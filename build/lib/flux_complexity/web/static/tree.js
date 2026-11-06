// Dependency tree drawing shared by the two pages (vanilla JS, no build step).
// Text is only inserted with textContent, never parsed as HTML.
"use strict";

// Dependency tree in the style of brat / conllu.js (UPOS box over each word, flat-topped
// arcs stacked by span, label on the arc, arrow to the dependent), drawn with our own SVG.
const SVGNS = "http://www.w3.org/2000/svg";
const T = { pad: 8, wordGap: 12, slot: 16, levelH: 18, arcTop: 12, posH: 16, wordH: 26, mwtH: 16, radius: 5 };
const WORD_FONT = "16px system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const SMALL_FONT = "10px system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
const measureCtx = document.createElement("canvas").getContext("2d");

function textWidth(text, font) {
  measureCtx.font = font;
  return measureCtx.measureText(text).width;
}
function svg(tag, attrs, text) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  if (text !== undefined) e.textContent = text;
  return e;
}

// brat-like stacking: an arc sits one level above every arc nested inside its span
function arcLevels(arcs) {
  const sorted = [...arcs].sort((a, b) => (a.r - a.l) - (b.r - b.l));
  sorted.forEach((a, k) => {
    a.level = 1;
    for (const b of sorted.slice(0, k)) {
      if (b.l >= a.l && b.r <= a.r && b.r - b.l < a.r - a.l) a.level = Math.max(a.level, b.level + 1);
    }
  });
  return Math.max(0, ...arcs.map((a) => a.level));
}

