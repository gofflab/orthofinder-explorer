/**
 * Species overview page: conservation profile per species (aligned to the
 * species tree when one is loaded), pairwise family-sharing heatmap, and the
 * sortable summary table.
 */
(function () {
  "use strict";

  /** Conservation classes in stacking order (broadest first). */
  const SEGMENTS = [
    { key: "broad", label: "Near-universal (≥ 90% of species)", token: "--chart-ordinal-4" },
    { key: "intermediate", label: "Intermediate", token: "--chart-ordinal-3" },
    { key: "narrow", label: "Narrow (≤ ⅓ of species)", token: "--chart-ordinal-2" },
    { key: "specific", label: "Species-specific", token: "--chart-ordinal-1" },
    { key: "unassigned", label: "Not in an orthogroup", token: "--chart-unassigned" },
  ];

  /**
   * Draw the tree-aligned stacked bars of genes by conservation class.
   *
   * @param {Object} data - /api/species response.
   * @param {Object} colors - Species name to clade color.
   * @param {boolean} normalize - Draw shares instead of counts.
   */
  function renderConservation(data, colors, normalize) {
    const card = CX.card("chart-conservation");
    const segments = SEGMENTS.map(function (segment) {
      return Object.assign({ color: CX.token(segment.token) }, segment);
    });
    const rows = data.species.map(function (species) {
      const values = Object.assign({}, species.classes, { unassigned: species.unassigned_genes || 0 });
      return { name: species.name, label: species.short_label, full: species.label, values: values, dot: colors[species.name] };
    });
    const host = card.clear();
    host.appendChild(CX.legend(segments));
    const plot = host.appendChild(CX.el("section"));
    CX.charts.stackedSpecies(plot, rows, {
      segments: segments,
      tree: data.tree,
      normalize: normalize,
      ariaLabel: "Genes per species by conservation class",
      onClick: function (row) { window.location.href = CX.link.species(row.name); },
      tooltip: function (row) {
        const total = d3.sum(segments, function (s) { return row.values[s.key] || 0; }) || 1;
        return {
          title: row.full,
          rows: segments.map(function (s) {
            const value = row.values[s.key] || 0;
            return [s.label, CX.fmt.int(value) + " (" + CX.fmt.pct0(value / total) + ")"];
          }),
        };
      },
    });
    card.setTable(
      [{ label: "Species", key: "full" }].concat(segments.map(function (s) {
        return { label: s.label, key: s.key, numeric: true, format: CX.fmt.int };
      })),
      rows.map(function (row) { return Object.assign({ full: row.full }, row.values); })
    );
  }

  /**
   * Draw the pairwise Jaccard-similarity heatmap.
   *
   * @param {Object} data - /api/species response.
   */
  function renderShared(data) {
    const card = CX.card("chart-shared");
    const shared = data.shared;
    const n = shared.names.length;
    if (n < 2) {
      card.status("At least two species are needed for a pairwise comparison.");
      return;
    }
    const cells = [];
    const tableRows = [];
    for (let r = 0; r < n; r += 1) {
      for (let c = 0; c < n; c += 1) {
        const both = shared.counts[r][c];
        const union = shared.counts[r][r] + shared.counts[c][c] - both;
        const jaccard = union ? both / union : 0;
        cells.push({ r: r, c: c, shared: both, jaccard: jaccard, diagonal: r === c });
        if (c > r) {
          tableRows.push({ a: shared.labels[r], b: shared.labels[c], shared: both, jaccard: jaccard });
        }
      }
    }
    const offDiagonal = cells.filter(function (cell) { return !cell.diagonal; });
    const extent = d3.extent(offDiagonal, function (cell) { return cell.jaccard; });
    const ramp = CX.charts.ramp("--chart-seq-a");
    const scale = d3.scaleLinear().domain(extent[0] === extent[1] ? [0, 1] : extent).range([0, 1]);
    const diagonalFill = CX.token("--chart-seq-neutral-low");
    cells.forEach(function (cell) {
      cell.fill = cell.diagonal ? diagonalFill : ramp(scale(cell.jaccard));
    });

    const host = card.clear();
    host.appendChild(CX.legend([
      { label: "Less similar (" + extent[0].toFixed(2) + ") to more similar (" + extent[1].toFixed(2) + ")",
        ramp: [ramp(0), ramp(0.5), ramp(1)] },
    ]));
    const plot = host.appendChild(CX.el("section"));
    CX.charts.heatmap(plot, {
      rows: shared.short_labels,
      cols: shared.short_labels,
      cells: cells,
      italic: true,
      rotate: true,
      maxCell: 30,
      ariaLabel: "Pairwise orthogroup sharing between species",
      onClick: function (cell) {
        if (!cell.diagonal) {
          window.location.href = CX.link.compare(shared.names[cell.r], shared.names[cell.c]);
        }
      },
      tooltip: function (cell) {
        if (cell.diagonal) {
          return { title: shared.labels[cell.r], rows: [["Orthogroups", CX.fmt.int(cell.shared)]] };
        }
        return {
          title: shared.labels[cell.r] + " × " + shared.labels[cell.c],
          rows: [
            ["Shared orthogroups", CX.fmt.int(cell.shared)],
            ["Jaccard similarity", cell.jaccard.toFixed(2)],
          ],
        };
      },
    });
    card.setTable(
      [
        { label: "Species A", key: "a" },
        { label: "Species B", key: "b" },
        { label: "Shared orthogroups", key: "shared", numeric: true, format: CX.fmt.int },
        { label: "Jaccard", key: "jaccard", numeric: true, format: d3.format(".3f") },
      ],
      tableRows
    );
  }

  /**
   * Render the per-species summary table.
   *
   * @param {Object} data - /api/species response.
   * @param {Object} colors - Species name to clade color.
   */
  function renderTable(data, colors) {
    // Percentage formatter that tolerates missing values.
    const pct = function (value) { return value === null ? "—" : CX.fmt.pct(value); };
    CX.dataTable(document.getElementById("species-table"), [
      {
        key: "label", label: "Species",
        render: function (row) {
          const dot = CX.el("span", { class: "clade-dot" });
          if (colors[row.name]) {
            dot.style.background = colors[row.name];
          }
          return CX.el("span", {}, [
            dot,
            CX.el("a", { href: CX.link.species(row.name), class: "species-name", text: row.label }),
          ]);
        },
      },
      { key: "proteins", label: "Proteins", numeric: true, format: CX.fmt.int },
      { key: "pct_assigned", label: "In orthogroups", numeric: true, format: pct },
      { key: "orthogroups", label: "Orthogroups", numeric: true, format: CX.fmt.int },
      { key: "species_specific_orthogroups", label: "Species-specific", numeric: true, format: CX.fmt.int,
        title: "Orthogroups found only in this species" },
      { key: "core_coverage", label: "Core coverage", numeric: true, format: pct,
        title: "Share of near-universal families that this species carries" },
      { key: "median_protein_length", label: "Median length (aa)", numeric: true, format: CX.fmt.int },
      {
        key: "transcripts", label: "Annotation", sortable: false,
        render: function (row) {
          const badges = [];
          if (row.transcripts) {
            badges.push(CX.el("span", { class: "badge-soft", text: "transcripts" }));
          }
          if (row.domain_hits) {
            badges.push(CX.el("span", { class: "badge-soft", text: "domains" }));
          }
          return CX.el("span", {}, badges.length ? badges : ["—"]);
        },
      },
    ], data.species, { pageSize: 0 });
  }

  /** Load the dataset summary and render the page. */
  async function init() {
    let data;
    let colors;
    try {
      const results = await Promise.all([CX.fetchJson(CX.urls.apiSpecies), CX.speciesColors()]);
      data = results[0];
      colors = results[1];
    } catch (error) {
      ["chart-conservation", "chart-shared"].forEach(function (id) { CX.card(id).status(error.message); });
      return;
    }
    if (!data.species.length) {
      ["chart-conservation", "chart-shared"].forEach(function (id) {
        CX.card(id).status("No species have been loaded yet.");
      });
      document.getElementById("species-table").replaceChildren();
      return;
    }

    const note = document.getElementById("dataset-note");
    note.textContent = CX.fmt.int(data.species.length) + " species · " +
      CX.fmt.int(data.n_orthogroups) + " orthogroups" +
      (data.dataset && data.dataset.name ? " · dataset: " + data.dataset.name : "") +
      (data.tree ? "" : " · no species tree loaded, so species are listed alphabetically");

    let normalize = false;
    // Draw (or redraw after a resize) both charts.
    const draw = function () {
      renderConservation(data, colors, normalize);
      renderShared(data);
    };
    CX.bindChoice(document.getElementById("conservation-unit"), function (value) {
      normalize = value === "share";
      renderConservation(data, colors, normalize);
    });
    draw();
    renderTable(data, colors);
    CX.onResize(draw);
  }

  init();
})();
