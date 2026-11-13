/* SciLEx Dashboard: cross-filtered charts and citation network of a review.
 *
 * Needs d3 (v7) and crossfilter (crossfilter2). Every chart is a crossfilter
 * dimension: brushing the years, clicking a bar or a legend value, or
 * restricting to a paper's neighbourhood filters every other view. Clicking a
 * paper (network node, list row) emits `scilex_dashboard_paper` with its key;
 * each change of the filters emits `scilex_dashboard_filtered` with the keys
 * left, in list order. Python draws the paper notice.
 */
(function () {
  "use strict";

  const PALETTE = ["#4269d0", "#efb118", "#ff725c", "#6cc5b0", "#3ca951",
    "#ff8ab7", "#a463f2", "#97bbf5", "#9c6b4e", "#9498a0"];
  const OTHER = "#c8c8c8";
  const CITATION_BANDS = ["0", "1", "2–4", "5–9", "10–24", "25–49", "50–99",
    "100–249", "250–999", "1000+", "unknown"];
  const BAR_ROWS = 12;

  function band(c) {
    if (c === null || c === undefined) return "unknown";
    const limits = [0, 1, 4, 9, 24, 49, 99, 249, 999];
    for (let i = 0; i < limits.length; i++) if (c <= limits[i]) return CITATION_BANDS[i];
    return "1000+";
  }

  function el(tag, cls, parent, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  function emit(name, payload) {
    if (typeof window.emitEvent === "function") window.emitEvent(name, payload);
  }

  function mount(rootId, data) {
    const root = document.getElementById(rootId);
    if (!root || !window.d3 || !window.crossfilter) {
      if (root) root.textContent = "The charts library could not be loaded (offline?).";
      return;
    }
    const d3 = window.d3;
    root.innerHTML = "";
    root.classList.add("sx-dash");
    const papers = data.papers;
    papers.forEach((p, i) => { p.i = i; p.band = band(p.citations); });
    const cf = window.crossfilter(papers);
    const all = cf.groupAll();
    const views = [];        // {redraw()}
    const filters = {};      // name -> {label, clear()}
    let selected = null;     // key of the paper shown in the notice
    let neighbourhood = null;

    // -- layout -----------------------------------------------------------
    const stats = el("div", "sx-stats", root);
    const bar = el("div", "sx-bar", root);
    const quick = el("div", "sx-quick", root);
    const chips = el("div", "sx-chips", bar);
    const reset = el("button", "sx-reset", bar, "Reset all filters");
    reset.onclick = () => { Object.values(filters).forEach((f) => f.clear()); update(); };
    const tabs = el("div", "sx-tabs", root);
    const panes = {};
    ["Statistics", "Network", "Papers"].forEach((name, i) => {
      const button = el("button", "sx-tab" + (i === 0 ? " on" : ""), tabs, name);
      const pane = el("div", "sx-pane" + (i === 0 ? " on" : ""), root);
      panes[name] = pane;
      button.onclick = () => {
        tabs.querySelectorAll(".sx-tab").forEach((b) => b.classList.remove("on"));
        Object.values(panes).forEach((p) => p.classList.remove("on"));
        button.classList.add("on");
        pane.classList.add("on");
        if (name === "Network") network.start();
      };
    });
    const grid = el("div", "sx-grid", panes.Statistics);
    const tooltip = el("div", "sx-tip", root);

    function showTip(event, text) {
      tooltip.textContent = text;
      tooltip.style.display = "block";
      const box = root.getBoundingClientRect();
      tooltip.style.left = (event.clientX - box.left + 12) + "px";
      tooltip.style.top = (event.clientY - box.top + 12) + "px";
    }
    function hideTip() { tooltip.style.display = "none"; }

    // -- stats --------------------------------------------------------------
    function drawStats() {
      const shown = cf.allFiltered();
      const cites = shown.map((p) => p.citations).filter((c) => c !== null && c !== undefined).sort(d3.ascending);
      const years = shown.map((p) => p.year).filter((y) => y);
      const count = (facet, value) => shown.filter((p) => (p.f[facet] || []).includes(value)).length;
      const tiles = [
        ["Papers", `${shown.length} / ${papers.length}`],
        ["Meet the criteria", data.facets.eligibility ? count("eligibility", "Meets the criteria") : "–"],
        ["Included", count("decision", "Include")],
        ["Maybe", count("decision", "Maybe")],
        ["Median citations", cites.length ? d3.median(cites) : "–"],
        ["Years", years.length ? `${d3.min(years)}–${d3.max(years)}` : "–"],
        ["Links in the corpus", network.visibleLinks()],
      ];
      stats.innerHTML = "";
      tiles.forEach(([label, value]) => {
        const tile = el("div", "sx-tile", stats);
        el("div", "sx-value", tile, String(value));
        el("div", "sx-label", tile, label);
      });
      chips.innerHTML = "";
      Object.entries(filters).forEach(([name, f]) => {
        if (!f.active()) return;
        const chip = el("span", "sx-chip", chips, f.label() + " ✕");
        chip.title = "Remove this filter";
        chip.onclick = () => { f.clear(); update(); };
      });
      reset.style.visibility = chips.children.length ? "visible" : "hidden";
      drawQuick();
    }

    // -- quick filters: one click on the screening / validation state --------
    // Each sets the values chosen in a facet chart (shown as a chip as usual).
    const NONE = "(none)";
    const QUICK = [
      ["Included", "decision", () => ["Include"]],
      ["Maybe", "decision", () => ["Maybe"]],
      ["Included or maybe", "decision", () => ["Include", "Maybe"]],
      ["Undecided", "decision", () => ["Undecided"]],
      ["Validated (ANNOT_VALID_BY)", "validated_by",
        (values) => values.filter((v) => v !== NONE)],
      ["Not validated", "validated_by", () => [NONE]],
    ];
    function drawQuick() {
      quick.innerHTML = "";
      const shown = QUICK.filter(([, name]) => filters[name]);
      if (!shown.length) return;
      el("span", "sx-quick-label", quick, "Quick filters:");
      shown.forEach(([label, name, wanted]) => {
        const f = filters[name];
        const values = wanted(f.values());
        const on = f.active() && f.chosen().length === values.length
          && values.every((v) => f.chosen().includes(v));
        const button = el("button", "sx-quick-btn" + (on ? " on" : ""), quick, label);
        button.title = on ? "Remove this filter" : `${f.title}: ${values.join(" or ")}`;
        button.onclick = () => { f.set(on ? [] : values); update(); };
      });
    }

    // -- year histogram (brush) --------------------------------------------
    function yearChart() {
      const card = el("div", "sx-card sx-wide", grid);
      el("div", "sx-title", card, "Publication year (drag to select a range)");
      const dim = cf.dimension((p) => p.year || 0);
      const group = dim.group();
      const width = Math.max(320, (card.clientWidth || 660) - 20), height = 160, m = { l: 34, r: 8, t: 6, b: 20 };
      const svg = d3.select(card).append("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("class", "sx-svg");
      const years = papers.map((p) => p.year).filter((y) => y);
      if (!years.length) { el("div", "sx-empty", card, "No year known."); return; }
      const x = d3.scaleLinear().domain([d3.min(years), d3.max(years) + 1]).range([m.l, width - m.r]);
      const y = d3.scaleLinear().range([height - m.b, m.t]);
      const gx = svg.append("g").attr("transform", `translate(0,${height - m.b})`);
      const gy = svg.append("g").attr("transform", `translate(${m.l},0)`);
      const bars = svg.append("g");
      let range = null;
      const brush = d3.brushX().extent([[m.l, m.t], [width - m.r, height - m.b]])
        .on("end", (event) => {
          if (!event.sourceEvent) return;
          if (!event.selection) { range = null; dim.filterAll(); update(); return; }
          const [a, b] = event.selection.map(x.invert).map(Math.round);
          range = [a, Math.max(b, a + 1)];
          dim.filterRange(range);
          brushG.call(brush.move, range.map(x));
          update();
        });
      const brushG = svg.append("g").call(brush);
      gx.call(d3.axisBottom(x).ticks(8).tickFormat(d3.format("d")));
      filters.year = {
        active: () => range !== null,
        label: () => range ? `Years ${range[0]}–${range[1] - 1}` : "",
        clear: () => { range = null; dim.filterAll(); brushG.call(brush.move, null); },
      };
      views.push({
        redraw() {
          const values = group.all().filter((g) => g.key);
          y.domain([0, d3.max(values, (g) => g.value) || 1]).nice();
          gy.call(d3.axisLeft(y).ticks(4).tickFormat(d3.format("d")));
          const w = Math.max(1, x(1) - x(0) - 1);
          bars.selectAll("rect").data(values, (g) => g.key).join("rect")
            .attr("class", "sx-mark")
            .attr("x", (g) => x(g.key)).attr("width", w)
            .attr("y", (g) => y(g.value)).attr("height", (g) => y(0) - y(g.value))
            .on("mousemove", (e, g) => showTip(e, `${g.key}: ${g.value} papers`))
            .on("mouseleave", hideTip);
        },
      });
    }

    // -- ordinal / categorical bar charts (click to filter) -----------------
    function barChart(title, accessor, isArray, order, name) {
      const card = el("div", "sx-card", grid);
      const head = el("div", "sx-title", card, title);
      const dim = cf.dimension(accessor, isArray);
      const group = dim.group();
      const chosen = new Set();
      const body = el("div", "sx-bars", card);
      let expanded = false;
      const more = el("button", "sx-more", card, "Show all");
      more.onclick = () => { expanded = !expanded; more.textContent = expanded ? "Show fewer" : "Show all"; draw(); };
      function apply() {
        if (!chosen.size) dim.filterAll();
        else dim.filterFunction((v) => chosen.has(v));
      }
      filters[name] = {
        title,
        active: () => chosen.size > 0,
        label: () => `${title}: ${[...chosen].join(" or ")}`,
        clear: () => { chosen.clear(); apply(); },
        chosen: () => [...chosen],
        values: () => group.all().map((g) => g.key),
        set: (values) => { chosen.clear(); values.forEach((v) => chosen.add(v)); apply(); },
      };
      function draw() {
        let values = group.all().slice();
        if (order) values.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key));
        else values.sort((a, b) => b.value - a.value || String(a.key).localeCompare(String(b.key)));
        values = values.filter((g) => g.value > 0 || chosen.has(g.key));
        more.style.display = values.length > BAR_ROWS ? "inline-block" : "none";
        if (!expanded && !order) values = values.slice(0, BAR_ROWS);
        const max = d3.max(values, (g) => g.value) || 1;
        head.textContent = title + (chosen.size ? ` (${chosen.size} selected)` : "");
        const rows = d3.select(body).selectAll("div.sx-row").data(values, (g) => g.key)
          .join((enter) => {
            const row = enter.append("div").attr("class", "sx-row");
            row.append("span").attr("class", "sx-name");
            const track = row.append("span").attr("class", "sx-track");
            track.append("span").attr("class", "sx-fill");
            row.append("span").attr("class", "sx-count");
            return row;
          });
        rows.classed("on", (g) => chosen.has(g.key))
          .classed("off", (g) => chosen.size > 0 && !chosen.has(g.key))
          .attr("title", (g) => `${g.key}: ${g.value} papers — click to filter`)
          .on("click", (e, g) => {
            if (chosen.has(g.key)) chosen.delete(g.key); else chosen.add(g.key);
            apply(); update();
          });
        rows.select(".sx-name").text((g) => g.key);
        rows.select(".sx-fill").style("width", (g) => (100 * g.value / max) + "%");
        rows.select(".sx-count").text((g) => g.value);
        rows.order();
      }
      views.push({ redraw: draw });
    }

    // -- citation network (canvas, d3-force) --------------------------------
    const network = (function () {
      const pane = panes.Network;
      const controls = el("div", "sx-controls", pane);
      const colorSel = el("select", "", el("label", "", controls, "Colour "));
      const facetIds = Object.keys(data.facets);
      facetIds.forEach((f) => { const o = el("option", "", colorSel, data.facets[f]); o.value = f; });
      colorSel.value = facetIds.includes("paper_type") ? "paper_type" : facetIds[0] || "";
      const sizeSel = el("select", "", el("label", "", controls, " Size "));
      [["pagerank", "PageRank"], ["citations", "Citations"], ["in_corpus", "Citations from the corpus"]]
        .forEach(([v, t]) => { const o = el("option", "", sizeSel, t); o.value = v; });
      const hideBox = el("input", "", null); hideBox.type = "checkbox";
      const hideLabel = el("label", "", controls); hideLabel.appendChild(hideBox);
      hideLabel.appendChild(document.createTextNode(" Hide filtered-out papers"));
      const isolatedBox = el("input", "", null); isolatedBox.type = "checkbox";
      const isolatedLabel = el("label", "", controls); isolatedLabel.appendChild(isolatedBox);
      isolatedLabel.appendChild(document.createTextNode(" Show unlinked papers"));
      const neighbours = el("button", "sx-more", controls, "Keep this paper and its neighbours");
      neighbours.disabled = true;
      const legend = el("div", "sx-legend", pane);
      const canvas = el("canvas", "sx-canvas", pane);
      const help = el("div", "sx-help", pane,
        "Links: citations between corpus papers (Enrich › Citations). Scroll to zoom, drag to pan, click a paper to read its notice.");
      if (!data.links.length) help.textContent = "No citation link between corpus papers yet: run Enrich › Citations.";

      const degree = new Array(papers.length).fill(0);
      data.links.forEach(([a, b]) => { degree[a]++; degree[b]++; });
      const adjacency = papers.map(() => new Set());
      data.links.forEach(([a, b]) => { adjacency[a].add(b); adjacency[b].add(a); });
      let nodes = [], links = [], simulation = null, transform = d3.zoomIdentity;
      let started = false, colorOf = () => OTHER, radiusOf = () => 4;
      const keyDim = cf.dimension((p) => p.key);
      filters.neighbourhood = {
        active: () => neighbourhood !== null,
        label: () => "Neighbours of a paper",
        clear: () => { neighbourhood = null; keyDim.filterAll(); },
      };
      neighbours.onclick = () => {
        if (!selected) return;
        const i = papers.findIndex((p) => p.key === selected);
        neighbourhood = new Set([selected, ...[...adjacency[i]].map((j) => papers[j].key)]);
        keyDim.filterFunction((k) => neighbourhood.has(k));
        update();
      };

      function build() {
        const keep = papers.filter((p) => isolatedBox.checked || degree[p.i] > 0);
        const index = new Map(keep.map((p) => [p.i, { p, x: undefined, y: undefined }]));
        nodes = [...index.values()];
        links = data.links.filter(([a, b]) => index.has(a) && index.has(b))
          .map(([a, b]) => ({ source: index.get(a), target: index.get(b) }));
        if (simulation) simulation.stop();
        simulation = d3.forceSimulation(nodes)
          .force("link", d3.forceLink(links).distance(30).strength(0.4))
          .force("charge", d3.forceManyBody().strength(-25).distanceMax(300))
          .force("x", d3.forceX().strength(0.04))
          .force("y", d3.forceY().strength(0.04))
          .force("collide", d3.forceCollide((n) => radiusOf(n.p) + 1))
          .on("tick", draw);
      }
      function scales() {
        const facet = colorSel.value;
        const counts = d3.rollup(papers, (v) => v.length, (p) => (p.f[facet] || [])[0] || "(none)");
        const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, PALETTE.length).map((e) => e[0]);
        const color = new Map(top.map((v, i) => [v, PALETTE[i]]));
        colorOf = (p) => color.get((p.f[facet] || [])[0] || "(none)") || OTHER;
        legend.innerHTML = "";
        top.forEach((v) => {
          const item = el("span", "sx-key", legend);
          const dot = el("span", "sx-dot", item); dot.style.background = color.get(v);
          item.appendChild(document.createTextNode(v));
        });
        const metric = sizeSel.value;
        const max = d3.max(papers, (p) => p[metric] || 0) || 1;
        const r = d3.scaleSqrt().domain([0, max]).range([3, 14]);
        radiusOf = (p) => r(p[metric] || 0);
      }
      function resize() {
        const ratio = window.devicePixelRatio || 1;
        const width = pane.clientWidth || 800, height = Math.max(420, Math.round(window.innerHeight * 0.62));
        canvas.width = width * ratio; canvas.height = height * ratio;
        canvas.style.width = width + "px"; canvas.style.height = height + "px";
      }
      function draw() {
        if (!started) return;
        const ctx = canvas.getContext("2d");
        const ratio = window.devicePixelRatio || 1;
        const w = canvas.width / ratio, h = canvas.height / ratio;
        ctx.save();
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, w, h);
        ctx.translate(w / 2 + transform.x, h / 2 + transform.y);
        ctx.scale(transform.k, transform.k);
        const shown = new Set(cf.allFiltered().map((p) => p.i));
        const hide = hideBox.checked;
        const sel = selected ? papers.findIndex((p) => p.key === selected) : -1;
        ctx.lineWidth = 0.6 / transform.k;
        links.forEach((l) => {
          const on = shown.has(l.source.p.i) && shown.has(l.target.p.i);
          if (hide && !on) return;
          const touch = l.source.p.i === sel || l.target.p.i === sel;
          ctx.strokeStyle = touch ? "rgba(255,114,92,0.9)" : on ? "rgba(120,120,140,0.35)" : "rgba(160,160,160,0.08)";
          ctx.beginPath(); ctx.moveTo(l.source.x, l.source.y); ctx.lineTo(l.target.x, l.target.y); ctx.stroke();
        });
        nodes.forEach((n) => {
          const on = shown.has(n.p.i);
          if (hide && !on) return;
          ctx.globalAlpha = on ? 1 : 0.12;
          ctx.fillStyle = colorOf(n.p);
          ctx.beginPath(); ctx.arc(n.x, n.y, radiusOf(n.p), 0, 2 * Math.PI); ctx.fill();
          if (n.p.i === sel) {
            ctx.lineWidth = 2.5 / transform.k; ctx.strokeStyle = "#111";
            ctx.stroke(); ctx.lineWidth = 0.6 / transform.k;
          }
        });
        ctx.globalAlpha = 1;
        ctx.restore();
      }
      function find(event) {
        const ratio = 1;
        const rect = canvas.getBoundingClientRect();
        const w = rect.width, h = rect.height;
        const x = (event.clientX - rect.left - w / 2 - transform.x) / transform.k / ratio;
        const y = (event.clientY - rect.top - h / 2 - transform.y) / transform.k / ratio;
        let best = null, dist = Infinity;
        nodes.forEach((n) => {
          const d = Math.hypot(n.x - x, n.y - y);
          if (d < radiusOf(n.p) + 3 / transform.k && d < dist) { best = n; dist = d; }
        });
        return best;
      }
      d3.select(canvas)
        .call(d3.zoom().scaleExtent([0.1, 8]).on("zoom", (e) => { transform = e.transform; draw(); }))
        .on("mousemove", (e) => {
          const n = find(e);
          canvas.style.cursor = n ? "pointer" : "grab";
          if (n) showTip(e, `${n.p.title} (${n.p.year || "?"}) — ${degree[n.p.i]} links`); else hideTip();
        })
        .on("mouseleave", hideTip)
        .on("click", (e) => { const n = find(e); if (n) select(n.p.key); });
      [colorSel, sizeSel].forEach((s) => s.addEventListener("change", () => { scales(); build(); draw(); }));
      hideBox.addEventListener("change", draw);
      isolatedBox.addEventListener("change", () => { build(); });
      return {
        start() {
          if (started) { resize(); draw(); return; }
          started = true; resize(); scales(); build();
        },
        redraw() { neighbours.disabled = !selected; draw(); },
        visibleLinks() {
          const shown = new Set(cf.allFiltered().map((p) => p.i));
          return data.links.filter(([a, b]) => shown.has(a) && shown.has(b)).length;
        },
      };
    })();
    views.push(network);

    // -- paper list ---------------------------------------------------------
    const list = (function () {
      const pane = panes.Papers;
      const controls = el("div", "sx-controls", pane);
      const sortSel = el("select", "", el("label", "", controls, "Sort by "));
      [["relevance", "Relevance"], ["citations", "Citations"], ["pagerank", "PageRank"],
        ["in_corpus", "Citations from the corpus"], ["year", "Year"]]
        .forEach(([v, t]) => { const o = el("option", "", sortSel, t); o.value = v; });
      const table = el("div", "sx-list", pane);
      sortSel.addEventListener("change", () => draw());
      function ordered() {
        const key = sortSel.value;
        return cf.allFiltered().slice().sort((a, b) => (b[key] ?? -1) - (a[key] ?? -1));
      }
      function draw() {
        const rows = ordered();
        table.innerHTML = "";
        rows.slice(0, 300).forEach((p) => {
          const row = el("div", "sx-paper" + (p.key === selected ? " on" : ""), table);
          el("span", "sx-ptitle", row, p.title);
          const fails = Object.keys(p.fails || {});
          el("span", "sx-pmeta", row, [p.year || "", (p.f.paper_type || [])[0] || "",
            p.citations !== null && p.citations !== undefined ? `${p.citations} cit.` : "",
            fails.length ? `fails ${fails.join(", ")}` : ""].filter(Boolean).join(" · "));
          row.title = fails.map((c) => `${c}: ${p.fails[c]}`).join("\n");
          row.onclick = () => select(p.key);
        });
        if (rows.length > 300) el("div", "sx-help", table, `… and ${rows.length - 300} more (narrow the filters).`);
        return rows;
      }
      return { redraw: draw, ordered };
    })();
    views.push(list);

    // -- charts of the facets -----------------------------------------------
    yearChart();
    barChart("Citations", (p) => p.band, false, CITATION_BANDS, "citations");
    Object.entries(data.facets).forEach(([facet, label]) => {
      barChart(label, (p) => (p.f[facet] && p.f[facet].length ? p.f[facet] : ["(none)"]), true, null, facet);
    });
    if (Object.keys(data.criteria || {}).length) {
      barChart("Criteria not met", (p) => {
        const ids = Object.keys(p.fails || {});
        return ids.length ? ids.map((c) => `${c} – ${data.criteria[c] || ""}`) : ["(all met)"];
      }, true, null, "criteria");
    }

    let timer = null;
    function update() {
      views.forEach((v) => v.redraw());
      drawStats();
      clearTimeout(timer);
      timer = setTimeout(() => emit("scilex_dashboard_filtered", { keys: list.ordered().map((p) => p.key) }), 150);
    }
    function select(key) {
      selected = key;
      emit("scilex_dashboard_paper", { key });
      network.redraw();
      list.redraw();
    }
    root.sxSelect = (key) => { selected = key; network.redraw(); list.redraw(); };
    update();
  }

  window.SciLExDashboard = { mount };
})();
