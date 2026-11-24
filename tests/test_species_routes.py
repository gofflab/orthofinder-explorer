"""Route tests for the Species and Species Comparison pages.

These need a real Flask installation.  ``conftest.py`` replaces Flask with a
``MagicMock`` when it is not installed, in which case the whole module is
skipped.  The app runs against a small synthetic database produced by
``scripts/build_demo_db.py``.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flask  # noqa: E402  (may be the MagicMock stub from conftest)

pytestmark = pytest.mark.skipif(
    isinstance(flask, MagicMock), reason="Flask is not installed"
)

A = "Homo_sapiens"
B = "Octopus_chierchiae"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Flask test client bound to a freshly built demo database."""
    from scripts.build_demo_db import build

    db_path = tmp_path_factory.mktemp("db") / "demo.db"
    build(db_path, n_orthogroups=120, seed=3)
    patch = pytest.MonkeyPatch()
    patch.setenv("ORTHOFINDER_DB_PATH", str(db_path))
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    yield app.test_client()
    patch.undo()


class TestPages:
    """HTML page shells for the species and comparison views."""

    def test_species_index_lists_species(self, client):
        response = client.get("/species")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Octopus chierchiae" in html
        assert "js/species-index.js" in html

    def test_species_page(self, client):
        response = client.get(f"/species/{B}")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Octopus chierchiae" in html
        assert "chart-strata" in html

    def test_unknown_species_page_is_404(self, client):
        assert client.get("/species/Not_a_species").status_code == 404

    def test_compare_page_without_selection_shows_picker_only(self, client):
        html = client.get("/compare").get_data(as_text=True)
        assert "Compare two species" in html
        assert "chart-landscape" not in html

    def test_compare_page_with_selection(self, client):
        response = client.get(f"/compare?a={A}&b={B}")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "chart-landscape" in html and "Homo sapiens" in html

    @pytest.mark.parametrize("query", [f"a={A}&b={A}", f"a={A}&b=Nope", f"a={A}"])
    def test_compare_page_with_invalid_selection_shows_picker_only(self, client, query):
        response = client.get(f"/compare?{query}")
        assert response.status_code == 200
        assert "chart-landscape" not in response.get_data(as_text=True)

    def test_navigation_links_present(self, client):
        html = client.get("/").get_data(as_text=True)
        assert 'href="/species"' in html and 'href="/compare"' in html


class TestSpeciesApi:
    """JSON endpoints under /api/species."""

    def test_species_listing(self, client):
        data = client.get("/api/species").get_json()
        assert len(data["species"]) == 21
        assert data["tree"] is not None
        names = [s["name"] for s in data["species"]]
        assert data["shared"]["names"] == names
        n = len(names)
        assert len(data["shared"]["counts"]) == n and len(data["shared"]["counts"][0]) == n
        row = next(s for s in data["species"] if s["name"] == B)
        assert row["proteins"] >= row["assigned_genes"] > 0
        assert row["transcripts"] > 0 and row["domain_hits"] > 0
        assert sum(row["classes"].values()) == row["assigned_genes"]

    def test_overview(self, client):
        data = client.get(f"/api/species/{B}/overview").get_json()
        assert data["species"]["name"] == B
        assert len(data["breadth"]) == data["n_species"] == 21
        assert len(data["shared"]) == 20
        strata = data["strata"]
        assert strata[0]["clade_size"] == 21 and strata[-1]["clade_size"] == 1
        assert sum(s["orthogroups"] for s in strata) == data["species"]["orthogroups"]
        assert sum(b["orthogroups"] for b in data["breadth"]) == data["species"]["orthogroups"]

    @pytest.mark.parametrize("category", ["expanded", "specific", "contracted", "absent"])
    def test_orthogroup_categories(self, client, category):
        data = client.get(
            f"/api/species/{B}/orthogroups?category={category}&min_other=1&limit=5"
        ).get_json()
        assert data["category"] == category
        assert len(data["rows"]) <= 5 <= max(data["total"], 5)
        for row in data["rows"]:
            if category == "specific":
                assert row["present_other"] == 0 and row["n_focal"] > 0
            if category == "absent":
                assert row["n_focal"] == 0

    def test_planted_expansion_is_ranked(self, client):
        data = client.get(
            f"/api/species/{B}/orthogroups?category=expanded&min_other=3&limit=50"
        ).get_json()
        # OG0000005 is the sulfotransferase family planted as a B expansion.
        assert "OG0000005" in [row["orthogroup_id"] for row in data["rows"]]

    def test_stratum_category(self, client):
        overview = client.get(f"/api/species/{B}/overview").get_json()
        last = overview["strata"][-1]
        data = client.get(
            f"/api/species/{B}/orthogroups?category=stratum&stratum={last['index']}&limit=500"
        ).get_json()
        assert data["total"] == last["orthogroups"] == overview["species"]["species_specific_orthogroups"]

    def test_exclude_parameter_changes_reference(self, client):
        base = client.get(f"/api/species/{B}/orthogroups?category=specific").get_json()
        relaxed = client.get(
            f"/api/species/{B}/orthogroups?category=specific"
            "&exclude=Octopus_bimaculoides,Octopus_sinensis,Not_a_species"
        ).get_json()
        assert relaxed["n_reference"] == base["n_reference"] - 2
        assert relaxed["total"] >= base["total"]

    def test_bad_category_and_species(self, client):
        assert client.get(f"/api/species/{B}/orthogroups?category=nope").status_code == 400
        response = client.get("/api/species/Nope/overview")
        assert response.status_code == 404
        assert "error" in response.get_json()

    def test_annotations(self, client):
        data = client.get(f"/api/species/{B}/annotations").get_json()
        assert data["proteins"]["count"] > 0
        assert data["transcripts"]["count"] > 0
        assert data["domains"]["database"] == "InterPro"
        assert 0 < len(data["domains"]["families"]) <= 20
        assert {c["class"] for c in data["domains"]["coverage_by_class"]} >= {"broad", "unassigned"}

    def test_annotations_for_unannotated_species(self, client):
        data = client.get("/api/species/Hydra_vulgaris/annotations").get_json()
        assert data["proteins"] is not None
        assert data["transcripts"] is None and data["domains"] is None

    def test_domains_endpoint(self, client):
        data = client.get(f"/api/species/{B}/domains?db=Pfam&limit=3").get_json()
        assert data["database"] == "Pfam"
        assert set(data["databases"]) == {"InterPro", "Pfam", "PANTHER"}
        assert len(data["families"]) == 3
        assert all(f["database"] == "Pfam" for f in data["families"])
        empty = client.get("/api/species/Hydra_vulgaris/domains").get_json()
        assert empty == {"database": None, "databases": [], "families": []}