// s: a sentence of the analysis API (words, tokens, positions); m: "weight" or "size".
// hooks (all optional): onEnter(p, el), onLeave(p, el), onClick(p, el), marked: Set of
// positions to outline. Returns the <svg>; svg.gapEls maps position -> its <rect>.
function drawTree(s, m, hooks = {}) {
  const words = s.words;
  const byId = new Map(words.map((w, i) => [w.id, i]));
  const gapAfter = new Map(s.positions.map((p) => [p.left_id, p]));

  // arcs, stacked by span (brat style)
  const arcs = words.filter((w) => w.head > 0 && byId.has(w.head)).map((w) => {
    const g = byId.get(w.head), d = byId.get(w.id);
    return { gov: w.head, dep: w.id, rel: w.deprel, status: w.status, g, d, l: Math.min(g, d), r: Math.max(g, d),
      lw: textWidth(w.deprel, SMALL_FONT) + 6 };
  });
  const maxLevel = arcLevels(arcs);
  const ends = new Map();
  for (const a of arcs) {
    for (const [idx, other] of [[a.g, a.d], [a.d, a.g]]) {
      if (!ends.has(idx)) ends.set(idx, []);
      ends.get(idx).push({ a, toRight: other > idx, len: Math.abs(other - idx), isDep: idx === a.d });
    }
  }

  // horizontal layout: a flux position gets a coloured slot between its two words; the
  // space after a word grows when the label of an arc starting there does not fit
  const ws = words.map((w) => Math.max(textWidth(w.form, WORD_FONT), textWidth(w.upos, SMALL_FONT) + 8) + 6);
  const extra = words.map(() => 0);
  let xs, slots, width;
  for (let pass = 0; pass < 4; pass++) {
    xs = []; slots = [];
    let x = T.pad;
    words.forEach((w, i) => {
      xs.push(x);
      x += ws[i];
      if (i === words.length - 1) return;
      const p = gapAfter.get(w.id);
      const gap = (p ? T.slot : T.wordGap) + extra[i];
      if (p) slots.push({ p, x: x + (gap - 10) / 2 });
      x += gap;
    });
    width = Math.ceil(x + T.pad);
    // endpoints spread over the word: the longest arcs nearest its middle, so that a
    // short arc never crosses the vertical line of a longer one
    for (const [idx, list] of ends) {
      const center = xs[idx] + ws[idx] / 2;
      const left = list.filter((e) => !e.toRight).sort((p, q) => q.len - p.len);
      const right = list.filter((e) => e.toRight).sort((p, q) => q.len - p.len);
      const step = Math.min(6, (ws[idx] / 2 - 2) / Math.max(1, left.length, right.length));
      left.forEach((e, k) => { e.x = center - step * (k + 0.5); });
      right.forEach((e, k) => { e.x = center + step * (k + 0.5); });
      for (const e of list) e.a[e.isDep ? "xd" : "xg"] = e.x;
    }
    let changed = false;
    for (const a of arcs) {
      const deficit = a.lw + 2 * T.radius + 4 - Math.abs(a.xd - a.xg);
      if (deficit > 0.5) { extra[a.l] += deficit; changed = true; }
    }
    if (!changed) break;
  }

  const posY = T.arcTop + maxLevel * T.levelH + 8;
  const wordY = posY + T.posH + 2;
  const mwts = s.tokens.filter((t) => t.first_id !== t.last_id);
  const height = wordY + T.wordH + (mwts.length ? T.mwtH : 0) + 4;
  const root = svg("svg", { class: "tree", width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": "Arbre de dépendances : " + s.text });

  const hlRects = words.map((w, i) => {
    const r = svg("rect", { class: "word-hl", x: xs[i] - 3, y: posY - 3, width: ws[i] + 6,
      height: T.posH + T.wordH + 6, rx: 5 });
    root.append(r);
    return r;
  });

  const arcLayer = svg("g", { class: "arcs" });
  root.append(arcLayer);
  for (const a of arcs) {
    const y = posY - 1, top = posY - 4 - a.level * T.levelH;
    const [x1, x2] = a.xg < a.xd ? [a.xg, a.xd] : [a.xd, a.xg];
    const r = Math.min(T.radius, (x2 - x1) / 2);
    const g = svg("g", { class: "arc " + a.status });
    g.append(svg("path", { class: "line",
      d: `M${x1},${y} V${top + r} Q${x1},${top} ${x1 + r},${top} H${x2 - r} Q${x2},${top} ${x2},${top + r} V${y}` }));
    g.append(svg("path", { class: "head", d: `M${a.xd - 3.5},${y - 6} L${a.xd + 3.5},${y - 6} L${a.xd},${y} Z` }));
    const lw = a.lw, mid = (x1 + x2) / 2;
    g.append(svg("rect", { class: "label-bg", x: mid - lw / 2, y: top - 6, width: lw, height: 12, rx: 2 }));
    g.append(svg("text", { class: "label", x: mid, y: top + 3.5, "text-anchor": "middle" }, a.rel));
    a.el = g;
    arcLayer.append(g);
  }

  words.forEach((w, i) => {
    const punct = w.upos === "PUNCT" ? " punct" : "";
    const cx = xs[i] + ws[i] / 2;
    root.append(svg("rect", { class: "pos" + punct, x: xs[i], y: posY, width: ws[i], height: T.posH, rx: 3 }));
    root.append(svg("text", { class: "pos-label", x: cx, y: posY + 11.5, "text-anchor": "middle" }, w.upos));
    root.append(svg("text", { class: "word" + punct, x: cx, y: wordY + 18, "text-anchor": "middle" }, w.form));
  });

  // multi-word tokens (« au » = à + le): bracket with the written form under the words
  for (const t of mwts) {
    const a = byId.get(t.first_id), b = byId.get(t.last_id);
    const x1 = xs[a] + 2, x2 = xs[b] + ws[b] - 2, y = wordY + T.wordH;
    root.append(svg("path", { class: "mwt", d: `M${x1},${y - 3} V${y} H${x2} V${y - 3}` }));
    root.append(svg("text", { class: "mwt-label", x: (x1 + x2) / 2, y: y + 12, "text-anchor": "middle" }, t.form));
  }

  const view = { root, arcs, hlRects, byId };
  const gapEls = new Map();
  root.gapEls = gapEls;
  for (const { p, x: sx } of slots) {
    const left = words[byId.get(p.left_id)].form, right = words[byId.get(p.right_id)].form;
    const g = svg("rect", { class: `gap l${p[m + "_level"]}`, x: sx, y: wordY + 2, width: 10, height: T.wordH - 2,
      rx: 3, tabindex: 0, "aria-label": `Entre « ${left} » et « ${right} » : poids ${p.weight}, taille ${p.size}` });
    if (hooks.marked && hooks.marked.has(p.position)) g.classList.add("marked");
    const show = () => { g.classList.add("active"); highlight(view, p, true); if (hooks.onEnter) hooks.onEnter(p, g); };
    const hide = () => { g.classList.remove("active"); highlight(view, p, false); if (hooks.onLeave) hooks.onLeave(p, g); };
    g.addEventListener("mouseenter", show);
    g.addEventListener("mouseleave", hide);
    g.addEventListener("focus", show);
    g.addEventListener("blur", hide);
    if (hooks.onClick) {
      g.addEventListener("click", () => hooks.onClick(p, g));
      g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); hooks.onClick(p, g); } });
    }
    gapEls.set(p.position, g);
    root.append(g);
  }
  return root;
}

// hovering a flux position: its crossing arcs in blue, the other arcs faded
function highlight(view, p, on) {
  const crossing = new Set(p.deps.map(([gov, dep]) => gov + ">" + dep));
  view.root.classList.toggle("focus", on);
  for (const a of view.arcs) a.el.classList.toggle("on", on && crossing.has(a.gov + ">" + a.dep));
  for (const r of view.hlRects) r.classList.remove("on");
  if (!on) return;
  for (const [gov, dep] of p.deps) {
    for (const id of [gov, dep]) if (view.byId.has(id)) view.hlRects[view.byId.get(id)].classList.add("on");
  }
}
