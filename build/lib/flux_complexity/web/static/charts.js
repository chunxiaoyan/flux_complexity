// Grouped column chart: share of flux positions for each value k, this corpus vs a
// reference norm. Plain SVG, no library. Text only via textContent.
// Colours: validated categorical pair (blue = corpus, orange = norm), see review_stage7.md.
"use strict";

const CHART = { w: 480, h: 230, left: 44, right: 10, top: 12, bottom: 34, gap: 2, radius: 4 };
const CHART_TAIL = 12; // values >= 12 are grouped in one last column « ≥ 12 », as in the tables

// counts: {k: n}. Returns [{label, k, n, share, tail}] folded at CHART_TAIL.
function foldDistribution(counts, upTo, maxK) {
  const total = Object.values(counts).reduce((a, n) => a + Number(n), 0) || 1;
  const rows = [];
  let above = total;
  for (let k = 1; k <= upTo; k++) {
    const last = k === CHART_TAIL && maxK > CHART_TAIL;
    let n = 0;
    for (const [key, v] of Object.entries(counts)) {
      const kk = Number(key);
      if (last ? kk >= k : kk === k) n += Number(v);
    }
    rows.push({ label: last ? `≥ ${k}` : String(k), k, n, share: n / total, tail: above / total });
    above -= n;
    if (last) break;
  }
  return rows;
}

function niceStep(max) {
  for (const s of [0.01, 0.02, 0.05, 0.1, 0.2, 0.25]) if (max / s <= 5) return s;
  return 0.25;
}

function roundedTop(x, y, w, h, r) {
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`;
}

// series: [{name, counts, cls}] (2 series); onEnter(column index, rows per series, element) / onLeave()
function columnChart(container, series, { onEnter, onLeave } = {}) {
  container.textContent = "";
  const maxK = Math.max(...series.map((s) => Math.max(0, ...Object.keys(s.counts).map(Number))));
  const upTo = Math.min(maxK, CHART_TAIL);
  const data = series.map((s) => foldDistribution(s.counts, upTo, maxK));
  const ymax = Math.max(0.0001, ...data.flat().map((r) => r.share));
  const step = niceStep(ymax);
  const top = Math.ceil(ymax / step) * step;
  const plotW = CHART.w - CHART.left - CHART.right, plotH = CHART.h - CHART.top - CHART.bottom;
  const y = (v) => CHART.top + plotH * (1 - v / top);
  const groupW = plotW / data[0].length;
  const barW = Math.min(18, (groupW * 0.72 - CHART.gap) / 2);

  const root = svg("svg", { class: "chart-svg", viewBox: `0 0 ${CHART.w} ${CHART.h}`, role: "img",
    "aria-label": series.map((s) => s.name).join(" et ") });
  // recessive grid + y axis labels
  for (let v = 0; v <= top + 1e-9; v += step) {
    root.append(svg("line", { class: "grid" + (v === 0 ? " baseline" : ""), x1: CHART.left, x2: CHART.w - CHART.right, y1: y(v), y2: y(v) }));
    root.append(svg("text", { class: "axis", x: CHART.left - 6, y: y(v) + 3.5, "text-anchor": "end" },
      `${Math.round(v * 100)} %`));
  }
  data[0].forEach((row, i) => {
    const cx = CHART.left + groupW * (i + 0.5);
    const x0 = cx - barW - CHART.gap / 2;
    series.forEach((s, j) => {
      const r = data[j][i];
      const h = Math.max(0, y(0) - y(r.share));
      if (h > 0) root.append(svg("path", { class: "bar " + s.cls, d: roundedTop(x0 + j * (barW + CHART.gap), y(r.share), barW, h, CHART.radius) }));
    });
    root.append(svg("text", { class: "axis", x: cx, y: CHART.h - CHART.bottom + 15, "text-anchor": "middle" }, row.label));
    // hit target: the whole column, larger than the bars
    const hit = svg("rect", { class: "hit", x: cx - groupW / 2, y: CHART.top, width: groupW, height: plotH, tabindex: 0,
      "aria-label": `k = ${row.label} : ` + series.map((s, j) => `${s.name} ${(data[j][i].share * 100).toFixed(2)} %`).join(", ") });
    const show = () => { hit.classList.add("active"); if (onEnter) onEnter(i, data, hit); };
    const hide = () => { hit.classList.remove("active"); if (onLeave) onLeave(); };
    hit.addEventListener("mouseenter", show);
    hit.addEventListener("mouseleave", hide);
    hit.addEventListener("focus", show);
    hit.addEventListener("blur", hide);
    root.append(hit);
  });
  root.append(svg("text", { class: "axis axis-title", x: CHART.left + plotW / 2, y: CHART.h - 3, "text-anchor": "middle" }, "valeur k"));
  container.append(root);
  return root;
}