class TestCompareApi:
    """JSON endpoints under /api/compare."""

    def test_compare(self, client):
        data = client.get(f"/api/compare?a={A}&b={B}").get_json()
        assert data["a"]["name"] == A and data["b"]["name"] == B
        assert data["n_reference"] == 19
        og = data["orthogroups"]
        n = len(og["ids"])
        assert n == data["summary"]["union"]
        assert all(len(og[key]) == n for key in ("a", "b", "ref", "ref_present"))
        assert all(a > 0 or b > 0 for a, b in zip(og["a"], og["b"]))
        classes = data["summary"]["classes"]
        shared = sum(classes[k]["orthogroups"] for k in
                     ("one_to_one", "one_to_many", "many_to_one", "many_to_many"))
        assert shared == data["summary"]["shared"]
        # The planted KRAB family is large in human and nearly absent in octopus.
        krab = og["ids"].index("OG0000002")
        assert og["a"][krab] > 100 and og["b"][krab] <= 1

    def test_compare_is_antisymmetric(self, client):
        forward = client.get(f"/api/compare?a={A}&b={B}").get_json()["summary"]["classes"]
        reverse = client.get(f"/api/compare?a={B}&b={A}").get_json()["summary"]["classes"]
        assert forward["a_only"]["orthogroups"] == reverse["b_only"]["orthogroups"]
        assert forward["one_to_many"]["orthogroups"] == reverse["many_to_one"]["orthogroups"]

    def test_compare_errors(self, client):
        assert client.get(f"/api/compare?a={A}&b={A}").status_code == 400
        assert client.get(f"/api/compare?a={A}&b=Nope").status_code == 404
        assert client.get("/api/compare").status_code == 400

    def test_compare_domains(self, client):
        data = client.get(f"/api/compare/domains?a={A}&b={B}").get_json()
        assert data["database"] == "InterPro"
        assert "Pfam" in data["databases"]
        assert data["rows"] and {"accession", "a", "b", "description", "name"} <= set(data["rows"][0])
        pfam = client.get(f"/api/compare/domains?a={A}&b={B}&db=Pfam").get_json()
        krab = next(r for r in pfam["rows"] if r["accession"] == "PF01352")
        assert krab["a"] > 100 and krab["b"] <= 1

    def test_compare_domains_without_annotations(self, client):
        data = client.get(f"/api/compare/domains?a={A}&b=Hydra_vulgaris").get_json()
        assert data == {"database": None, "databases": [], "rows": []}


class TestOrthogroupApi:
    """Orthogroup profile and annotation endpoints."""

    def test_profile(self, client):
        data = client.get("/api/orthogroup/OG0000000/profile").get_json()
        assert len(data["counts"]) == 21
        counts = {c["name"]: c["count"] for c in data["counts"]}
        assert counts[B] > counts[A]        # planted cephalopod protocadherin expansion
        assert client.get("/api/orthogroup/NOPE/profile").status_code == 404

    def test_annotations(self, client):
        response = client.post("/api/orthogroups/annotations", json={"ids": ["OG0000000", "NOPE"]})
        data = response.get_json()
        assert data["OG0000000"]["description"] == "Protocadherin"
        assert data["OG0000000"]["labels"][0]["label"].startswith("Cadherin")
        assert "NOPE" not in data

    def test_annotations_rejects_bad_payload(self, client):
        assert client.post("/api/orthogroups/annotations", json={"ids": "OG1"}).status_code == 400
        assert client.post("/api/orthogroups/annotations", data="x").status_code == 400
