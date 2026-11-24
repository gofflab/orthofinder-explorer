/**
 * CephExplorer shared front-end helpers (namespace: window.CX).
 *
 * Loaded before the chart and page scripts.  Nothing here knows about a
 * specific page; it provides DOM construction, formatting, color-token
 * lookup, a shared tooltip, and the chart-card plumbing (status messages and
 * the "view data" table twin that every chart exposes).
 */
(function (global) {
  "use strict";

  const CX = (global.CX = global.CX || {});

  /**
   * Read a CSS custom property from the document root.
   *
   * Chart colors are never written in JavaScript; they are looked up here so
   * the palette stays editable in charts.css.
   *
   * @param {string} name - Custom property name, e.g. "--chart-series-a".
   * @returns {string} The trimmed property value.
   */
  CX.token = function (name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  };

  /** Number formatters shared by charts, tiles and tables. */
  CX.fmt = {
    int: d3.format(","),
    pct: d3.format(".1%"),
    pct0: d3.format(".0%"),
    fixed1: d3.format(".1f"),
    signed: d3.format("+.2f"),
    /**
     * Count with a correctly pluralised noun, e.g. "1 copy" / "3 copies".
     * @param {number} value
     * @param {string} singular
     * @param {string} plural
     * @returns {string}
     */
    count: function (value, singular, plural) {
      return d3.format(",")(value) + " " + (value === 1 ? singular : plural);
    },
    /**
     * Compact axis-tick formatter: full digits below 10,000, SI above.
     * @param {number} value
     * @returns {string}
     */
    tick: function (value) {
      return Math.abs(value) >= 10000 ? d3.format(".2~s")(value) : d3.format(",")(value);
    },
  };

  /**
   * Create a DOM element.  Text is always assigned via textContent so labels
   * that originate in the database can never inject markup.
   *
   * @param {string} tag - Element tag name.
   * @param {Object} [attrs] - Attributes; "text" sets textContent and "class"
   *   sets className.  Null/undefined values are skipped.
   * @param {Array<Node|string>} [children] - Child nodes or strings.
   * @returns {HTMLElement}
   */
  CX.el = function (tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(function ([key, value]) {
      if (value === null || value === undefined || value === false) {
        return;
      }
      if (key === "text") {
        node.textContent = value;
      } else if (key === "class") {
        node.className = value;
      } else {
        node.setAttribute(key, value === true ? "" : value);
      }
    });
    (children || []).forEach(function (child) {
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  };

  /**
   * Fetch JSON and raise a readable error on failure.
   *
   * @param {string} url - Endpoint URL.
   * @param {RequestInit} [options] - fetch() options.
   * @returns {Promise<Object>} Parsed response body.
   */
  CX.fetchJson = async function (url, options) {
    const response = await fetch(url, options);
    let body = null;
    try {
      body = await response.json();
    } catch (error) {
      body = null;
    }
    if (!response.ok) {
      throw new Error((body && body.error) || "Request failed (" + response.status + ")");
    }
    return body;
  };

  /**
   * Build a URL with query parameters, skipping empty values.
   *
   * @param {string} base - Path without a query string.
   * @param {Object} params - Query parameters.
   * @returns {string}
   */
  CX.url = function (base, params) {
    const query = new URLSearchParams();
    Object.entries(params || {}).forEach(function ([key, value]) {
      if (value !== null && value !== undefined && value !== "") {
        query.set(key, value);
      }
    });
    const text = query.toString();
    return text ? base + "?" + text : base;
  };

  let colorPromise = null;
  /**
   * Load the clade-based species color map once per page.
   *
   * @returns {Promise<Object>} Map of species name to color; empty on failure.
   */
  CX.speciesColors = function () {
    if (!colorPromise) {
      colorPromise = fetch(CX.urls.speciesColors)
        .then(function (response) {
          return response.ok ? response.json() : {};
        })
        .catch(function () {
          return {};
        });
    }
    return colorPromise;
  };

  let measureContext = null;
  /**
   * Measure rendered text width so charts can size their margins.
   *
   * @param {string} text - Text to measure.
   * @param {string} [font] - CSS font shorthand; defaults to the chart font.
   * @returns {number} Width in pixels.
   */
  CX.textWidth = function (text, font) {
    if (!measureContext) {
      measureContext = document.createElement("canvas").getContext("2d");
    }
    const family = getComputedStyle(document.body).fontFamily;
    measureContext.font = font || "12px " + family;
    return measureContext.measureText(String(text)).width;
  };

  // ---- Tooltip -----------------------------------------------------------

  let tooltipNode = null;

  /**
   * Shared tooltip.  Content is a title plus label/value rows; values lead
   * visually because the reader already knows which mark they are on.
   */
  CX.tooltip = {
    /**
     * Show the tooltip near a pointer or focus event.
     *
     * @param {Event} event - pointermove/focus event (or any with a target).
     * @param {Object} content - { title: string, rows: Array<[label, value]>,
     *   note: string }.
     */
    show: function (event, content) {
      if (!tooltipNode) {
        tooltipNode = CX.el("aside", { class: "chart-tooltip", role: "status", hidden: true });
        document.body.appendChild(tooltipNode);
      }
      tooltipNode.replaceChildren();
      if (content.title) {
        tooltipNode.appendChild(CX.el("span", { class: "tooltip-title", text: content.title }));
      }
      (content.rows || []).forEach(function (row) {
        tooltipNode.appendChild(
          CX.el("span", { class: "tooltip-row" }, [
            CX.el("span", { text: row[0] }),
            CX.el("span", { class: "tooltip-value", text: row[1] }),
          ])
        );
      });
      if (content.note) {
        tooltipNode.appendChild(CX.el("span", { text: content.note }));
      }
      tooltipNode.hidden = false;
      CX.tooltip.move(event);
    },
    /**
     * Reposition the tooltip, keeping it inside the viewport.
     * @param {Event} event
     */
    move: function (event) {
      if (!tooltipNode || tooltipNode.hidden) {
        return;
      }
      let x = event.pageX;
      let y = event.pageY;
      if (x === undefined || (event.type && event.type.indexOf("focus") === 0)) {
        // Keyboard focus has no pointer position: anchor to the element.
        const box = event.target.getBoundingClientRect();
        x = box.left + box.width / 2 + global.scrollX;
        y = box.top + global.scrollY;
      }
      const width = tooltipNode.offsetWidth;
      const height = tooltipNode.offsetHeight;
      const maxX = global.scrollX + document.documentElement.clientWidth - width - 8;
      const left = Math.max(global.scrollX + 8, Math.min(x + 14, maxX));
      const top = y - height - 12 < global.scrollY + 8 ? y + 18 : y - height - 12;
      tooltipNode.style.left = left + "px";
      tooltipNode.style.top = top + "px";
    },
    /** Hide the tooltip. */
    hide: function () {
      if (tooltipNode) {
        tooltipNode.hidden = true;
      }
    },
  };

  /**
   * Attach hover, focus and click behaviour to a d3 selection of hit targets.
   *
   * @param {d3.Selection} selection - Elements acting as hit areas.
   * @param {Object} options - { content(d): tooltip content, onClick(d),
   *   label(d): accessible name, highlight(d, on): optional hover callback }.
   */
  CX.interact = function (selection, options) {
    selection
      .attr("tabindex", 0)
      .attr("role", options.onClick ? "link" : "img")
      .attr("aria-label", options.label || null)
      .classed("is-clickable", Boolean(options.onClick))
      .on("pointerenter focus", function (event, d) {
        if (options.highlight) {
          options.highlight(d, true, this);
        }
        CX.tooltip.show(event, options.content(d));
      })
      .on("pointermove", function (event) {
        CX.tooltip.move(event);
      })
      .on("pointerleave blur", function (event, d) {
        if (options.highlight) {
          options.highlight(d, false, this);
        }
        CX.tooltip.hide();
      });
    if (options.onClick) {
      selection
        .on("click", function (event, d) {
          options.onClick(d, event);
        })
        .on("keydown", function (event, d) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            options.onClick(d, event);
          }
        });
    }
  };

  // ---- Chart cards -------------------------------------------------------

  /**
   * Wrap a chart-card <figure> rendered by the chart_card template macro.
   *
   * @param {string} id - Element id of the figure.
   * @returns {Object|null} Card controller, or null if the id is absent:
   *   body: element charts draw into;
   *   status(message): replace the body with a status line;
   *   clear(): empty the body and return it;
   *   setTable(columns, rows): provide the data twin shown by "View data",
   *     where columns are { label, key, format } and rows are objects;
   *   subtitle(text) / title(text): update the card's subtitle or heading.
   */
  CX.card = function (id) {
    const figure = document.getElementById(id);
    if (!figure) {
      return null;
    }
    const body = figure.querySelector(".chart-body");
    const tableHost = figure.querySelector(".chart-table");
    const toggle = figure.querySelector(".chart-table-toggle");

    if (toggle && !toggle.dataset.bound) {
      toggle.dataset.bound = "1";
      toggle.addEventListener("click", function () {
        const showing = toggle.getAttribute("aria-pressed") === "true";
        toggle.setAttribute("aria-pressed", String(!showing));
        toggle.textContent = showing ? "View data" : "View chart";
        tableHost.hidden = showing;
        body.hidden = !showing;
      });
    }

    return {
      figure: figure,
      body: body,
      status: function (message) {
        body.replaceChildren(CX.el("p", { class: "chart-status", text: message }));
      },
      clear: function () {
        body.replaceChildren();
        return body;
      },
      subtitle: function (text) {
        const node = figure.querySelector(".chart-subtitle");
        if (node) {
          node.textContent = text;
        }
      },
      title: function (text) {
        // The heading may also hold a help bubble, so only swap its text node.
        const node = figure.querySelector(".chart-title");
        if (node && node.firstChild) {
          node.firstChild.textContent = text + " ";
        }
      },
      setTable: function (columns, rows) {
        if (!tableHost) {
          return;
        }
        const head = CX.el("tr", {}, columns.map(function (column) {
          return CX.el("th", { text: column.label, class: column.numeric ? "numeric" : null });
        }));
        const bodyRows = rows.map(function (row) {
          return CX.el("tr", {}, columns.map(function (column) {
            const raw = row[column.key];
            const text = raw === null || raw === undefined ? "" : column.format ? column.format(raw) : raw;
            return CX.el("td", { text: text, class: column.numeric ? "numeric" : null });
          }));
        });
        tableHost.replaceChildren(
          CX.el("table", { class: "table table-sm data-table" }, [
            CX.el("thead", {}, [head]),
            CX.el("tbody", {}, bodyRows),
          ])
        );
        if (toggle) {
          toggle.hidden = false;
        }
      },
    };
  };

  /**
   * Render a legend as a list of swatches (or gradient ramps) with labels.
   *
   * @param {Array<Object>} items - { label, color } or { label, ramp: [css
   *   colors] } entries.
   * @returns {HTMLElement} The <ul> legend element.
   */
  CX.legend = function (items) {
    return CX.el("ul", { class: "chart-legend" }, items.map(function (item) {
      const swatch = CX.el("span", { class: item.ramp ? "legend-ramp" : "legend-swatch" });
      swatch.style.background = item.ramp
        ? "linear-gradient(to right, " + item.ramp.join(", ") + ")"
        : item.color;
      return CX.el("li", {}, [swatch, CX.el("span", { text: item.label })]);
    }));
  };

  /**
   * Set the value (and optional note) of a stat tile.
   *
   * @param {string} id - Tile element id.
   * @param {string} value - Headline value.
   * @param {string} [note] - Supporting line under the value.
   */
  CX.setStat = function (id, value, note) {
    const tile = document.getElementById(id);
    if (!tile) {
      return;
    }
    tile.querySelector(".stat-value").textContent = value;
    const noteNode = tile.querySelector(".stat-note");
    if (noteNode) {
      noteNode.textContent = note || "";
    }
  };

  /** URL builders for pages (the URL map itself is injected by the template). */
  CX.link = {
    /**
     * @param {string} name - Species name.
     * @returns {string} URL of that species' page.
     */
    species: function (name) {
      return CX.urls.species.replace("__NAME__", encodeURIComponent(name));
    },
    /**
     * @param {string} a - Species A name.
     * @param {string} b - Species B name.
     * @returns {string} URL of the comparison page for the pair.
     */
    compare: function (a, b) {
      return CX.url(CX.urls.compare, { a: a, b: b });
    },
    /**
     * @param {string} template - URL containing the __NAME__ placeholder.
     * @param {string} name - Species name.
     * @param {Object} [params] - Query parameters.
     * @returns {string} API URL for the species.
     */
    api: function (template, name, params) {
      return CX.url(template.replace("__NAME__", encodeURIComponent(name)), params);
    },
  };

  /**
   * Generic sortable table with a "Show more" control.
   *
   * @param {HTMLElement} host - Element that will contain the table.
   * @param {Array<Object>} columns - { key, label, numeric, className,
   *   format(value, row), render(row): Node, sortable (default true) }.
   * @param {Array<Object>} rows - Row objects.
   * @param {Object} [options] - pageSize (0 shows every row); emptyMessage.
   */
  CX.dataTable = function (host, columns, rows, options) {
    const opts = Object.assign({ pageSize: 15 }, options);
    const data = rows.slice();
    let visible = opts.pageSize || data.length;
    let sortKey = null;
    let direction = -1;

    /** Rebuild the table for the current sort order and page. */
    function render() {
      if (!data.length) {
        host.replaceChildren(
          CX.el("p", { class: "chart-status", text: opts.emptyMessage || "Nothing to show." })
        );
        return;
      }
      const head = columns.map(function (column) {
        const sortable = column.sortable !== false;
        const th = CX.el("th", {
          text: column.label,
          class: [column.numeric ? "numeric" : "", column.className || ""].join(" ").trim() || null,
          title: column.title || null,
          "data-sort": sortable ? column.key : null,
          "aria-sort": sortKey === column.key ? (direction > 0 ? "ascending" : "descending") : null,
          tabindex: sortable ? 0 : null,
        });
        if (sortable) {
          // Sort by this column; a second activation reverses the order.
          const sort = function () {
            direction = sortKey === column.key ? -direction : (column.numeric ? -1 : 1);
            sortKey = column.key;
            data.sort(function (a, b) {
              const av = a[sortKey];
              const bv = b[sortKey];
              if (av === bv) {
                return 0;
              }
              if (av === null || av === undefined) {
                return 1;
              }
              if (bv === null || bv === undefined) {
                return -1;
              }
              return (av > bv ? 1 : -1) * direction;
            });
            render();
          };
          th.addEventListener("click", sort);
          th.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
              sort();
            }
          });
        }
        return th;
      });
      const shown = data.slice(0, visible);
      const body = shown.map(function (row) {
        return CX.el("tr", {}, columns.map(function (column) {
          if (column.render) {
            return CX.el("td", { class: column.numeric ? "numeric" : null }, [column.render(row)]);
          }
          const raw = row[column.key];
          const text = raw === null || raw === undefined ? "—" : column.format ? column.format(raw, row) : raw;
          return CX.el("td", { text: text, class: column.numeric ? "numeric" : null });
        }));
      });
      const nodes = [
        CX.el("table", { class: "table table-sm data-table" }, [
          CX.el("thead", {}, [CX.el("tr", {}, head)]),
          CX.el("tbody", {}, body),
        ]),
      ];
      if (visible < data.length) {
        const more = CX.el("button", {
          type: "button", class: "btn btn-outline-secondary btn-sm", text: "Show more",
        });
        more.addEventListener("click", function () {
          visible += opts.pageSize;
          render();
        });
        nodes.push(CX.el("footer", { class: "table-footer" }, [
          CX.el("span", { text: "Showing " + CX.fmt.int(shown.length) + " of " + CX.fmt.int(data.length) }),
          more,
        ]));
      }
      host.replaceChildren.apply(host, nodes);
    }

    render();
  };

  /**
   * Populate a <details> element with checkboxes for the reference species.
   *
   * Copy-number comparisons are made against "all other species"; this lets
   * the reader leave some out (for example a second annotation of the same
   * species, which would otherwise mask a lineage-specific family).
   *
   * @param {HTMLElement} details - The <details> element to fill.
   * @param {Array<Object>} species - { name, label } entries to offer.
   * @param {Function} onChange - Called with the array of excluded names.
   */
  CX.referencePicker = function (details, species, onChange) {
    if (!details) {
      return;
    }
    const summary = CX.el("summary", {});
    const list = CX.el("fieldset", { class: "reference-list" });
    const boxes = species.map(function (entry) {
      const box = CX.el("input", { type: "checkbox", value: entry.name, checked: true });
      list.appendChild(CX.el("label", {}, [box, CX.el("span", { class: "species-name", text: entry.label })]));
      return box;
    });
    /** Refresh the summary line and report the current exclusions. */
    function update(notify) {
      const excluded = boxes.filter(function (box) { return !box.checked; })
        .map(function (box) { return box.value; });
      summary.textContent = "Reference set: " + (boxes.length - excluded.length) + " of " +
        boxes.length + " other species";
      if (notify) {
        onChange(excluded);
      }
    }
    list.addEventListener("change", function () { update(true); });
    details.replaceChildren(summary, list);
    update(false);
  };

  const resizeCallbacks = [];
  let resizeTimer = null;
  /**
   * Register a callback to re-render charts after the window is resized.
   * @param {Function} callback
   */
  CX.onResize = function (callback) {
    resizeCallbacks.push(callback);
  };
  global.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      resizeCallbacks.forEach(function (callback) {
        callback();
      });
    }, 150);
  });

  /**
   * Wire a group of toggle buttons so exactly one is pressed.
   *
   * @param {HTMLElement} group - Container whose buttons carry data-value.
   * @param {Function} onChange - Called with the selected data-value.
   * @param {string} [attribute="aria-pressed"] - State attribute to manage.
   */
  CX.bindChoice = function (group, onChange, attribute) {
    const state = attribute || "aria-pressed";
    if (!group) {
      return;
    }
    group.querySelectorAll("button[data-value]").forEach(function (button) {
      button.addEventListener("click", function () {
        group.querySelectorAll("button[data-value]").forEach(function (other) {
          other.setAttribute(state, String(other === button));
        });
        onChange(button.dataset.value);
      });
    });
  };
})(window);
