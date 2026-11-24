/**
 * Orthogroup tables and the copy-number profile panel (namespace: window.CX).
 *
 * Shared by the Species and Species Comparison pages: both list orthogroups
 * in a sortable table, lazily attach a representative domain annotation to
 * the visible rows, and show the selected family's copy number in every
 * species next to the table.
 */
(function (global) {
  "use strict";

  const CX = global.CX;
  const annotationCache = new Map();

  /**
   * Fetch representative annotations for orthogroups not yet cached.
   *
   * @param {Array<string>} ids - Orthogroup identifiers.
   * @returns {Promise<void>} Resolves once the cache holds every id.
   */
  async function loadAnnotations(ids) {
    const missing = ids.filter(function (id) { return !annotationCache.has(id); });
    if (!missing.length) {
      return;
    }
    let result = {};
    try {
      result = await CX.fetchJson(CX.urls.orthogroupAnnotations, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: missing }),
      });
    } catch (error) {
      result = {};
    }
    missing.forEach(function (id) {
      annotationCache.set(id, result[id] || null);
    });
  }

  /**
   * Write an annotation into its line under the orthogroup id.
   *
   * @param {HTMLElement} cell - Target element.
   * @param {Object|null} info - { description, labels: [{ label, database,
   *   accession, genes }] } or null when nothing is known.
   */
  function fillAnnotation(cell, info) {
    cell.replaceChildren();
    if (!info || (!info.description && !(info.labels || []).length)) {
      cell.textContent = "No annotation";
      return;
    }
    const labels = info.labels || [];
    const primary = info.description || labels[0].label;
    cell.appendChild(document.createTextNode(primary));
    const extra = info.description ? labels.length : labels.length - 1;
    if (extra > 0) {
      cell.appendChild(document.createTextNode(" (+" + extra + ")"));
    }
    cell.title = labels
      .map(function (l) { return l.label + " [" + l.database + " " + l.accession + "]"; })
      .join("; ");
  }

  /**
   * Sortable, incrementally revealed orthogroup table.
   *
   * @param {HTMLElement} host - Element that will contain the table.
   * @param {Object} config - columns: Array<{ key, label, numeric, format,
   *   title, className }> (an orthogroup column is prepended automatically;
   *   it shows the id and, on a second line, a representative annotation);
   *   onSelect(row): called when a row is chosen; pageSize: rows revealed
   *   per step; emptyMessage.
   * @returns {Object} Controller with setRows(rows, note): replace the rows
   *   (note is shown in the footer) and select the first one.
   */
  CX.OrthogroupTable = function (host, config) {
    const pageSize = config.pageSize || 12;
    let rows = [];
    let visible = pageSize;
    let sortKey = null;
    let sortDirection = -1;
    let selectedId = null;
    let footerNote = "";

    /** Sort the current rows in place by the active column. */
    function applySort() {
      if (!sortKey) {
        return;
      }
      rows.sort(function (a, b) {
        const av = a[sortKey];
        const bv = b[sortKey];
        if (av === bv) {
          return 0;
        }
        return (av > bv ? 1 : -1) * sortDirection;
      });
    }

    /** Mark a row as selected and notify the page. */
    function select(row, tableRow) {
      selectedId = row.orthogroup_id;
      host.querySelectorAll("tbody tr").forEach(function (node) {
        node.classList.toggle("is-selected", node === tableRow);
      });
      if (config.onSelect) {
        config.onSelect(row);
      }
    }

    /** Rebuild the table for the current rows, sort order and page. */
    function render() {
      if (!rows.length) {
        host.replaceChildren(
          CX.el("p", { class: "chart-status", text: config.emptyMessage || "No orthogroups match." })
        );
        return;
      }
      const headCells = [CX.el("th", { text: "Orthogroup" })];
      config.columns.forEach(function (column) {
        const th = CX.el("th", {
          text: column.label,
          class: [column.numeric ? "numeric" : "", column.className || ""].join(" ").trim() || null,
          title: column.title || null,
          "data-sort": column.key,
          "aria-sort": sortKey === column.key ? (sortDirection > 0 ? "ascending" : "descending") : null,
          tabindex: 0,
        });
        // Sort by this column (largest first); a second activation reverses it.
        const sort = function () {
          sortDirection = sortKey === column.key ? -sortDirection : -1;
          sortKey = column.key;
          applySort();
          render();
        };
        th.addEventListener("click", sort);
        th.addEventListener("keydown", function (event) {
          if (event.key === "Enter") {
            sort();
          }
        });
        headCells.push(th);
      });

      const shown = rows.slice(0, visible);
      const annotationCells = new Map();
      const bodyRows = shown.map(function (row) {
        const link = CX.el("a", {
          href: CX.urls.orthogroup + encodeURIComponent(row.orthogroup_id),
          text: row.orthogroup_id,
        });
        // Following the link should not also change the selection.
        link.addEventListener("click", function (event) { event.stopPropagation(); });
        // The annotation shares the first cell so the table stays narrow.
        const annotationCell = CX.el("span", { class: "annotation-line", text: "…" });
        annotationCells.set(row.orthogroup_id, annotationCell);
        const cells = [CX.el("td", { class: "orthogroup-cell" }, [link, annotationCell])];
        config.columns.forEach(function (column) {
          const raw = row[column.key];
          cells.push(CX.el("td", {
            class: column.numeric ? "numeric" : null,
            text: raw === null || raw === undefined ? "—" : column.format ? column.format(raw, row) : raw,
          }));
        });
        const tr = CX.el("tr", {
          class: row.orthogroup_id === selectedId ? "is-selected" : null,
          tabindex: 0,
        }, cells);
        tr.addEventListener("click", function () { select(row, tr); });
        tr.addEventListener("keydown", function (event) {
          if (event.key === "Enter") {
            select(row, tr);
          }
        });
        return tr;
      });

      const footer = CX.el("footer", { class: "table-footer" }, [
        CX.el("span", {
          text: "Showing " + CX.fmt.int(shown.length) + " of " + CX.fmt.int(rows.length) +
            (footerNote ? " · " + footerNote : ""),
        }),
      ]);
      if (visible < rows.length) {
        const more = CX.el("button", {
          type: "button", class: "btn btn-outline-secondary btn-sm", text: "Show more",
        });
        more.addEventListener("click", function () {
          visible += pageSize;
          render();
        });
        footer.appendChild(more);
      }

      host.replaceChildren(
        CX.el("table", { class: "table table-hover table-sm data-table" }, [
          CX.el("thead", {}, [CX.el("tr", {}, headCells)]),
          CX.el("tbody", {}, bodyRows),
        ]),
        footer
      );

      const ids = shown.map(function (row) { return row.orthogroup_id; });
      loadAnnotations(ids).then(function () {
        annotationCells.forEach(function (cell, id) {
          fillAnnotation(cell, annotationCache.get(id));
        });
      });
    }

    return {
      setRows: function (newRows, note) {
        rows = newRows.slice();
        visible = pageSize;
        sortKey = null;
        sortDirection = -1;
        footerNote = note || "";
        selectedId = rows.length ? rows[0].orthogroup_id : null;
        render();
        if (rows.length && config.onSelect) {
          config.onSelect(rows[0]);
        }
      },
    };
  };

  /**
   * Draw one orthogroup's copy number in every species into a chart card.
   *
   * @param {string} cardId - Id of the chart-card figure.
   * @param {string} orthogroupId - Orthogroup to display.
   * @param {Object} [options] - highlight: map of species name to bar color;
   *   species not listed are drawn in the de-emphasis gray.
   */
  CX.orthogroupProfile = async function (cardId, orthogroupId, options) {
    const card = CX.card(cardId);
    if (!card) {
      return;
    }
    const opts = options || {};
    const requested = orthogroupId;
    card.figure.dataset.orthogroup = requested;
    card.body.style.opacity = 0.5;
    let data;
    let colors;
    try {
      const results = await Promise.all([
        CX.fetchJson(CX.urls.orthogroupProfile.replace("__ID__", encodeURIComponent(orthogroupId))),
        CX.speciesColors(),
      ]);
      data = results[0];
      colors = results[1];
    } catch (error) {
      card.body.style.opacity = 1;
      card.status(error.message);
      return;
    }
    // A newer selection may have been made while this request was in flight.
    if (card.figure.dataset.orthogroup !== requested) {
      return;
    }
    card.body.style.opacity = 1;
    card.subtitle(orthogroupId + " · gene copies in each species");
    const neutral = CX.token("--chart-neutral");
    const highlight = opts.highlight || {};
    const rows = data.counts.map(function (entry) {
      return {
        label: entry.short_label,
        full: entry.label,
        value: entry.count,
        italic: true,
        emphasis: Boolean(highlight[entry.name]),
        color: highlight[entry.name] || neutral,
        dot: colors[entry.name] || null,
      };
    });
    // Redraw callback (also used after a window resize).
    const draw = function () {
      CX.charts.barsH(card.clear(), rows, {
        rowHeight: 21,
        barHeight: 11,
        maxLabelWidth: 150,
        ariaLabel: "Gene copies per species for " + orthogroupId,
        tooltip: function (d) {
          return { title: d.full, rows: [["Gene copies", CX.fmt.int(d.value)]] };
        },
      });
    };
    card.redraw = draw;
    draw();
    card.setTable(
      [{ label: "Species", key: "full" }, { label: "Gene copies", key: "value", numeric: true }],
      rows
    );
  };
})(window);
