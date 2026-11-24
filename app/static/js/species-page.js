/**
 * Single-species page: summary tiles, conservation and gene-age charts,
 * cross-species context, notable orthogroups and annotation statistics.
 *
 * Reads CX.page.species ({ name, label }) set by the template.
 */
(function () {
  "use strict";

  const species = CX.page.species;
  const dash = "—";

  /** Shared page state. */
  const state = {
    unit: "orthogroups",       // or "genes"
    category: "expanded",
    stratum: null,
    exclude: [],
    overview: null,
    colors: {},
  };

  /** Plain-language description of each notable-orthogroup category. */
  const CATEGORY_TEXT = {
    expanded: "Families shared with other species in which this species has at least two more copies than the reference median, ranked by log2 ratio.",
    specific: "Families found only in this species, largest first. With close relatives in the dataset this list is short; see the gene-age chart for lineage-restricted families.",
    contracted: "Families in which this species has at least two fewer copies than the reference median, ranked by log2 ratio.",
    absent: "Families missing from this species but present in other species, most widely conserved first. These are candidate losses or annotation gaps.",
    stratum: "Families assigned to the selected gene-age stratum, largest first.",
  };

  /** Measures offered by the cross-species context chart. */
  const METRICS = {
    proteins: { label: "Proteins", format: CX.fmt.int },
    pct_assigned: { label: "Share of genes in orthogroups", format: CX.fmt.pct },
    orthogroups: { label: "Orthogroups", format: CX.fmt.int },
    species_specific_orthogroups: { label: "Species-specific families", format: CX.fmt.int },
    core_coverage: { label: "Core family coverage", format: CX.fmt.pct },
    median_protein_length: { label: "Median protein length (aa)", format: CX.fmt.int },
  };

  /** Human-readable names for the conservation classes. */
  const CLASS_LABELS = {
    specific: "Species-specific",
    narrow: "Narrow (≤ ⅓ of species)",
    intermediate: "Intermediate",
    broad: "Near-universal",
    unassigned: "Not in an orthogroup",
  };

  /**
   * Label a gene-age stratum by the lineage that joins at that split.
   *
   * @param {Object} stratum - Entry of overview.strata.
   * @param {boolean} last - True for the final (species-specific) stratum.
   * @returns {string}
   */
  function stratumLabel(stratum, last) {
    if (last) {
      return "This species only";
    }
    const names = stratum.joined_labels;
    if (names.length <= 2) {
      return "+ " + names.join(", ");
    }
    return "+ " + names[0] + " and " + (names.length - 1) + " more";
  }

  // ---- Summary tiles -------------------------------------------------------

  /** Fill the headline stat tiles from the overview payload. */
  function renderTiles() {
    const s = state.overview.species;
    CX.setStat("stat-proteins", s.proteins === null ? dash : CX.fmt.int(s.proteins), "Input to OrthoFinder");
    CX.setStat(
      "stat-assigned",
      s.pct_assigned === null ? dash : CX.fmt.pct(s.pct_assigned),
      CX.fmt.int(s.assigned_genes) + " genes" +
        (s.unassigned_genes === null ? "" : " · " + CX.fmt.int(s.unassigned_genes) + " unassigned")
    );
    CX.setStat(
      "stat-orthogroups", CX.fmt.int(s.orthogroups),
      CX.fmt.int(s.single_copy_orthogroups) + " single-copy · " + CX.fmt.int(s.multi_copy_orthogroups) + " multi-copy"
    );
    CX.setStat(
      "stat-specific", CX.fmt.int(s.species_specific_orthogroups),
      CX.fmt.int(s.species_specific_genes) + " genes"
    );
    CX.setStat(
      "stat-core",
      s.core_coverage === null ? dash : CX.fmt.pct(s.core_coverage),
      CX.fmt.int(s.core_present) + " of " + CX.fmt.int(s.core_total) + " near-universal families"
    );
    CX.setStat(
      "stat-length",
      s.median_protein_length === null ? dash : CX.fmt.int(s.median_protein_length) + " aa",
      "Largest family: " + CX.fmt.int(s.largest_family) + " genes"
    );
  }

  // ---- Conservation charts -------------------------------------------------

  /** Columns: number of species sharing each of this species' families. */
  function renderBreadth() {
    const card = CX.card("chart-breadth");
    const unit = state.unit;
    const rows = state.overview.breadth.map(function (entry) {
      return { label: String(entry.n_species), value: entry[unit], orthogroups: entry.orthogroups, genes: entry.genes };
    });
    card.subtitle(
      (unit === "genes" ? "Genes" : "Orthogroups") + " of this species by the number of species in the family."
    );
    CX.charts.columns(card.clear(), rows, {
      color: CX.token("--chart-series-a"),
      xLabel: "Species represented in the family",
      yLabel: unit === "genes" ? "Genes" : "Orthogroups",
      ariaLabel: "Families by number of species sharing them",
      tooltip: function (d) {
        return {
          title: d.label + (d.label === "1" ? " species (this one only)" : " species"),
          rows: [["Orthogroups", CX.fmt.int(d.orthogroups)], ["Genes", CX.fmt.int(d.genes)]],
        };
      },
    });
    card.setTable(
      [
        { label: "Species in family", key: "label", numeric: true },
        { label: "Orthogroups", key: "orthogroups", numeric: true, format: CX.fmt.int },
        { label: "Genes", key: "genes", numeric: true, format: CX.fmt.int },
      ],
      rows
    );
  }

  /** Horizontal bars: gene-age strata from the root to this species. */
  function renderStrata() {
    const card = CX.card("chart-strata");
    const strata = state.overview.strata;
    if (!strata || !strata.length) {
      card.subtitle("");
      card.status(
        "No species tree is loaded, so gene age cannot be estimated. Load the OrthoFinder species tree " +
        "with scripts/upgrade_db.py to enable this chart."
      );
      return;
    }
    const unit = state.unit;
    const rows = strata.map(function (stratum, i) {
      return {
        label: stratumLabel(stratum, i === strata.length - 1),
        value: stratum[unit],
        stratum: stratum,
        emphasis: state.category === "stratum" && state.stratum === stratum.index,
      };
    });
    card.subtitle(
      (unit === "genes" ? "Genes" : "Orthogroups") +
      " by the deepest split their family spans, oldest at the top. Click a row to list its families."
    );
    CX.charts.barsH(card.clear(), rows, {
      color: CX.token("--chart-series-a"),
      maxLabelWidth: 210,
      ariaLabel: "Gene age strata",
      onClick: function (d) { showStratum(d.stratum, d.label); },
      tooltip: function (d) {
        const joined = d.stratum.joined_labels;
        return {
          title: "Clade of " + d.stratum.clade_size + " species",
          rows: [["Orthogroups", CX.fmt.int(d.stratum.orthogroups)], ["Genes", CX.fmt.int(d.stratum.genes)]],
          note: joined.length ? "Lineage joining here: " + joined.join(", ") : "Found only in this species.",
        };
      },
    });
    card.setTable(
      [
        { label: "Stratum", key: "label" },
        { label: "Species in clade", key: "clade_size", numeric: true },
        { label: "Orthogroups", key: "orthogroups", numeric: true, format: CX.fmt.int },
        { label: "Genes", key: "genes", numeric: true, format: CX.fmt.int },
      ],
      rows.map(function (row) { return Object.assign({ label: row.label }, row.stratum); })
    );
  }

  /** Columns: family size (copy number) distribution. */
  function renderCopy() {
    const card = CX.card("chart-copy");
    const unit = state.unit;
    const rows = state.overview.copy_number.map(function (entry) {
      return { label: entry.label, value: entry[unit], orthogroups: entry.orthogroups, genes: entry.genes };
    });
    card.subtitle((unit === "genes" ? "Genes" : "Orthogroups") + " by the number of copies in this species.");
    CX.charts.columns(card.clear(), rows, {
      color: CX.token("--chart-series-a"),
      xLabel: "Gene copies in this species",
      yLabel: unit === "genes" ? "Genes" : "Orthogroups",
      ariaLabel: "Family size distribution",
      tooltip: function (d) {
        return {
          title: d.label + (d.label === "1" ? " copy" : " copies"),
          rows: [["Orthogroups", CX.fmt.int(d.orthogroups)], ["Genes", CX.fmt.int(d.genes)]],
        };
      },
    });
    card.setTable(
      [
        { label: "Copies", key: "label" },
        { label: "Orthogroups", key: "orthogroups", numeric: true, format: CX.fmt.int },
        { label: "Genes", key: "genes", numeric: true, format: CX.fmt.int },
      ],
      rows
    );
  }

  /** Horizontal bars: orthogroups shared with each other species. */
  function renderShared() {
    const card = CX.card("chart-shared");
    const rows = state.overview.shared.map(function (entry) {
      return Object.assign({ value: entry.shared, italic: true, dot: state.colors[entry.name] }, entry, {
        label: entry.short_label, full: entry.label,
      });
    });
    if (!rows.length) {
      card.status("No other species to compare with.");
      return;
    }
    CX.charts.barsH(card.clear(), rows, {
      color: CX.token("--chart-series-a"),
      rowHeight: 21,
      barHeight: 11,
      ariaLabel: "Orthogroups shared with each other species",
      onClick: function (d) { window.location.href = CX.link.compare(species.name, d.name); },
      tooltip: function (d) {
        return {
          title: d.full,
          rows: [
            ["Shared orthogroups", CX.fmt.int(d.shared)],
            ["Only in " + state.overview.species.short_label, CX.fmt.int(d.focal_only)],
            ["Only in " + d.short_label, CX.fmt.int(d.other_only)],
            ["Jaccard similarity", d.jaccard.toFixed(2)],
          ],
        };
      },
    });
    card.setTable(
      [
        { label: "Species", key: "full" },
        { label: "Shared orthogroups", key: "shared", numeric: true, format: CX.fmt.int },
        { label: "Only in this species", key: "focal_only", numeric: true, format: CX.fmt.int },
        { label: "Only in the other", key: "other_only", numeric: true, format: CX.fmt.int },
        { label: "Jaccard", key: "jaccard", numeric: true, format: d3.format(".3f") },
      ],
      rows
    );
  }

  /** Horizontal bars: one measure across all species, this one highlighted. */
  function renderContext() {
    const card = CX.card("chart-context");
    const key = document.getElementById("context-metric").value;
    const metric = METRICS[key];
    const focal = CX.token("--chart-series-a");
    const neutral = CX.token("--chart-neutral");
    const rows = state.overview.all_species
      .filter(function (entry) { return entry[key] !== null && entry[key] !== undefined; })
      .map(function (entry) {
        const isFocal = entry.name === species.name;
        return {
          name: entry.name, label: entry.short_label, full: entry.label, value: entry[key],
          italic: true, emphasis: isFocal, color: isFocal ? focal : neutral, dot: state.colors[entry.name],
        };
      });
    card.title(metric.label + " across all species");
    card.subtitle("This species is highlighted. Click a bar to open that species.");
    CX.charts.barsH(card.clear(), rows, {
      valueFormat: metric.format,
      rowHeight: 21,
      barHeight: 11,
      ariaLabel: metric.label + " for every species",
      onClick: function (d) {
        if (d.name !== species.name) {
          window.location.href = CX.link.species(d.name);
        }
      },
      tooltip: function (d) { return { title: d.full, rows: [[metric.label, metric.format(d.value)]] }; },
    });
    card.setTable(
      [{ label: "Species", key: "full" }, { label: metric.label, key: "value", numeric: true, format: metric.format }],
      rows
    );
  }

  // ---- Notable orthogroups -------------------------------------------------

  let notableTable = null;

  /** Fetch and display the orthogroups for the active category. */
  async function loadNotable() {
    const host = document.getElementById("notable-table");
    const description = document.getElementById("notable-description");
    description.textContent = CATEGORY_TEXT[state.category];
    host.style.opacity = 0.5;
    let result;
    try {
      result = await CX.fetchJson(CX.link.api(CX.urls.apiSpeciesOrthogroups, species.name, {
        category: state.category,
        stratum: state.category === "stratum" ? state.stratum : null,
        min_other: document.getElementById("min-other").value,
        exclude: state.exclude.join(","),
        limit: 300,
      }));
    } catch (error) {
      host.style.opacity = 1;
      host.replaceChildren(CX.el("p", { class: "chart-status", text: error.message }));
      return;
    }
    host.style.opacity = 1;
    const nReference = result.n_reference;
    if (!notableTable) {
      notableTable = CX.OrthogroupTable(host, {
        columns: [
          { key: "n_focal", label: "Copies", numeric: true, format: CX.fmt.int, title: "Gene copies in this species" },
          { key: "median_other", label: "Ref. median", numeric: true, format: CX.fmt.fixed1,
            title: "Median copies among reference species that carry the family" },
          { key: "max_other", label: "Ref. max", numeric: true, format: CX.fmt.int,
            title: "Largest copy number in any reference species" },
          { key: "log2_ratio", label: "log2 ratio", numeric: true, format: CX.fmt.signed,
            title: "log2((copies + 1) / (reference median + 1))" },
          { key: "present_other", label: "In ref. spp.", numeric: true,
            format: function (value) { return value + " / " + notableTable.nReference; },
            title: "Reference species that carry the family" },
        ],
        emptyMessage: "No orthogroups match this category with the current filters.",
        onSelect: function (row) {
          const highlight = {};
          highlight[species.name] = CX.token("--chart-series-a");
          CX.orthogroupProfile("chart-profile", row.orthogroup_id, { highlight: highlight });
        },
      });
    }
    notableTable.nReference = nReference;
    notableTable.setRows(
      result.rows,
      CX.fmt.int(result.total) + " orthogroups in this category"
    );
  }

  /**
   * Switch the notable-orthogroup list to one gene-age stratum.
   *
   * @param {Object} stratum - Entry of overview.strata.
   * @param {string} label - Display label of the stratum.
   */
  function showStratum(stratum, label) {
    state.category = "stratum";
    state.stratum = stratum.index;
    const tabs = document.getElementById("notable-tabs");
    tabs.querySelectorAll("button").forEach(function (button) {
      const isStratum = button.dataset.value === "stratum";
      button.setAttribute("aria-selected", String(isStratum));
      if (isStratum) {
        button.hidden = false;
        button.textContent = "Gene age: " + label;
      }
    });
    renderStrata();
    loadNotable();
    document.getElementById("notable").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---- Annotation ----------------------------------------------------------

  /** Histogram of protein lengths with the median marked. */
  function renderLengths(proteins) {
    const card = CX.card("chart-length");
    if (!proteins) {
      card.status("No protein sequences are loaded for this species.");
      return;
    }
    card.subtitle(
      CX.fmt.int(proteins.count) + " proteins · median " + CX.fmt.int(proteins.median) + " aa · " +
      CX.fmt.pct(proteins.short_fraction) + " shorter than 100 aa · longest " + CX.fmt.int(proteins.max) + " aa"
    );
    card.draw = function () {
      CX.charts.histogram(card.clear(), proteins.histogram, {
        color: CX.token("--chart-series-a"),
        xLabel: "Protein length (aa)",
        yLabel: "Proteins",
        ariaLabel: "Protein length distribution",
        markers: [{ x: proteins.median, label: "median " + CX.fmt.int(proteins.median) }],
      });
    };
    card.draw();
    card.setTable(
      [
        { label: "From (aa)", key: "x0", numeric: true, format: CX.fmt.int },
        { label: "To (aa)", key: "x1", numeric: true, format: function (v) { return v === null ? "" : CX.fmt.int(v); } },
        { label: "Proteins", key: "count", numeric: true, format: CX.fmt.int },
      ],
      proteins.histogram
    );
    return card.draw;
  }

  /**
   * Draw a simple binned-count column chart into a card.
   *
   * @param {string} cardId - Chart card id.
   * @param {Array<Object>} bins - { label, count } entries.
   * @param {string} xLabel - X-axis title.
   * @param {string} yLabel - Y-axis title.
   * @returns {Function} Redraw callback.
   */
  function binnedColumns(cardId, bins, xLabel, yLabel) {
    const card = CX.card(cardId);
    const rows = bins.map(function (bin) { return { label: bin.label, value: bin.count }; });
    // Redraw callback (also used after a window resize).
    const draw = function () {
      CX.charts.columns(card.clear(), rows, {
        color: CX.token("--chart-series-a"), xLabel: xLabel, yLabel: yLabel, ariaLabel: xLabel,
      });
    };
    draw();
    card.setTable(
      [{ label: xLabel, key: "label" }, { label: yLabel, key: "value", numeric: true, format: CX.fmt.int }],
      rows
    );
    return draw;
  }

  /** Transcript tiles and charts, or an explanatory empty state. */
  function renderTranscripts(transcripts) {
    const redraws = [];
    if (!transcripts) {
      document.getElementById("transcript-charts").replaceChildren(
        CX.el("p", { class: "chart-status", text: "No transcript annotation (GTF/GFF3) has been loaded for this species." })
      );
      return redraws;
    }
    document.getElementById("transcript-stats").hidden = false;
    CX.setStat("stat-transcripts", CX.fmt.int(transcripts.count),
      CX.fmt.int(transcripts.with_mrna) + " with an mRNA sequence");
    CX.setStat("stat-tx-genes", CX.fmt.int(transcripts.genes),
      CX.fmt.int(transcripts.matched_genes) + " linked to orthogroup genes");
    CX.setStat("stat-isoforms",
      transcripts.mean_isoforms === null ? dash : transcripts.mean_isoforms.toFixed(2), "Mean per gene");
    CX.setStat("stat-monoexonic",
      transcripts.mono_exonic_fraction === null ? dash : CX.fmt.pct(transcripts.mono_exonic_fraction),
      transcripts.median_exons === null ? "" : "Median " + CX.fmt.int(transcripts.median_exons) + " exons");
    CX.setStat("stat-cds",
      transcripts.median_cds_length === null ? dash : CX.fmt.int(transcripts.median_cds_length) + " nt",
      transcripts.biotypes.map(function (b) { return b.label + " " + CX.fmt.int(b.count); }).join(" · "));
    redraws.push(binnedColumns("chart-isoforms", transcripts.isoform_histogram, "Isoforms per gene", "Genes"));
    if (transcripts.with_structure) {
      redraws.push(binnedColumns("chart-exons", transcripts.exon_histogram, "Exons per transcript", "Transcripts"));
    } else {
      CX.card("chart-exons").status("Transcripts were loaded from an mRNA FASTA only, so exon structure is unavailable.");
    }
    return redraws;
  }

  /** Top domain families for the selected database. */
  function renderDomainFamilies(database, families) {
    const card = CX.card("chart-domains");
    const rows = families.map(function (family) {
      const text = family.description || family.name || family.accession;
      return {
        label: text.length > 34 ? text.slice(0, 33) + "…" : text,
        full: text, accession: family.accession, value: family.genes,
      };
    });
    card.subtitle("Genes carrying each " + database + " family (top " + rows.length + ").");
    if (!rows.length) {
      card.status("No families for this database.");
      return function () {};
    }
    // Redraw callback (also used after a window resize).
    const draw = function () {
      CX.charts.barsH(card.clear(), rows, {
        color: CX.token("--chart-series-a"),
        rowHeight: 21,
        barHeight: 11,
        maxLabelWidth: 230,
        ariaLabel: "Largest " + database + " domain families",
        tooltip: function (d) {
          return { title: d.full, rows: [["Accession", d.accession], ["Genes", CX.fmt.int(d.value)]] };
        },
      });
    };
    draw();
    card.setTable(
      [
        { label: "Accession", key: "accession" },
        { label: "Description", key: "full" },
        { label: "Genes", key: "value", numeric: true, format: CX.fmt.int },
      ],
      rows
    );
    return draw;
  }

  /** Domain tiles, family chart and coverage-by-conservation chart. */
  function renderDomains(domains) {
    const redraws = [];
    if (!domains) {
      document.getElementById("domain-charts").replaceChildren(
        CX.el("p", { class: "chart-status", text: "No protein-domain annotation (InterProScan or Pfam) has been loaded for this species." })
      );
      return redraws;
    }
    const summary = domains.summary;
    document.getElementById("domain-stats").hidden = false;
    CX.setStat("stat-domain-coverage",
      summary.coverage === null ? dash : CX.fmt.pct(Math.min(summary.coverage, 1)),
      CX.fmt.int(summary.genes_with_domain) + " proteins with at least one hit");
    CX.setStat("stat-domain-hits", CX.fmt.int(summary.hits),
      summary.databases.map(function (d) { return d.name; }).join(" · "));
    CX.setStat("stat-domain-go", CX.fmt.int(summary.genes_with_go),
      summary.unmatched_hits ? CX.fmt.int(summary.unmatched_hits) + " hits not linked to a gene" : "");

    const select = document.getElementById("domain-database");
    document.getElementById("domain-controls").hidden = false;
    summary.databases.forEach(function (database) {
      select.appendChild(CX.el("option", {
        value: database.name, text: database.name + " (" + CX.fmt.int(database.genes) + " genes)",
        selected: database.name === domains.database,
      }));
    });
    let familyDraw = renderDomainFamilies(domains.database, domains.families);
    select.addEventListener("change", async function () {
      const card = CX.card("chart-domains");
      card.body.style.opacity = 0.5;
      try {
        const result = await CX.fetchJson(CX.link.api(CX.urls.apiSpeciesDomains, species.name, { db: select.value }));
        familyDraw = renderDomainFamilies(result.database, result.families);
      } catch (error) {
        card.status(error.message);
      }
      card.body.style.opacity = 1;
    });
    redraws.push(function () { familyDraw(); });

    const coverageCard = CX.card("chart-domain-coverage");
    const coverageRows = domains.coverage_by_class
      .filter(function (entry) { return entry.genes > 0; })
      .map(function (entry) {
        const share = entry.with_domain / entry.genes;
        return {
          label: CLASS_LABELS[entry.class] || entry.class, value: share,
          genes: entry.genes, with_domain: entry.with_domain,
          valueText: CX.fmt.pct0(share) + " of " + CX.fmt.int(entry.genes),
        };
      });
    // Redraw callback for the coverage-by-conservation chart.
    const drawCoverage = function () {
      CX.charts.barsH(coverageCard.clear(), coverageRows, {
        color: CX.token("--chart-series-a"),
        domainMax: 1,
        maxLabelWidth: 200,
        ariaLabel: "Domain coverage by conservation class",
        tooltip: function (d) {
          return {
            title: d.label,
            rows: [["Genes", CX.fmt.int(d.genes)], ["With a domain", CX.fmt.int(d.with_domain)], ["Share", CX.fmt.pct(d.value)]],
          };
        },
      });
    };
    drawCoverage();
    coverageCard.setTable(
      [
        { label: "Conservation class", key: "label" },
        { label: "Genes", key: "genes", numeric: true, format: CX.fmt.int },
        { label: "With a domain", key: "with_domain", numeric: true, format: CX.fmt.int },
        { label: "Share", key: "value", numeric: true, format: CX.fmt.pct },
      ],
      coverageRows
    );
    redraws.push(drawCoverage);
    return redraws;
  }

  // ---- Wiring --------------------------------------------------------------

  /** Bind navigation selects, toggles, tabs and filters. */
  function bindControls() {
    document.getElementById("switch-species").addEventListener("change", function (event) {
      if (event.target.value) {
        window.location.href = CX.link.species(event.target.value);
      }
    });
    const compareWith = document.getElementById("compare-with");
    Array.from(compareWith.options).forEach(function (option) {
      option.disabled = option.value === species.name;
    });
    compareWith.addEventListener("change", function (event) {
      if (event.target.value) {
        window.location.href = CX.link.compare(species.name, event.target.value);
      }
    });
    CX.bindChoice(document.getElementById("unit-toggle"), function (value) {
      state.unit = value;
      renderBreadth();
      renderStrata();
      renderCopy();
    });
    document.getElementById("context-metric").addEventListener("change", renderContext);
    CX.bindChoice(document.getElementById("notable-tabs"), function (value) {
      state.category = value;
      renderStrata();
      loadNotable();
    }, "aria-selected");
    document.getElementById("min-other").addEventListener("change", loadNotable);
  }

  /** Load data and render the page. */
  async function init() {
    bindControls();
    const chartIds = ["chart-breadth", "chart-strata", "chart-copy", "chart-shared", "chart-context"];
    try {
      const results = await Promise.all([
        CX.fetchJson(CX.link.api(CX.urls.apiSpeciesOverview, species.name)),
        CX.speciesColors(),
      ]);
      state.overview = results[0];
      state.colors = results[1];
    } catch (error) {
      chartIds.forEach(function (id) { CX.card(id).status(error.message); });
      return;
    }

    renderTiles();
    // Draw (or redraw after a resize) every chart fed by the overview payload.
    const drawOverview = function () {
      renderBreadth();
      renderStrata();
      renderCopy();
      renderShared();
      renderContext();
    };
    drawOverview();
    CX.onResize(drawOverview);

    CX.referencePicker(
      document.getElementById("reference-picker"),
      state.overview.all_species.filter(function (entry) { return entry.name !== species.name; }),
      function (excluded) {
        state.exclude = excluded;
        loadNotable();
      }
    );
    loadNotable();

    // Annotation statistics can be slow on first load, so fetch them last.
    try {
      const annotations = await CX.fetchJson(CX.link.api(CX.urls.apiSpeciesAnnotations, species.name));
      const redraws = [renderLengths(annotations.proteins)]
        .concat(renderTranscripts(annotations.transcripts))
        .concat(renderDomains(annotations.domains))
        .filter(Boolean);
      CX.onResize(function () { redraws.forEach(function (redraw) { redraw(); }); });
    } catch (error) {
      ["chart-length", "chart-isoforms", "chart-exons", "chart-domains", "chart-domain-coverage"].forEach(function (id) {
        const card = CX.card(id);
        if (card) {
          card.status(error.message);
        }
      });
    }
  }

  init();
})();
