/**
 * Species Comparison page: gene-family expansions and contractions between
 * two species, polarised against the other species in the dataset.
 *
 * Reads CX.page ({ a, b, selected }) set by the template.  All per-family
 * classification happens in the browser so the thresholds respond instantly.
 */
(function () {
  "use strict";

  const page = CX.page;

  /** Copy-number bins shared by the landscape heatmap: [low, high, label]. */
  const BINS = [
    [0, 0, "0"], [1, 1, "1"], [2, 2, "2"], [3, 3, "3"], [4, 4, "4"], [5, 5, "5"],
    [6, 10, "6-10"], [11, 20, "11-20"], [21, 50, "21-50"], [51, Infinity, ">50"],
  ];

  /** Fold change (and absolute change) needed to call a shift from the reference. */
  const POLARITY_FOLD = 1.5;

  /** Largest number of rows handed to the family table. */
  const MAX_TABLE_ROWS = 500;

  const state = {
    data: null,
    families: [],
    minFold: 1,          // log2 units
    minDiff: 2,
    exclude: [],
    tab: "higher_a",
    selection: [],
    domains: null,
  };

  // ---- Species pickers (always active) -------------------------------------

  /** Keep the two pickers from selecting the same species; wire the swap. */
  function bindPickers() {
    const a = document.getElementById("pick-a");
    const b = document.getElementById("pick-b");
    // Disable, in each picker, the species currently chosen in the other.
    const sync = function () {
      Array.from(b.options).forEach(function (option) {
        option.disabled = Boolean(option.value) && option.value === a.value;
      });
      Array.from(a.options).forEach(function (option) {
        option.disabled = Boolean(option.value) && option.value === b.value;
      });
    };
    a.addEventListener("change", sync);
    b.addEventListener("change", sync);
    sync();
    const swap = document.getElementById("swap-species");
    if (swap) {
      swap.addEventListener("click", function () {
        const previous = a.value;
        // Clear first so neither option is disabled while values cross over.
        Array.from(a.options).concat(Array.from(b.options)).forEach(function (option) {
          option.disabled = false;
        });
        a.value = b.value;
        b.value = previous;
        sync();
        if (a.value && b.value) {
          a.form.submit();
        }
      });
    }
  }

  // ---- Classification ------------------------------------------------------

  /**
   * Index of the copy-number bin containing a value.
   * @param {number} value - Gene copies.
   * @returns {number}
   */
  function binIndex(value) {
    for (let i = 0; i < BINS.length; i += 1) {
      if (value >= BINS[i][0] && value <= BINS[i][1]) {
        return i;
      }
    }
    return BINS.length - 1;
  }

  /**
   * Classify a pair of copy numbers under the current thresholds.
   *
   * @param {number} a - Copies in species A.
   * @param {number} b - Copies in species B.
   * @returns {string} only_a, only_b, higher_a, higher_b or similar.
   */
  function classify(a, b) {
    if (a > 0 && b === 0) {
      return "only_a";
    }
    if (b > 0 && a === 0) {
      return "only_b";
    }
    return thresholdClass(a, b);
  }

  /**
   * Classify by the thresholds alone, with no special case for absence.
   *
   * Used for domain families, where one gene against none is not a notable
   * difference in the way a species-restricted orthogroup is.
   *
   * @param {number} a - Count in species A.
   * @param {number} b - Count in species B.
   * @returns {string} higher_a, higher_b or similar.
   */
  function thresholdClass(a, b) {
    const ratio = Math.log2((a + 1) / (b + 1));
    if (ratio >= state.minFold && a - b >= state.minDiff) {
      return "higher_a";
    }
    if (-ratio >= state.minFold && b - a >= state.minDiff) {
      return "higher_b";
    }
    return "similar";
  }

  /**
   * Direction of one species' copy number relative to the reference median.
   *
   * @param {number} copies - Copies in the species.
   * @param {number} reference - Reference median.
   * @returns {number} 1 above, -1 below, 0 about the same.
   */
  function shift(copies, reference) {
    if (copies - reference >= 1 && (copies + 1) / (reference + 1) >= POLARITY_FOLD) {
      return 1;
    }
    if (reference - copies >= 1 && (reference + 1) / (copies + 1) >= POLARITY_FOLD) {
      return -1;
    }
    return 0;
  }

  /**
   * Suggest which lineage changed for a family that differs between A and B.
   *
   * @param {Object} family - Family record with a, b, ref, refPresent, cls.
   * @returns {string} Short description for the "Likely change" column.
   */
  function likelyChange(family) {
    if (family.cls === "similar") {
      return "—";
    }
    if (!family.refPresent) {
      return "No reference (absent elsewhere)";
    }
    const a = state.data.a.short_label;
    const b = state.data.b.short_label;
    const aShift = shift(family.a, family.ref);
    const bShift = shift(family.b, family.ref);
    const parts = [];
    if (aShift > 0) { parts.push("gain in " + a); }
    if (aShift < 0) { parts.push("loss in " + a); }
    if (bShift > 0) { parts.push("gain in " + b); }
    if (bShift < 0) { parts.push("loss in " + b); }
    if (!parts.length) {
      return "Unclear";
    }
    const text = parts.join(", ");
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  /** Rebuild per-family records from the API payload and thresholds. */
  function deriveFamilies() {
    const og = state.data.orthogroups;
    state.families = og.ids.map(function (id, i) {
      const family = {
        orthogroup_id: id, a: og.a[i], b: og.b[i], ref: og.ref[i], refPresent: og.ref_present[i],
        ratio: Math.log2((og.a[i] + 1) / (og.b[i] + 1)),
      };
      family.cls = classify(family.a, family.b);
      family.change = likelyChange(family);
      return family;
    });
  }

  /**
   * Chart color for a classification.
   * @param {string} cls - Result of classify().
   * @returns {string} CSS color.
   */
  function classColor(cls) {
    if (cls === "higher_a" || cls === "only_a") {
      return CX.token("--chart-series-a");
    }
    if (cls === "higher_b" || cls === "only_b") {
      return CX.token("--chart-series-b");
    }
    return CX.token("--chart-neutral");
  }

  /** Legend entries naming the two species and the neutral class. */
  function classLegend() {
    return [
      { label: "Larger in " + state.data.a.short_label, color: CX.token("--chart-series-a") },
      { label: "Larger in " + state.data.b.short_label, color: CX.token("--chart-series-b") },
      { label: "Similar", color: CX.token("--chart-neutral") },
    ];
  }

  // ---- Tiles -----------------------------------------------------------------

  /**
   * Replace the text of a stat tile label, keeping its color key.
   * @param {string} id - Tile id.
   * @param {string} text - New label text.
   */
  function setTileLabel(id, text) {
    const label = document.querySelector("#" + id + " .stat-label");
    if (label) {
      label.lastChild.textContent = text;
    }
  }

  /** Fill the summary tiles. */
  function renderTiles() {
    const data = state.data;
    const summary = data.summary;
    const classes = summary.classes;
    // Number of families in one class under the current thresholds.
    const count = function (cls) {
      return state.families.filter(function (f) { return f.cls === cls; }).length;
    };
    const fold = Math.pow(2, state.minFold);
    const rule = "≥ " + (Math.round(fold * 10) / 10) + "× and ≥ " + state.minDiff +
      (state.minDiff === 1 ? " gene" : " genes");
    CX.setStat("stat-shared", CX.fmt.int(summary.shared),
      "of " + CX.fmt.int(summary.union) + " families in either species");
    CX.setStat("stat-one-to-one", CX.fmt.int(classes.one_to_one.orthogroups),
      summary.shared ? CX.fmt.pct0(classes.one_to_one.orthogroups / summary.shared) + " of shared families" : "");
    setTileLabel("stat-higher-a", "Larger in " + data.a.short_label);
    setTileLabel("stat-higher-b", "Larger in " + data.b.short_label);
    setTileLabel("stat-only-a", "Only in " + data.a.short_label);
    setTileLabel("stat-only-b", "Only in " + data.b.short_label);
    CX.setStat("stat-higher-a", CX.fmt.int(count("higher_a")), "Shared families, " + rule);
    CX.setStat("stat-higher-b", CX.fmt.int(count("higher_b")), "Shared families, " + rule);
    CX.setStat("stat-only-a", CX.fmt.int(classes.a_only.orthogroups), CX.fmt.int(classes.a_only.genes_a) + " genes");
    CX.setStat("stat-only-b", CX.fmt.int(classes.b_only.orthogroups), CX.fmt.int(classes.b_only.genes_b) + " genes");
  }

  // ---- Charts ----------------------------------------------------------------

  /** Heatmap of orthogroup counts by binned copy number in A and B. */
  function renderLandscape() {
    const card = CX.card("chart-landscape");
    const data = state.data;
    const groups = new Map();
    state.families.forEach(function (family) {
      const key = binIndex(family.a) + "|" + binIndex(family.b);
      if (!groups.has(key)) {
        groups.set(key, []);
      }
      groups.get(key).push(family);
    });
    const maxCount = d3.max(Array.from(groups.values()), function (g) { return g.length; }) || 1;
    const ramps = {
      a: CX.charts.ramp("--chart-seq-a"),
      b: CX.charts.ramp("--chart-seq-b"),
      equal: CX.charts.ramp("--chart-seq-neutral"),
    };
    // Log scaling keeps single-family cells visible next to the 1:1 cell.
    const intensity = function (count) { return 0.08 + 0.92 * Math.log(count + 1) / Math.log(maxCount + 1); };
    const cells = [];
    groups.forEach(function (members, key) {
      const parts = key.split("|").map(Number);
      const side = parts[0] > parts[1] ? "a" : parts[1] > parts[0] ? "b" : "equal";
      cells.push({
        // Row 0 is the top of the grid, so the largest B bin goes first.
        r: BINS.length - 1 - parts[1], c: parts[0], aBin: parts[0], bBin: parts[1],
        members: members, fill: ramps[side](intensity(members.length)), text: CX.fmt.int(members.length),
      });
    });
    card.subtitle("Orthogroups by copies in each species. Click a cell to list its families.");
    const host = card.clear();
    host.appendChild(CX.legend([
      { label: "Larger in " + data.a.short_label, ramp: [ramps.a(0.1), ramps.a(1)] },
      { label: "Same bin", ramp: [ramps.equal(0.1), ramps.equal(1)] },
      { label: "Larger in " + data.b.short_label + " (darker = more families)", ramp: [ramps.b(0.1), ramps.b(1)] },
    ]));
    CX.charts.heatmap(host.appendChild(CX.el("section")), {
      rows: BINS.map(function (bin) { return bin[2]; }).reverse(),
      cols: BINS.map(function (bin) { return bin[2]; }),
      cells: cells,
      rowTitle: "Copies in " + data.b.short_label,
      colTitle: "Copies in " + data.a.short_label,
      maxCell: 42,
      ariaLabel: "Orthogroups by copy number in the two species",
      onClick: function (cell) {
        select(cell.members, data.a.short_label + " " + BINS[cell.aBin][2] + " / " +
          data.b.short_label + " " + BINS[cell.bBin][2]);
      },
      tooltip: function (cell) {
        return {
          title: CX.fmt.count(cell.members.length, "family", "families"),
          rows: [
            [data.a.short_label, BINS[cell.aBin][2] + " copies"],
            [data.b.short_label, BINS[cell.bBin][2] + " copies"],
          ],
        };
      },
    });
    card.setTable(
      [
        { label: "Copies in " + data.a.short_label, key: "aLabel" },
        { label: "Copies in " + data.b.short_label, key: "bLabel" },
        { label: "Orthogroups", key: "count", numeric: true, format: CX.fmt.int },
      ],
      cells.map(function (cell) {
        return { aLabel: BINS[cell.aBin][2], bLabel: BINS[cell.bBin][2], count: cell.members.length };
      }).sort(function (x, y) { return y.count - x.count; })
    );
  }

  /** Bubble plot of copy number in A and B relative to the reference median. */
  function renderPolarity() {
    const card = CX.card("chart-polarity");
    const data = state.data;
    const groups = new Map();
    let withoutReference = 0;
    state.families.forEach(function (family) {
      if (!family.refPresent) {
        withoutReference += 1;
        return;
      }
      const key = family.a + "|" + family.b + "|" + family.ref;
      if (!groups.has(key)) {
        groups.set(key, {
          a: family.a, b: family.b, ref: family.ref, members: [],
          x: Math.log2((family.a + 1) / (family.ref + 1)),
          y: Math.log2((family.b + 1) / (family.ref + 1)),
          color: classColor(family.cls),
        });
      }
      groups.get(key).members.push(family);
    });
    const points = Array.from(groups.values());
    points.forEach(function (point) { point.size = point.members.length; });
    if (!points.length) {
      card.subtitle("");
      card.status("No family in this pair is found in any reference species, so there is nothing to polarise against.");
      return;
    }
    card.subtitle(
      CX.fmt.int(state.families.length - withoutReference) + " families with a reference; " +
      CX.fmt.int(withoutReference) + " absent from every reference species are not drawn. " +
      "Bubble area shows the number of families."
    );
    const limit = (d3.max(points, function (p) { return Math.max(Math.abs(p.x), Math.abs(p.y)); }) || 1) + 0.4;
    const host = card.clear();
    host.appendChild(CX.legend(classLegend()));
    CX.charts.scatter(host.appendChild(CX.el("section")), points, {
      xDomain: [-limit, limit],
      yDomain: [-limit, limit],
      xLabel: data.a.short_label + " vs reference median (log2 copy ratio)",
      yLabel: data.b.short_label + " vs reference median (log2)",
      diagonal: true,
      zeroLines: true,
      corners: {
        tr: "more copies in both",
        bl: "fewer copies in both",
        br: "more in " + data.a.short_label,
        tl: "more in " + data.b.short_label,
      },
      ariaLabel: "Copy number relative to the reference in each species",
      onClick: function (point) {
        select(point.members, data.a.short_label + " " + point.a + " / " + data.b.short_label + " " +
          point.b + " / reference " + point.ref);
      },
      tooltip: function (point) {
        return {
          title: CX.fmt.count(point.size, "family", "families"),
          rows: [
            [data.a.short_label, CX.fmt.count(point.a, "copy", "copies")],
            [data.b.short_label, CX.fmt.count(point.b, "copy", "copies")],
            ["Reference median", String(point.ref)],
          ],
          note: point.size === 1 ? point.members[0].orthogroup_id : "",
        };
      },
    });
    card.setTable(
      [
        { label: "Copies in " + data.a.short_label, key: "a", numeric: true },
        { label: "Copies in " + data.b.short_label, key: "b", numeric: true },
        { label: "Reference median", key: "ref", numeric: true },
        { label: "Orthogroups", key: "size", numeric: true, format: CX.fmt.int },
      ],
      points.slice().sort(function (p, q) { return q.size - p.size; }).slice(0, 300)
    );
  }

  /** Histogram of the A/B log2 copy ratio for shared, unequal families. */
  function renderRatio() {
    const card = CX.card("chart-ratio");
    const data = state.data;
    const shared = state.families.filter(function (f) { return f.a > 0 && f.b > 0; });
    const unequal = shared.filter(function (f) { return f.a !== f.b; });
    if (!unequal.length) {
      card.subtitle("");
      card.status("Every shared family has the same copy number in both species.");
      return;
    }
    const width = 0.5;
    const counts = new Map();
    unequal.forEach(function (family) {
      const k = Math.round(family.ratio / width);
      counts.set(k, (counts.get(k) || 0) + 1);
    });
    const extent = d3.max(Array.from(counts.keys()), Math.abs);
    const a = CX.token("--chart-series-a");
    const b = CX.token("--chart-series-b");
    const neutral = CX.token("--chart-neutral");
    const bins = d3.range(-extent, extent + 1).map(function (k) {
      return {
        x0: k * width - width / 2, x1: k * width + width / 2, count: counts.get(k) || 0,
        color: k > 0 ? a : k < 0 ? b : neutral,
      };
    });
    card.subtitle(
      CX.fmt.int(unequal.length) + " shared families with unequal copy number; " +
      CX.fmt.int(shared.length - unequal.length) + " with equal copy number are not drawn."
    );
    const host = card.clear();
    host.appendChild(CX.legend([
      { label: "More copies in " + data.a.short_label, color: a },
      { label: "More copies in " + data.b.short_label, color: b },
    ]));
    const foldLabel = (Math.round(Math.pow(2, state.minFold) * 10) / 10) + "×";
    CX.charts.histogram(host.appendChild(CX.el("section")), bins, {
      xLabel: "log2 copy ratio, " + data.a.short_label + " / " + data.b.short_label,
      yLabel: "Orthogroups",
      tickFormat: d3.format("+~g"),
      markers: [{ x: state.minFold, label: foldLabel }, { x: -state.minFold, label: foldLabel }],
      ariaLabel: "Distribution of copy-number ratio",
    });
    card.setTable(
      [
        { label: "log2 ratio from", key: "x0", numeric: true, format: d3.format("+.2f") },
        { label: "to", key: "x1", numeric: true, format: d3.format("+.2f") },
        { label: "Orthogroups", key: "count", numeric: true, format: CX.fmt.int },
      ],
      bins
    );
  }

  /** Ranked bars of orthology relationship classes. */
  function renderClasses() {
    const card = CX.card("chart-classes");
    const data = state.data;
    const classes = data.summary.classes;
    const a = CX.token("--chart-series-a");
    const b = CX.token("--chart-series-b");
    const neutral = CX.token("--chart-neutral-strong");
    const rows = [
      ["one_to_one", "1 : 1", neutral],
      ["one_to_many", "1 : many (more in " + data.b.short_label + ")", b],
      ["many_to_one", "many : 1 (more in " + data.a.short_label + ")", a],
      ["many_to_many", "many : many", neutral],
      ["a_only", "Only in " + data.a.short_label, a],
      ["b_only", "Only in " + data.b.short_label, b],
    ].map(function (entry) {
      const record = classes[entry[0]];
      return {
        label: entry[1], color: entry[2], value: record.orthogroups,
        genes_a: record.genes_a, genes_b: record.genes_b,
      };
    });
    CX.charts.barsH(card.clear(), rows, {
      maxLabelWidth: 230,
      ariaLabel: "Orthology relationship classes",
      tooltip: function (d) {
        return {
          title: d.label,
          rows: [
            ["Orthogroups", CX.fmt.int(d.value)],
            ["Genes in " + data.a.short_label, CX.fmt.int(d.genes_a)],
            ["Genes in " + data.b.short_label, CX.fmt.int(d.genes_b)],
          ],
        };
      },
    });
    card.setTable(
      [
        { label: "Relationship (A : B)", key: "label" },
        { label: "Orthogroups", key: "value", numeric: true, format: CX.fmt.int },
        { label: "Genes in " + data.a.short_label, key: "genes_a", numeric: true, format: CX.fmt.int },
        { label: "Genes in " + data.b.short_label, key: "genes_b", numeric: true, format: CX.fmt.int },
      ],
      rows
    );
  }

  // ---- Family table ------------------------------------------------------------

  let familyTable = null;

  /** Families for the active tab, ranked for display. */
  function rowsForTab() {
    // Comparator: by signed log2 ratio, then by total copies.
    const byRatio = function (sign) {
      return function (x, y) { return sign * (y.ratio - x.ratio) || (y.a + y.b) - (x.a + x.b); };
    };
    // Families belonging to one class.
    const ofClass = function (cls) {
      return state.families.filter(function (f) { return f.cls === cls; });
    };
    switch (state.tab) {
      case "higher_a": return ofClass("higher_a").sort(byRatio(1));
      case "higher_b": return ofClass("higher_b").sort(byRatio(-1));
      case "only_a": return ofClass("only_a").sort(function (x, y) { return y.a - x.a; });
      case "only_b": return ofClass("only_b").sort(function (x, y) { return y.b - x.b; });
      default:
        return state.selection.slice().sort(function (x, y) {
          return Math.abs(y.ratio) - Math.abs(x.ratio) || (y.a + y.b) - (x.a + x.b);
        });
    }
  }

  /** Refresh tab labels (with counts) and the family table. */
  function renderFamilies() {
    const data = state.data;
    // Number of families in one class, for the tab labels.
    const count = function (cls) {
      return state.families.filter(function (f) { return f.cls === cls; }).length;
    };
    const labels = {
      higher_a: "Larger in " + data.a.short_label + " (" + CX.fmt.int(count("higher_a")) + ")",
      higher_b: "Larger in " + data.b.short_label + " (" + CX.fmt.int(count("higher_b")) + ")",
      only_a: "Only in " + data.a.short_label + " (" + CX.fmt.int(count("only_a")) + ")",
      only_b: "Only in " + data.b.short_label + " (" + CX.fmt.int(count("only_b")) + ")",
    };
    document.querySelectorAll("#family-tabs button").forEach(function (button) {
      if (labels[button.dataset.value]) {
        button.textContent = labels[button.dataset.value];
      }
      button.setAttribute("aria-selected", String(button.dataset.value === state.tab));
    });
    if (!familyTable) {
      familyTable = CX.OrthogroupTable(document.getElementById("family-table"), {
        columns: [
          { key: "a", label: data.a.short_label, numeric: true, format: CX.fmt.int, className: "species-name",
            title: "Gene copies in " + data.a.label },
          { key: "b", label: data.b.short_label, numeric: true, format: CX.fmt.int, className: "species-name",
            title: "Gene copies in " + data.b.label },
          { key: "ratio", label: "log2 ratio", numeric: true, format: CX.fmt.signed, title: "log2((A + 1) / (B + 1))" },
          { key: "ref", label: "Ref. median", numeric: true, format: CX.fmt.fixed1,
            title: "Median copies among reference species that carry the family" },
          { key: "refPresent", label: "In ref. spp.", numeric: true,
            format: function (value) { return value + " / " + state.data.n_reference; },
            title: "Reference species that carry the family" },
          { key: "change", label: "Likely change", title: "Suggested from the reference median" },
        ],
        emptyMessage: "No families in this list with the current thresholds.",
        onSelect: function (row) {
          const highlight = {};
          highlight[data.a.name] = CX.token("--chart-series-a");
          highlight[data.b.name] = CX.token("--chart-series-b");
          CX.orthogroupProfile("chart-profile", row.orthogroup_id, { highlight: highlight });
        },
      });
    }
    const rows = rowsForTab();
    familyTable.setRows(
      rows.slice(0, MAX_TABLE_ROWS),
      CX.fmt.int(rows.length) + " families in this list"
    );
  }

  /**
   * Show a chart selection in the family table.
   *
   * @param {Array<Object>} families - Family records picked in a chart.
   * @param {string} label - Description of the selection for the tab.
   */
  function select(families, label) {
    state.selection = families;
    state.tab = "selection";
    const tab = document.querySelector('#family-tabs button[data-value="selection"]');
    tab.hidden = false;
    tab.textContent = "Selection: " + label + " (" + CX.fmt.int(families.length) + ")";
    renderFamilies();
    document.getElementById("families").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---- Domain comparison -------------------------------------------------------

  /** Scatter and table comparing domain-family sizes in the two species. */
  function renderDomains() {
    const result = state.domains;
    const scatterCard = CX.card("chart-domain-scatter");
    const tableCard = CX.card("chart-domain-table");
    if (!scatterCard || !result) {
      return;
    }
    const data = state.data;
    const rows = result.rows.map(function (row) {
      return Object.assign({ ratio: Math.log2((row.a + 1) / (row.b + 1)), cls: thresholdClass(row.a, row.b) }, row, {
        text: row.description || row.name || row.accession,
      });
    });
    const groups = new Map();
    rows.forEach(function (row) {
      const key = row.a + "|" + row.b;
      if (!groups.has(key)) {
        groups.set(key, {
          a: row.a, b: row.b, x: Math.log2(row.a + 1), y: Math.log2(row.b + 1),
          color: classColor(row.cls), members: [],
        });
      }
      groups.get(key).members.push(row);
    });
    const points = Array.from(groups.values());
    points.forEach(function (point) { point.size = point.members.length; });
    const maxCount = d3.max(rows, function (row) { return Math.max(row.a, row.b); }) || 1;
    const tickCounts = [0, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000].filter(function (v) { return v <= maxCount * 1.5; });
    const ticks = {
      values: tickCounts.map(function (v) { return Math.log2(v + 1); }),
      format: function (v) { return CX.fmt.int(Math.round(Math.pow(2, v) - 1)); },
    };
    const limit = Math.log2(maxCount + 1) * 1.06 + 0.3;
    scatterCard.subtitle(
      CX.fmt.int(rows.length) + " " + result.database + " families; gene counts on a log scale."
    );
    const host = scatterCard.clear();
    host.appendChild(CX.legend(classLegend()));
    CX.charts.scatter(host.appendChild(CX.el("section")), points, {
      xDomain: [-0.3, limit],
      yDomain: [-0.3, limit],
      xTicks: ticks,
      yTicks: ticks,
      xLabel: "Genes with the domain in " + data.a.short_label,
      yLabel: "Genes in " + data.b.short_label,
      diagonal: true,
      radius: [4, 13],
      ariaLabel: "Domain family size in the two species",
      tooltip: function (point) {
        const names = point.members.slice(0, 3).map(function (m) { return m.text; });
        return {
          title: point.size === 1 ? point.members[0].text : CX.fmt.int(point.size) + " domain families",
          rows: [
            [data.a.short_label, CX.fmt.count(point.a, "gene", "genes")],
            [data.b.short_label, CX.fmt.count(point.b, "gene", "genes")],
          ],
          note: point.size === 1 ? point.members[0].accession
            : names.join("; ") + (point.size > 3 ? "; …" : ""),
        };
      },
    });
    scatterCard.setTable(
      [
        { label: "Accession", key: "accession" },
        { label: "Description", key: "text" },
        { label: data.a.short_label, key: "a", numeric: true, format: CX.fmt.int },
        { label: data.b.short_label, key: "b", numeric: true, format: CX.fmt.int },
      ],
      rows.slice(0, 500)
    );

    const different = rows
      .filter(function (row) { return row.cls !== "similar"; })
      .sort(function (x, y) { return Math.abs(y.ratio) - Math.abs(x.ratio) || (y.a + y.b) - (x.a + x.b); });
    tableCard.subtitle(
      CX.fmt.int(different.length) + " " + result.database + " families pass the thresholds above, ranked by fold difference."
    );
    CX.dataTable(tableCard.clear(), [
      {
        key: "text", label: "Domain",
        render: function (row) {
          const node = CX.el("span", { text: row.text, title: row.accession });
          return node;
        },
      },
      { key: "a", label: data.a.short_label, numeric: true, format: CX.fmt.int, className: "species-name" },
      { key: "b", label: data.b.short_label, numeric: true, format: CX.fmt.int, className: "species-name" },
      { key: "ratio", label: "log2 ratio", numeric: true, format: CX.fmt.signed },
    ], different, { pageSize: 12, emptyMessage: "No domain family passes the thresholds." });
  }

  /**
   * Load the domain comparison for a database (or the default one).
   * @param {string} [database] - Domain database name.
   */
  async function loadDomains(database) {
    const scatterCard = CX.card("chart-domain-scatter");
    try {
      state.domains = await CX.fetchJson(CX.url(CX.urls.apiCompareDomains, {
        a: page.a.name, b: page.b.name, db: database,
      }));
    } catch (error) {
      scatterCard.status(error.message);
      return;
    }
    if (!state.domains.database) {
      document.getElementById("domain-section").replaceChildren(
        CX.el("p", {
          class: "chart-status",
          text: "Protein-domain annotations (InterProScan or Pfam) are not loaded for both species.",
        })
      );
      state.domains = null;
      return;
    }
    const select = document.getElementById("domain-database");
    if (!select.options.length) {
      state.domains.databases.forEach(function (name) {
        select.appendChild(CX.el("option", { value: name, text: name, selected: name === state.domains.database }));
      });
      select.addEventListener("change", function () { loadDomains(select.value); });
      document.getElementById("domain-controls").hidden = false;
    }
    renderDomains();
  }

  // ---- Wiring --------------------------------------------------------------------

  /** Re-render everything that depends on thresholds or the payload. */
  function renderAll() {
    deriveFamilies();
    renderTiles();
    renderLandscape();
    renderPolarity();
    renderRatio();
    renderClasses();
    renderFamilies();
    renderDomains();
  }

  /** Fetch the comparison (honouring reference exclusions) and render. */
  async function loadComparison() {
    const ids = ["chart-landscape", "chart-polarity", "chart-ratio", "chart-classes"];
    ids.forEach(function (id) { CX.card(id).body.style.opacity = 0.5; });
    try {
      state.data = await CX.fetchJson(CX.url(CX.urls.apiCompare, {
        a: page.a.name, b: page.b.name, exclude: state.exclude.join(","),
      }));
    } catch (error) {
      ids.forEach(function (id) {
        CX.card(id).body.style.opacity = 1;
        CX.card(id).status(error.message);
      });
      return false;
    }
    ids.forEach(function (id) { CX.card(id).body.style.opacity = 1; });
    state.selection = [];
    if (state.tab === "selection") {
      state.tab = "higher_a";
    }
    document.querySelector('#family-tabs button[data-value="selection"]').hidden = true;
    renderAll();
    return true;
  }

  /** Initialise the page. */
  async function init() {
    bindPickers();
    if (!page.selected) {
      return;
    }
    document.getElementById("min-fold").addEventListener("change", function (event) {
      state.minFold = parseFloat(event.target.value);
      renderAll();
    });
    document.getElementById("min-diff").addEventListener("change", function (event) {
      state.minDiff = parseInt(event.target.value, 10);
      renderAll();
    });
    CX.bindChoice(document.getElementById("family-tabs"), function (value) {
      state.tab = value;
      renderFamilies();
    }, "aria-selected");

    if (!(await loadComparison())) {
      return;
    }
    CX.onResize(function () {
      renderLandscape();
      renderPolarity();
      renderRatio();
      renderClasses();
      renderDomains();
    });

    // The reference picker lists every species other than the two compared.
    try {
      const all = await CX.fetchJson(CX.urls.apiSpecies);
      CX.referencePicker(
        document.getElementById("reference-picker"),
        all.species.filter(function (s) { return s.name !== page.a.name && s.name !== page.b.name; }),
        function (excluded) {
          state.exclude = excluded;
          loadComparison();
        }
      );
    } catch (error) {
      // The picker is optional; the comparison still works without it.
    }
    loadDomains();
  }

  init();
})();
