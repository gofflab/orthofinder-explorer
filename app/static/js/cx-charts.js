/**
 * CephExplorer chart primitives (namespace: window.CX.charts).
 *
 * Each function draws one chart into a host element it fully owns and can be
 * called again to re-render (for example after a resize).  Conventions shared
 * by every chart:
 *
 *  - colors arrive as resolved CSS color strings (callers read them from the
 *    tokens in charts.css with CX.token), never as literals in this file;
 *  - marks are thin, data ends are rounded, grid and axes are hairlines;
 *  - text uses ink classes, never a series color;
 *  - group classes are prefixed (cx-row, cx-col) because Bootstrap styles
 *    bare .row / .col, and its width rules would override SVG rect widths;
 *  - every mark has a hover/focus tooltip, and the page supplies a table twin
 *    through CX.card().setTable().
 */
(function (global) {
  "use strict";

  const CX = global.CX;
  const charts = (CX.charts = {});

  const BAR_RADIUS = 4;
  const MAX_BAR = 24;

  /**
   * Create a fresh <svg> inside a host element.
   *
   * @param {HTMLElement} host - Element to draw into (emptied first).
   * @param {number} width - SVG width in pixels.
   * @param {number} height - SVG height in pixels.
   * @param {string} [label] - Accessible name for the chart.
   * @returns {d3.Selection} The svg selection.
   */
  function createSvg(host, width, height, label) {
    host.replaceChildren();
    return d3
      .select(host)
      .append("svg")
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", "0 0 " + width + " " + height)
      .attr("role", "group")
      .attr("aria-label", label || null);
  }

  /**
   * Usable width of a host element, with a floor for hidden containers.
   * @param {HTMLElement} host
   * @returns {number}
   */
  function hostWidth(host) {
    return Math.max(host.clientWidth || host.parentNode.clientWidth || 0, 280);
  }

  /**
   * Path for a horizontal bar: square at the baseline, rounded data end.
   * @returns {string} SVG path data.
   */
  function barRight(x, y, w, h) {
    const r = Math.max(0, Math.min(BAR_RADIUS, w, h / 2));
    return (
      "M" + x + "," + y + "h" + (w - r) + "a" + r + "," + r + " 0 0 1 " + r + "," + r +
      "v" + (h - 2 * r) + "a" + r + "," + r + " 0 0 1 " + -r + "," + r + "h" + -(w - r) + "z"
    );
  }

  /**
   * Path for a vertical column: square at the baseline, rounded top.
   * @returns {string} SVG path data.
   */
  function barTop(x, y, w, h) {
    const r = Math.max(0, Math.min(BAR_RADIUS, h, w / 2));
    return (
      "M" + x + "," + (y + h) + "v" + -(h - r) + "a" + r + "," + r + " 0 0 1 " + r + "," + -r +
      "h" + (w - 2 * r) + "a" + r + "," + r + " 0 0 1 " + r + "," + r + "v" + (h - r) + "z"
    );
  }

  /**
   * Draw horizontal hairline gridlines with tick labels for a y scale.
   *
   * @param {d3.Selection} g - Group positioned at the plot origin.
   * @param {d3.Scale} y - Linear scale mapping values to pixels.
   * @param {number} width - Plot width.
   * @param {Function} format - Tick formatter.
   * @param {number} [count=4] - Approximate number of ticks.
   */
  function yGrid(g, y, width, format, count) {
    const ticks = y.ticks(count || 4);
    const rows = g.append("g").selectAll("g").data(ticks).join("g")
      .attr("transform", function (d) { return "translate(0," + y(d) + ")"; });
    rows.append("line")
      .attr("class", function (d) { return d === 0 ? "axis-line" : "grid-line"; })
      .attr("x2", width);
    rows.append("text").attr("class", "tick-label").attr("x", -6).attr("dy", "0.32em")
      .attr("text-anchor", "end").text(format);
  }

  /**
   * Build a color interpolator from a three-stop sequential ramp.
   *
   * @param {string} prefix - Token prefix, e.g. "--chart-seq-a".
   * @returns {Function} Interpolator mapping [0, 1] to a CSS color.
   */
  charts.ramp = function (prefix) {
    return d3.piecewise(d3.interpolateLab, [
      CX.token(prefix + "-low"),
      CX.token(prefix + "-mid"),
      CX.token(prefix + "-high"),
    ]);
  };

  /**
   * Choose a readable ink for text placed on a filled cell.
   *
   * @param {string} fill - CSS color of the cell.
   * @returns {string} Light or dark ink token value.
   */
  charts.inkOn = function (fill) {
    return d3.lab(fill).l < 58 ? CX.token("--chart-on-dark") : CX.token("--chart-on-light");
  };

  // ---- Horizontal ranked bars ---------------------------------------------

  /**
   * Horizontal bar chart with the label on the left and the value at the tip.
   *
   * @param {HTMLElement} host - Element to draw into.
   * @param {Array<Object>} rows - { label, value, color?, italic?, dot?,
   *   valueText? } plus any payload the callbacks need.
   * @param {Object} [options] - color: default bar color; valueFormat;
   *   rowHeight; barHeight; maxLabelWidth; tooltip(row): tooltip content;
   *   onClick(row); ariaLabel.
   */
  charts.barsH = function (host, rows, options) {
    const opts = Object.assign(
      { valueFormat: CX.fmt.int, rowHeight: 24, barHeight: 14, maxLabelWidth: 180 },
      options
    );
    const width = hostWidth(host);
    const hasDots = rows.some(function (row) { return row.dot; });
    const labelWidth = Math.min(
      opts.maxLabelWidth,
      (d3.max(rows, function (row) { return CX.textWidth(row.label); }) || 0) + 10
    ) + (hasDots ? 14 : 0);
    // Text shown at the bar tip: an explicit override or the formatted value.
    const valueText = function (row) {
      return row.valueText !== undefined ? row.valueText : opts.valueFormat(row.value);
    };
    const valueWidth = (d3.max(rows, function (row) { return CX.textWidth(valueText(row)); }) || 0) + 10;
    const plotWidth = Math.max(40, width - labelWidth - valueWidth);
    const height = rows.length * opts.rowHeight + 4;
    const x = d3.scaleLinear()
      .domain([0, opts.domainMax || d3.max(rows, function (row) { return row.value; }) || 1])
      .range([0, plotWidth]);
    const svg = createSvg(host, width, height, opts.ariaLabel);

    const groups = svg.selectAll("g.cx-row").data(rows).join("g").attr("class", "cx-row")
      .attr("transform", function (d, i) { return "translate(0," + (i * opts.rowHeight + 2) + ")"; });

    // The clade dot sits just left of its (right-aligned) label.
    groups.filter(function (d) { return d.dot; }).append("circle")
      .attr("cx", function (d) {
        return Math.max(5, labelWidth - 8 - Math.min(CX.textWidth(d.label), opts.maxLabelWidth) - 9);
      })
      .attr("cy", opts.rowHeight / 2).attr("r", 4)
      .attr("fill", function (d) { return d.dot; });

    groups.append("text")
      .attr("class", function (d) { return "mark-label" + (d.italic ? " species-name" : ""); })
      .attr("x", labelWidth - 8).attr("y", opts.rowHeight / 2).attr("dy", "0.32em")
      .attr("text-anchor", "end")
      .attr("font-weight", function (d) { return d.emphasis ? 600 : null; })
      .text(function (d) { return d.label; });

    groups.append("path").attr("class", "bar")
      .attr("fill", function (d) { return d.color || opts.color; })
      .attr("d", function (d) {
        const w = d.value > 0 ? Math.max(x(d.value), 1.5) : 0;
        return barRight(labelWidth, (opts.rowHeight - opts.barHeight) / 2, w, opts.barHeight);
      });

    groups.append("text").attr("class", "mark-label")
      .attr("x", function (d) { return labelWidth + x(d.value) + 6; })
      .attr("y", opts.rowHeight / 2).attr("dy", "0.32em")
      .style("font-variant-numeric", "tabular-nums")
      .text(valueText);

    // The whole row is the hit target, not just the painted bar.
    const hits = groups.append("rect").attr("class", "hit")
      .attr("width", width).attr("height", opts.rowHeight);
    CX.interact(hits, {
      content: opts.tooltip || function (d) {
        return { title: d.label, rows: [[opts.valueLabel || "Value", valueText(d)]] };
      },
      onClick: opts.onClick,
      highlight: function (d, on, node) {
        d3.select(node.parentNode).select(".bar").classed("is-hovered", on);
      },
    });
  };

  // ---- Vertical columns (categorical x) -----------------------------------

  /**
   * Column chart over ordered categories (bins, strata, species counts).
   *
   * @param {HTMLElement} host - Element to draw into.
   * @param {Array<Object>} rows - { label, value, color? }.
   * @param {Object} [options] - color; height; xLabel; yLabel; valueFormat;
   *   tooltip(row); onClick(row); ariaLabel.
   */
  charts.columns = function (host, rows, options) {
    const opts = Object.assign({ height: 230, valueFormat: CX.fmt.int }, options);
    const width = hostWidth(host);
    const maxValue = d3.max(rows, function (row) { return row.value; }) || 1;
    const y = d3.scaleLinear().domain([0, maxValue]).nice(4);
    const tickFormat = CX.fmt.tick;
    const margin = {
      top: 10,
      right: 8,
      bottom: opts.xLabel ? 42 : 24,
      left: (d3.max(y.ticks(4), function (t) { return CX.textWidth(tickFormat(t)); }) || 20) + 12 +
        (opts.yLabel ? 16 : 0),
    };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = opts.height - margin.top - margin.bottom;
    y.range([plotHeight, 0]);
    const x = d3.scaleBand()
      .domain(rows.map(function (row) { return row.label; }))
      .range([0, plotWidth]).paddingInner(0.25).paddingOuter(0.15);
    const barWidth = Math.min(MAX_BAR, x.bandwidth());

    const svg = createSvg(host, width, opts.height, opts.ariaLabel);
    const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
    yGrid(g, y, plotWidth, tickFormat);

    const groups = g.selectAll("g.cx-col").data(rows).join("g").attr("class", "cx-col")
      .attr("transform", function (d) { return "translate(" + x(d.label) + ",0)"; });
    groups.append("path").attr("class", "bar")
      .attr("fill", function (d) { return d.color || opts.color; })
      .attr("d", function (d) {
        const h = d.value > 0 ? Math.max(plotHeight - y(d.value), 1.5) : 0;
        return barTop((x.bandwidth() - barWidth) / 2, plotHeight - h, barWidth, h);
      });

    // Thin out x labels when the bands are too narrow to hold every one.
    const widest = d3.max(rows, function (row) { return CX.textWidth(row.label); }) || 0;
    const step = Math.max(1, Math.ceil((widest + 6) / x.step()));
    groups.filter(function (d, i) { return i % step === 0; }).append("text")
      .attr("class", "tick-label").attr("x", x.bandwidth() / 2).attr("y", plotHeight + 15)
      .attr("text-anchor", "middle").text(function (d) { return d.label; });

    if (opts.xLabel) {
      g.append("text").attr("class", "axis-label").attr("x", plotWidth / 2)
        .attr("y", plotHeight + 36).attr("text-anchor", "middle").text(opts.xLabel);
    }
    if (opts.yLabel) {
      svg.append("text").attr("class", "axis-label")
        .attr("transform", "translate(11," + (margin.top + plotHeight / 2) + ") rotate(-90)")
        .attr("text-anchor", "middle").text(opts.yLabel);
    }

    const hits = groups.append("rect").attr("class", "hit")
      .attr("width", x.step()).attr("x", -(x.step() - x.bandwidth()) / 2)
      .attr("height", plotHeight + margin.bottom);
    CX.interact(hits, {
      content: opts.tooltip || function (d) {
        return { title: d.label, rows: [[opts.yLabel || "Value", opts.valueFormat(d.value)]] };
      },
      onClick: opts.onClick,
      highlight: function (d, on, node) {
        d3.select(node.parentNode).select(".bar").classed("is-hovered", on);
      },
    });
  };

  // ---- Histogram (numeric x) ----------------------------------------------

  /**
   * Histogram over contiguous numeric bins.
   *
   * @param {HTMLElement} host - Element to draw into.
   * @param {Array<Object>} bins - { x0, x1, count, color? }.  A bin whose x1
   *   is null is drawn as a final open-ended bin of the same width.
   * @param {Object} [options] - color; height; xLabel; yLabel; markers:
   *   Array<{ x, label }> vertical reference lines; tickValues; tickFormat;
   *   tooltip(bin); ariaLabel.
   */
  charts.histogram = function (host, bins, options) {
    const opts = Object.assign({ height: 230 }, options);
    const width = hostWidth(host);
    const closed = bins.filter(function (bin) { return bin.x1 !== null; });
    const binWidth = closed.length ? closed[0].x1 - closed[0].x0 : 1;
    const drawn = bins.map(function (bin) {
      return Object.assign({}, bin, { end: bin.x1 === null ? bin.x0 + binWidth : bin.x1, open: bin.x1 === null });
    });
    const maxValue = d3.max(drawn, function (bin) { return bin.count; }) || 1;
    const y = d3.scaleLinear().domain([0, maxValue]).nice(4);
    const margin = {
      top: 16,
      right: 10,
      bottom: opts.xLabel ? 42 : 24,
      left: (d3.max(y.ticks(4), function (t) { return CX.textWidth(CX.fmt.tick(t)); }) || 20) + 12 +
        (opts.yLabel ? 16 : 0),
    };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = opts.height - margin.top - margin.bottom;
    y.range([plotHeight, 0]);
    const x = d3.scaleLinear()
      .domain([drawn[0].x0, drawn[drawn.length - 1].end]).range([0, plotWidth]);

    const svg = createSvg(host, width, opts.height, opts.ariaLabel);
    const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
    yGrid(g, y, plotWidth, CX.fmt.tick);

    const groups = g.selectAll("g.bin").data(drawn).join("g").attr("class", "bin");
    groups.append("path").attr("class", "bar")
      .attr("fill", function (d) { return d.color || opts.color; })
      .attr("d", function (d) {
        // A 1px inset on each side leaves a 2px surface gap between bars.
        const left = x(d.x0) + 1;
        const w = Math.max(x(d.end) - x(d.x0) - 2, 1);
        const h = d.count > 0 ? Math.max(plotHeight - y(d.count), 1.5) : 0;
        return barTop(left, plotHeight - h, w, h);
      });

    const tickValues = opts.tickValues || x.ticks(Math.max(3, Math.floor(plotWidth / 70)));
    const tickFormat = opts.tickFormat || CX.fmt.tick;
    g.append("g").selectAll("text").data(tickValues).join("text")
      .attr("class", "tick-label").attr("x", function (d) { return x(d); })
      .attr("y", plotHeight + 15).attr("text-anchor", "middle").text(tickFormat);

    (opts.markers || []).forEach(function (marker) {
      if (marker.x < x.domain()[0] || marker.x > x.domain()[1]) {
        return;
      }
      g.append("line").attr("class", "axis-line").attr("x1", x(marker.x)).attr("x2", x(marker.x))
        .attr("y1", -6).attr("y2", plotHeight);
      g.append("text").attr("class", "annotation").attr("x", x(marker.x) + 4).attr("y", -6)
        .attr("text-anchor", x(marker.x) > plotWidth * 0.75 ? "end" : "start")
        .attr("dx", x(marker.x) > plotWidth * 0.75 ? -8 : 0)
        .text(marker.label);
    });

    if (opts.xLabel) {
      g.append("text").attr("class", "axis-label").attr("x", plotWidth / 2)
        .attr("y", plotHeight + 36).attr("text-anchor", "middle").text(opts.xLabel);
    }
    if (opts.yLabel) {
      svg.append("text").attr("class", "axis-label")
        .attr("transform", "translate(11," + (margin.top + plotHeight / 2) + ") rotate(-90)")
        .attr("text-anchor", "middle").text(opts.yLabel);
    }

    const hits = groups.append("rect").attr("class", "hit")
      .attr("x", function (d) { return x(d.x0); })
      .attr("width", function (d) { return Math.max(x(d.end) - x(d.x0), 1); })
      .attr("height", plotHeight);
    CX.interact(hits, {
      content: opts.tooltip || function (d) {
        const range = d.open ? "≥ " + tickFormat(d.x0) : tickFormat(d.x0) + " to " + tickFormat(d.end);
        return { title: range, rows: [[opts.yLabel || "Count", CX.fmt.int(d.count)]] };
      },
      highlight: function (d, on, node) {
        d3.select(node.parentNode).select(".bar").classed("is-hovered", on);
      },
    });
  };

  // ---- Species tree + stacked bars ----------------------------------------

  /**
   * Stacked horizontal bars, one row per species, optionally aligned to a
   * cladogram of the species tree.
   *
   * @param {HTMLElement} host - Element to draw into.
   * @param {Array<Object>} rows - { name, label, values: {key: number},
   *   dot? } in display (tree) order.
   * @param {Object} options - segments: Array<{ key, label, color }> in
   *   stacking order; tree: nested { name, children } or null; normalize:
   *   draw shares instead of counts; tooltip(row, segment); onClick(row);
   *   ariaLabel.
   */
  charts.stackedSpecies = function (host, rows, options) {
    const opts = Object.assign({ rowHeight: 22, barHeight: 12 }, options);
    const width = hostWidth(host);
    // On narrow screens the cladogram is dropped so the bars keep their room.
    const treeWidth = opts.tree && width >= 520 ? Math.min(120, width * 0.18) : 0;
    const labelWidth = (d3.max(rows, function (row) { return CX.textWidth(row.label); }) || 0) + 26;
    // Sum of all segment values for one species row.
    const total = function (row) {
      return d3.sum(opts.segments, function (segment) { return row.values[segment.key] || 0; });
    };
    // Formatted row total, drawn at the end of the stacked bar.
    const totalText = function (row) { return CX.fmt.int(total(row)); };
    const valueWidth = opts.normalize ? 8 :
      (d3.max(rows, function (row) { return CX.textWidth(totalText(row)); }) || 0) + 12;
    const left = treeWidth + labelWidth;
    const plotWidth = Math.max(60, width - left - valueWidth);
    const axisHeight = 22;
    const height = rows.length * opts.rowHeight + axisHeight + 4;
    const maxTotal = d3.max(rows, total) || 1;
    const x = d3.scaleLinear().domain([0, opts.normalize ? 1 : maxTotal]).range([0, plotWidth]);
    if (!opts.normalize) {
      x.nice(4);
    }

    const svg = createSvg(host, width, height, opts.ariaLabel);
    const plot = svg.append("g").attr("transform", "translate(" + left + ",0)");

    // Vertical hairlines and bottom axis labels.
    const ticks = x.ticks(4);
    plot.append("g").selectAll("line").data(ticks).join("line")
      .attr("class", function (d) { return d === 0 ? "axis-line" : "grid-line"; })
      .attr("x1", x).attr("x2", x).attr("y2", rows.length * opts.rowHeight);
    plot.append("g").selectAll("text").data(ticks).join("text").attr("class", "tick-label")
      .attr("x", x).attr("y", rows.length * opts.rowHeight + 15).attr("text-anchor", "middle")
      .text(opts.normalize ? CX.fmt.pct0 : CX.fmt.tick);

    if (treeWidth) {
      const rowIndex = new Map(rows.map(function (row, i) { return [row.name, i]; }));
      const root = d3.hierarchy(opts.tree);
      root.eachAfter(function (node) {
        node.py = node.children
          ? d3.mean(node.children, function (child) { return child.py; })
          : (rowIndex.get(node.data.name) + 0.5) * opts.rowHeight;
        // Cladogram: every leaf is flush right, depth is set by node height.
        node.px = 4 + (treeWidth - 10) * (1 - node.height / Math.max(root.height, 1));
      });
      svg.append("g").selectAll("path").data(root.descendants().filter(function (n) { return n.parent; }))
        .join("path").attr("class", "tree-link")
        .attr("d", function (n) {
          return "M" + n.parent.px + "," + n.parent.py + "V" + n.py + "H" + n.px;
        });
    }

    const groups = svg.selectAll("g.cx-row").data(rows).join("g").attr("class", "cx-row")
      .attr("transform", function (d, i) { return "translate(0," + i * opts.rowHeight + ")"; });

    groups.append("circle").attr("cx", treeWidth + 8).attr("cy", opts.rowHeight / 2).attr("r", 4)
      .attr("fill", function (d) { return d.dot || CX.token("--chart-neutral"); });
    groups.append("text").attr("class", "mark-label species-name")
      .attr("x", treeWidth + 18).attr("y", opts.rowHeight / 2).attr("dy", "0.32em")
      .text(function (d) { return d.label; });

    groups.each(function (row) {
      const rowTotal = total(row) || 1;
      let offset = 0;
      const group = d3.select(this);
      opts.segments.forEach(function (segment) {
        const raw = row.values[segment.key] || 0;
        const value = opts.normalize ? raw / rowTotal : raw;
        const x0 = x(offset);
        const x1 = x(offset + value);
        offset += value;
        if (x1 - x0 < 0.5) {
          return;
        }
        // Inset each segment so neighbours are separated by a surface gap.
        group.append("rect").attr("class", "bar")
          .attr("x", left + x0).attr("width", Math.max(x1 - x0 - 2, 0.75))
          .attr("y", (opts.rowHeight - opts.barHeight) / 2).attr("height", opts.barHeight)
          .attr("rx", 2).attr("fill", segment.color);
      });
      if (!opts.normalize) {
        group.append("text").attr("class", "mark-label")
          .attr("x", left + x(total(row)) + 6).attr("y", opts.rowHeight / 2).attr("dy", "0.32em")
          .style("font-variant-numeric", "tabular-nums").text(totalText(row));
      }
    });

    const hits = groups.append("rect").attr("class", "hit")
      .attr("x", treeWidth).attr("width", width - treeWidth).attr("height", opts.rowHeight);
    CX.interact(hits, {
      content: opts.tooltip,
      onClick: opts.onClick,
      highlight: function (d, on, node) {
        d3.select(node.parentNode).selectAll(".bar").classed("is-hovered", on);
      },
    });
  };

  // ---- Heatmap ------------------------------------------------------------

  /**
   * Grid heatmap with row labels on the left and column labels on top.
   *
   * @param {HTMLElement} host - Element to draw into.
   * @param {Object} spec - rows / cols: label arrays; cells: Array<{ r, c,
   *   fill, text? }> plus payload; italic: italicise labels; rotate: rotate
   *   column labels; rowTitle / colTitle: axis titles; maxCell: largest cell
   *   size; tooltip(cell); onClick(cell); ariaLabel.
   */
  charts.heatmap = function (host, spec) {
    const width = hostWidth(host);
    const rowLabelWidth = (d3.max(spec.rows, function (l) { return CX.textWidth(l); }) || 0) + 12 +
      (spec.rowTitle ? 18 : 0);
    const widestCol = d3.max(spec.cols, function (l) { return CX.textWidth(l); }) || 0;
    /**
     * Cell size and label geometry for upright or rotated column labels.
     * @param {boolean} rotated - Whether column labels are rotated.
     * @returns {Object} { cell, colLabelSize, overhang }.
     */
    const layout = function (rotated) {
      const colLabelSize = rotated ? widestCol * 0.72 + 14 : 20;
      // Rotated labels lean past the last column, so reserve room on the right.
      const overhang = rotated ? colLabelSize : 4;
      const cell = Math.max(10, Math.min(
        spec.maxCell || 44,
        Math.floor((width - rowLabelWidth - overhang) / spec.cols.length)
      ));
      return { cell: cell, colLabelSize: colLabelSize, overhang: overhang };
    };
    let geometry = layout(Boolean(spec.rotate));
    // Upright labels that would collide (narrow screens) are rotated instead.
    const rotate = Boolean(spec.rotate) || widestCol > geometry.cell - 4;
    if (rotate && !spec.rotate) {
      geometry = layout(true);
    }
    const cell = geometry.cell;
    const overhang = geometry.overhang;
    const top = geometry.colLabelSize + (spec.colTitle ? 18 : 0);
    const gridWidth = cell * spec.cols.length;
    const gridHeight = cell * spec.rows.length;
    const svg = createSvg(host, Math.min(width, rowLabelWidth + gridWidth + overhang), top + gridHeight + 4, spec.ariaLabel);
    const labelClass = "mark-label" + (spec.italic ? " species-name" : "");

    const g = svg.append("g").attr("transform", "translate(" + rowLabelWidth + "," + top + ")");
    const rowLabels = g.append("g").selectAll("text").data(spec.rows).join("text")
      .attr("class", labelClass).attr("x", -8)
      .attr("y", function (d, i) { return i * cell + cell / 2; })
      .attr("dy", "0.32em").attr("text-anchor", "end").text(function (d) { return d; });
    const colLabels = g.append("g").selectAll("text").data(spec.cols).join("text")
      .attr("class", labelClass)
      .attr("transform", function (d, i) {
        const cx = i * cell + cell / 2;
        return rotate ? "translate(" + (cx + 3) + ",-8) rotate(-45)" : "translate(" + cx + ",-8)";
      })
      .attr("text-anchor", rotate ? "start" : "middle").text(function (d) { return d; });

    if (spec.rowTitle) {
      svg.append("text").attr("class", "axis-label")
        .attr("transform", "translate(11," + (top + gridHeight / 2) + ") rotate(-90)")
        .attr("text-anchor", "middle").text(spec.rowTitle);
    }
    if (spec.colTitle) {
      svg.append("text").attr("class", "axis-label").attr("x", rowLabelWidth + gridWidth / 2)
        .attr("y", 12).attr("text-anchor", "middle").text(spec.colTitle);
    }

    const cells = g.selectAll("g.cell").data(spec.cells).join("g").attr("class", "cell")
      .attr("transform", function (d) { return "translate(" + d.c * cell + "," + d.r * cell + ")"; });
    cells.append("rect").attr("class", "bar").attr("x", 1).attr("y", 1)
      .attr("width", cell - 2).attr("height", cell - 2).attr("rx", Math.min(3, cell / 6))
      .attr("fill", function (d) { return d.fill; });
    cells.filter(function (d) { return d.text && CX.textWidth(d.text, "11px sans-serif") < cell - 6; })
      .append("text").attr("x", cell / 2).attr("y", cell / 2).attr("dy", "0.32em")
      .attr("text-anchor", "middle").attr("font-size", 11)
      .style("font-variant-numeric", "tabular-nums")
      .attr("fill", function (d) { return charts.inkOn(d.fill); })
      .text(function (d) { return d.text; });

    const hits = cells.append("rect").attr("class", "hit").attr("width", cell).attr("height", cell);
    CX.interact(hits, {
      content: spec.tooltip,
      onClick: spec.onClick,
      highlight: function (d, on, node) {
        d3.select(node.parentNode).select(".bar").classed("is-hovered", on);
        rowLabels.filter(function (l, i) { return i === d.r; }).attr("font-weight", on ? 700 : null);
        colLabels.filter(function (l, i) { return i === d.c; }).attr("font-weight", on ? 700 : null);
      },
    });
  };

  // ---- Bubble scatter ------------------------------------------------------

  /**
   * Scatter / bubble plot with nearest-point hover.
   *
   * @param {HTMLElement} host - Element to draw into.
   * @param {Array<Object>} points - { x, y, size, color } plus payload.
   * @param {Object} [options] - height; xLabel; yLabel; xDomain; yDomain;
   *   xTicks / yTicks: { values, format }; diagonal: draw the y = x line;
   *   zeroLines: emphasise x = 0 and y = 0; corners: { tl, tr, bl, br }
   *   annotations; radius: [min, max]; tooltip(point); onClick(point);
   *   ariaLabel.
   */
  charts.scatter = function (host, points, options) {
    const opts = Object.assign({ height: 360, radius: [4, 15] }, options);
    const width = hostWidth(host);
    const margin = { top: 14, right: 14, bottom: 44, left: 52 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = opts.height - margin.top - margin.bottom;
    // Widen a data extent by 6% on each side so marks clear the plot edge.
    const pad = function (extent) {
      const span = (extent[1] - extent[0]) || 1;
      return [extent[0] - span * 0.06, extent[1] + span * 0.06];
    };
    const x = d3.scaleLinear()
      .domain(opts.xDomain || pad(d3.extent(points, function (p) { return p.x; })))
      .range([0, plotWidth]);
    const y = d3.scaleLinear()
      .domain(opts.yDomain || pad(d3.extent(points, function (p) { return p.y; })))
      .range([plotHeight, 0]);
    const r = d3.scaleSqrt()
      .domain([1, Math.max(2, d3.max(points, function (p) { return p.size || 1; }) || 1)])
      .range(opts.radius).clamp(true);

    const svg = createSvg(host, width, opts.height, opts.ariaLabel);
    const g = svg.append("g").attr("transform", "translate(" + margin.left + "," + margin.top + ")");
    const xTicks = opts.xTicks || { values: x.ticks(6), format: d3.format("~g") };
    const yTicks = opts.yTicks || { values: y.ticks(6), format: d3.format("~g") };
    // Keep only ticks that fall inside the (possibly caller-supplied) domains.
    const inX = function (v) { return v >= x.domain()[0] && v <= x.domain()[1]; };
    const inY = function (v) { return v >= y.domain()[0] && v <= y.domain()[1]; };

    g.append("g").selectAll("line").data(xTicks.values.filter(inX)).join("line")
      .attr("class", function (d) { return opts.zeroLines && d === 0 ? "axis-line" : "grid-line"; })
      .attr("x1", x).attr("x2", x).attr("y2", plotHeight);
    g.append("g").selectAll("line").data(yTicks.values.filter(inY)).join("line")
      .attr("class", function (d) { return opts.zeroLines && d === 0 ? "axis-line" : "grid-line"; })
      .attr("y1", y).attr("y2", y).attr("x2", plotWidth);
    g.append("g").selectAll("text").data(xTicks.values.filter(inX)).join("text")
      .attr("class", "tick-label").attr("x", x).attr("y", plotHeight + 15)
      .attr("text-anchor", "middle").text(xTicks.format);
    g.append("g").selectAll("text").data(yTicks.values.filter(inY)).join("text")
      .attr("class", "tick-label").attr("x", -8).attr("y", y).attr("dy", "0.32em")
      .attr("text-anchor", "end").text(yTicks.format);

    if (opts.diagonal) {
      const lo = Math.max(x.domain()[0], y.domain()[0]);
      const hi = Math.min(x.domain()[1], y.domain()[1]);
      g.append("line").attr("class", "axis-line")
        .attr("x1", x(lo)).attr("y1", y(lo)).attr("x2", x(hi)).attr("y2", y(hi));
    }

    const corners = opts.corners || {};
    [
      ["tl", 6, 12, "start"], ["tr", plotWidth - 6, 12, "end"],
      ["bl", 6, plotHeight - 8, "start"], ["br", plotWidth - 6, plotHeight - 8, "end"],
    ].forEach(function (corner) {
      if (corners[corner[0]]) {
        g.append("text").attr("class", "annotation").attr("x", corner[1]).attr("y", corner[2])
          .attr("text-anchor", corner[3]).text(corners[corner[0]]);
      }
    });

    g.append("text").attr("class", "axis-label").attr("x", plotWidth / 2).attr("y", plotHeight + 36)
      .attr("text-anchor", "middle").text(opts.xLabel || "");
    svg.append("text").attr("class", "axis-label")
      .attr("transform", "translate(12," + (margin.top + plotHeight / 2) + ") rotate(-90)")
      .attr("text-anchor", "middle").text(opts.yLabel || "");

    // Large bubbles first so small ones stay visible and reachable on top.
    const ordered = points.slice().sort(function (a, b) { return (b.size || 1) - (a.size || 1); });
    const surface = CX.token("--chart-surface");
    const marks = g.append("g").selectAll("circle").data(ordered).join("circle")
      .attr("cx", function (p) { return x(p.x); }).attr("cy", function (p) { return y(p.y); })
      .attr("r", function (p) { return r(p.size || 1); })
      .attr("fill", function (p) { return p.color; }).attr("fill-opacity", 0.82)
      .attr("stroke", surface).attr("stroke-width", 1.5);

    // Nearest-point hover: the pointer only has to be close, not dead-centre.
    const delaunay = d3.Delaunay.from(ordered, function (p) { return x(p.x); }, function (p) { return y(p.y); });
    let active = null;
    const focusRing = g.append("circle").attr("fill", "none")
      .attr("stroke", CX.token("--chart-ink")).attr("stroke-width", 1.5).attr("display", "none");
    const overlay = g.append("rect").attr("class", "hit" + (opts.onClick ? " is-clickable" : ""))
      .attr("width", plotWidth).attr("height", plotHeight);
    overlay
      .on("pointermove", function (event) {
        const position = d3.pointer(event);
        const index = delaunay.find(position[0], position[1]);
        const point = ordered[index];
        const near = point && Math.hypot(x(point.x) - position[0], y(point.y) - position[1]) <= r(point.size || 1) + 18;
        active = near ? point : null;
        if (!active) {
          focusRing.attr("display", "none");
          CX.tooltip.hide();
          return;
        }
        focusRing.attr("display", null).attr("cx", x(point.x)).attr("cy", y(point.y))
          .attr("r", r(point.size || 1) + 2);
        CX.tooltip.show(event, opts.tooltip(point));
      })
      .on("pointerleave", function () {
        active = null;
        focusRing.attr("display", "none");
        CX.tooltip.hide();
      })
      .on("click", function () {
        if (active && opts.onClick) {
          opts.onClick(active);
        }
      });
    return marks;
  };
})(window);
