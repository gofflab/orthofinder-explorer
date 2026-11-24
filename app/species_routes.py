"""Routes for the Species and Species Comparison pages.

HTML routes render lightweight page shells; the numbers and plots are loaded
asynchronously from the JSON endpoints defined alongside them so that a slow
first computation never blocks the initial page render.
"""

import os

from flask import abort, jsonify, render_template, request

from . import db
from .analysis import annotations, compare, species_stats
from .analysis.phylostrata import summarize_strata
from .analysis.matrix import species_label, species_short_label
from .analysis.store import AnalysisStore

#: Hard ceiling on rows returned by the notable-orthogroup endpoint.
MAX_ORTHOGROUP_ROWS = 500

#: Default number of domain families returned for a species.
DEFAULT_DOMAIN_ROWS = 20


def register_species_routes(app):
    """Attach the species pages and their JSON API to the Flask app.

    Args:
        app: Flask application instance.
    """
    ttl = float(os.environ.get("ORTHOFINDER_ANALYSIS_CACHE_TTL", "1800"))
    store = AnalysisStore(lambda: db.session, ttl=ttl)
    app.extensions["analysis_store"] = store

    # -- helpers ------------------------------------------------------------

    def species_options():
        """List species for the page pickers, in display order.

        Returns:
            List of ``{"name", "label"}`` dicts.
        """
        return [
            {"name": name, "label": species_label(name)}
            for name in store.species_order()
        ]

    def require_species(species_name, as_json=True):
        """Resolve a species name to its matrix column or abort with 404.

        Args:
            species_name: Species name from the URL or query string.
            as_json: Return a JSON error body (API) instead of an HTML 404.

        Returns:
            Tuple ``(matrix, column)``.
        """
        matrix = store.matrix()
        try:
            return matrix, matrix.column(species_name)
        except KeyError:
            if as_json:
                abort(_json_error(f"Unknown species: {species_name}", 404))
            abort(404)

    def excluded_columns(matrix):
        """Parse the ``exclude`` query parameter into matrix columns.

        Returns:
            List of column indices for recognised species names; unknown names
            are ignored.
        """
        raw = request.args.get("exclude", "")
        columns = []
        for name in filter(None, (part.strip() for part in raw.split(","))):
            try:
                columns.append(matrix.column(name))
            except KeyError:
                continue
        return columns

    def _json_error(message, status):
        """Build a JSON error response.

        Args:
            message: Human-readable error description.
            status: HTTP status code.

        Returns:
            Flask response object.
        """
        response = jsonify({"error": message})
        response.status_code = status
        return response

    def family_rows(species_name, database, limit=None):
        """Return a species' domain families for one database.

        Args:
            species_name: Database species name.
            database: Domain database name.
            limit: Optional maximum number of rows (largest families first).

        Returns:
            List of family dicts.
        """
        rows = [
            row
            for row in store.domain_bundle(species_name)["families"]
            if row["database"] == database
        ]
        return rows[:limit] if limit else rows

    def database_names(species_name):
        """List the domain databases available for a species."""
        summary = store.domain_bundle(species_name)["summary"]
        return [entry["name"] for entry in summary["databases"]] if summary else []

    # -- pages --------------------------------------------------------------

    @app.route("/species")
    def species_index():
        """Render the species overview page (all species, tree, pairwise map)."""
        return render_template("species_index.html", species_options=species_options())

    @app.route("/species/<string:species_name>")
    def species_detail(species_name):
        """Render the page shell for a single species.

        Args:
            species_name: Database species name from the URL.
        """
        require_species(species_name, as_json=False)
        return render_template(
            "species.html",
            species={"name": species_name, "label": species_label(species_name)},
            species_options=species_options(),
        )

    @app.route("/compare")
    def species_compare():
        """Render the species comparison page.

        Query parameters ``a`` and ``b`` select the two species; when either is
        missing or unknown only the species pickers are shown.
        """
        options = species_options()
        names = {option["name"] for option in options}
        a = request.args.get("a")
        b = request.args.get("b")
        selected = a in names and b in names and a != b
        return render_template(
            "species_compare.html",
            species_options=options,
            species_a={"name": a, "label": species_label(a)} if a in names else None,
            species_b={"name": b, "label": species_label(b)} if b in names else None,
            selected=selected,
        )

    # -- API: dataset -------------------------------------------------------

    @app.route("/api/species")
    def api_species():
        """Return the summary table, species tree and pairwise sharing matrix."""
        matrix = store.matrix()
        order = store.species_order()
        return jsonify(
            {
                "dataset": store.dataset(),
                "n_orthogroups": matrix.n_orthogroups,
                "species": store.species_rows(),
                "tree": store.tree(),
                "shared": species_stats.shared_matrix(matrix, order),
                "class_labels": list(species_stats.BREADTH_CLASSES),
            }
        )

    # -- API: single species --------------------------------------------------

    @app.route("/api/species/<string:species_name>/overview")
    def api_species_overview(species_name):
        """Return summary statistics and distributions for one species."""
        matrix, column = require_species(species_name)
        rows = store.species_rows()
        order = {row["name"]: i for i, row in enumerate(rows)}
        shared = sorted(
            species_stats.shared_with_others(matrix, column),
            key=lambda row: order.get(row["name"], 0),
        )
        strata, assignment = store.strata(species_name)
        strata_summary = None
        if strata:
            strata_summary = summarize_strata(matrix, column, strata, assignment)
            for entry in strata_summary:
                entry["joined_labels"] = [species_short_label(n) for n in entry["joined"]]
        return jsonify(
            {
                "species": next(row for row in rows if row["name"] == species_name),
                "all_species": rows,
                "n_species": matrix.n_species,
                "breadth": species_stats.breadth_histogram(matrix, column),
                "copy_number": species_stats.copy_number_histogram(matrix, column),
                "shared": shared,
                "strata": strata_summary,
            }
        )

    @app.route("/api/species/<string:species_name>/orthogroups")
    def api_species_orthogroups(species_name):
        """Return ranked notable orthogroups for one species.

        Query parameters: ``category`` (specific, expanded, contracted, absent,
        stratum), ``min_other``, ``limit``, ``stratum`` and ``exclude``.
        """
        matrix, column = require_species(species_name)
        category = request.args.get("category", "expanded")
        if category not in species_stats.NOTABLE_CATEGORIES:
            return _json_error(f"Unknown category: {category}", 400)
        limit = min(request.args.get("limit", 50, type=int), MAX_ORTHOGROUP_ROWS)
        assignment = None
        stratum = request.args.get("stratum", type=int)
        if category == "stratum":
            _, assignment = store.strata(species_name)
        result = species_stats.notable_orthogroups(
            matrix,
            column,
            category,
            min_other=max(request.args.get("min_other", 3, type=int), 0),
            limit=limit,
            exclude=excluded_columns(matrix),
            assignment=assignment,
            stratum=stratum,
        )
        result["category"] = category
        return jsonify(result)

    @app.route("/api/species/<string:species_name>/annotations")
    def api_species_annotations(species_name):
        """Return protein, transcript and domain annotation statistics."""
        matrix, column = require_species(species_name)
        species_id = matrix.species_ids[column]
        bundle = store.domain_bundle(species_name)
        domains = None
        if bundle["summary"]:
            databases = database_names(species_name)
            default = annotations.preferred_database(databases)
            domains = {
                "summary": bundle["summary"],
                "coverage_by_class": bundle["coverage_by_class"],
                "database": default,
                "families": family_rows(species_name, default, DEFAULT_DOMAIN_ROWS),
            }
        return jsonify(
            {
                "proteins": annotations.length_stats(store.protein_lengths().get(species_id)),
                "transcripts": store.transcript_stats(species_id),
                "domains": domains,
            }
        )

    @app.route("/api/species/<string:species_name>/domains")
    def api_species_domains(species_name):
        """Return the largest domain families for one species and database."""
        require_species(species_name)
        databases = database_names(species_name)
        database = request.args.get("db") or annotations.preferred_database(databases)
        limit = min(request.args.get("limit", DEFAULT_DOMAIN_ROWS, type=int), 200)
        return jsonify(
            {
                "database": database,
                "databases": databases,
                "families": family_rows(species_name, database, limit) if database else [],
            }
        )

    # -- API: comparison ------------------------------------------------------

    @app.route("/api/compare")
    def api_compare():
        """Return the orthogroup-level comparison of species ``a`` and ``b``."""
        name_a = request.args.get("a", "")
        name_b = request.args.get("b", "")
        if name_a == name_b:
            return _json_error("Choose two different species.", 400)
        matrix, column_a = require_species(name_a)
        _, column_b = require_species(name_b)
        return jsonify(
            compare.compare_species(
                matrix, column_a, column_b, exclude=excluded_columns(matrix)
            )
        )

    @app.route("/api/compare/domains")
    def api_compare_domains():
        """Return domain-family sizes for species ``a`` and ``b`` side by side."""
        name_a = request.args.get("a", "")
        name_b = request.args.get("b", "")
        require_species(name_a)
        require_species(name_b)
        names_b = set(database_names(name_b))
        shared = [name for name in database_names(name_a) if name in names_b]
        database = request.args.get("db")
        if database not in shared:
            database = annotations.preferred_database(shared)
        rows = []
        if database:
            rows = compare.compare_domain_tables(
                store.domain_bundle(name_a)["families"],
                store.domain_bundle(name_b)["families"],
                database,
            )
        return jsonify({"database": database, "databases": shared, "rows": rows})

    # -- API: orthogroups -----------------------------------------------------

    @app.route("/api/orthogroup/<string:orthogroup_id>/profile")
    def api_orthogroup_profile(orthogroup_id):
        """Return one orthogroup's copy number in every species."""
        profile = species_stats.orthogroup_profile(
            store.matrix(), orthogroup_id, store.species_order()
        )
        if profile is None:
            return _json_error(f"Unknown orthogroup: {orthogroup_id}", 404)
        return jsonify({"orthogroup_id": orthogroup_id, "counts": profile})

    @app.route("/api/orthogroups/annotations", methods=["POST"])
    def api_orthogroup_annotations():
        """Return representative domain annotations for a list of orthogroups.

        Expects a JSON body ``{"ids": ["OG0000001", ...]}``.
        """
        payload = request.get_json(silent=True) or {}
        ids = payload.get("ids")
        if not isinstance(ids, list):
            return _json_error("Expected a JSON body with an 'ids' list.", 400)
        ids = [str(value) for value in ids]
        return jsonify(annotations.orthogroup_annotations(db.session, ids))
