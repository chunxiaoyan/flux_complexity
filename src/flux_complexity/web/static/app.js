// Page « Analyser un texte » — vanilla JS, no build step, works offline.
// User text is only ever inserted with textContent, never parsed as HTML.
"use strict";

const $ = (sel) => document.querySelector(sel);
const MAX_LABEL = { weight: "Poids maximal", size: "Taille maximale" };
const DEFAULT_THRESHOLDS = { weight: [40, 5, 1], size: [10, 5, 2] };
const pct = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 1 });
const fmtTail = (t) => (t > 0 && t < 0.001 ? "moins de 0,1 %" : pct.format(t));

let lastResult = null;
let norms = [];

// ------------------------------------------------------------------ helpers
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function setStatus(msg, isError = false) {
  const s = $("#status");
  s.textContent = msg;
  s.classList.toggle("error", isError);
}
function metric() {
  return document.querySelector('input[name="metric"]:checked').value;
}
function thresholds() {
  const out = {};
  for (const row of document.querySelectorAll(".thresholds tr[data-metric]")) {
    out[row.dataset.metric] = [...row.querySelectorAll("input")].map((i) => Number(i.value) / 100);
  }
  return out;
}
async function api(path, options) {
  const r = await fetch(path, options);
  let body = null;
  try { body = await r.json(); } catch { /* empty body */ }
  if (!r.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : "Erreur inattendue du serveur (" + r.status + ").");
  }
  return body;
}

// ------------------------------------------------------------- norms, health
function fillNorms(scheme) {
  const sel = $("#norm");
  const keep = sel.value;
  sel.textContent = "";
  for (const n of norms.filter((x) => x.scheme === scheme)) {
    const label = n.name.replace(/^S?UD_French-/, "").replace("merged", "les trois réunis");
    const o = el("option", null, `${label} (${scheme})`);
    o.value = n.name;
    if (n.default) o.selected = true;
    sel.append(o);
  }
  if ([...sel.options].some((o) => o.value === keep)) sel.value = keep;
}

async function pollHealth() {
  try {
    const h = await api("/api/health");
    const btn = $("#analyze");
    if (h.parser === "loading") {
      btn.disabled = true;
      setStatus("Chargement de l'analyseur syntaxique… (la première fois, cela peut prendre une minute)");
      setTimeout(pollHealth, 1500);
      return;
    }
    btn.disabled = h.parser !== "ready";
    if (h.parser === "ready") {
      setStatus("");
      const m = h.parser_info.models || {};
      $("#footer").textContent =
        `Analyse syntaxique : Stanza ${h.parser_info.stanza} (modèle ${m.depparse || "?"}) · flux_complexity ${h.version}`;
    } else {
      setStatus("L'analyseur syntaxique n'est pas disponible : seule l'analyse de fichiers CoNLL-U est possible.", true);
      $("#upload-box").open = true;
    }
  } catch {
    setStatus("Impossible de joindre le serveur.", true);
  }
}

// ------------------------------------------------------------------ analyse
async function analyzeText() {
  const text = $("#text").value;
  if (!text.trim()) { setStatus("Écrivez d'abord un texte.", true); return; }
  // raw text is always parsed into UD: make sure a UD reference corpus is selected
  if (!norms.some((n) => n.name === $("#norm").value && n.scheme === "UD")) fillNorms("UD");
  const btn = $("#analyze");
  btn.disabled = true;
  setStatus("Analyse en cours…");
  try {
    lastResult = await api("/api/analyze/text", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, norm: $("#norm").value, thresholds: thresholds() }),
    });
    setStatus("");
    render();
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function analyzeFile() {
  const f = $("#file").files[0];
  if (!f) { setStatus("Choisissez d'abord un fichier.", true); return; }
  const scheme = $("#scheme").value;
  const norm = $("#norm").value;
  const fd = new FormData();
  fd.append("file", f);
  fd.append("scheme", scheme);
  if (norms.find((n) => n.name === norm && n.scheme === scheme)) fd.append("norm", norm);
  setStatus("Analyse du fichier…");
  try {
    lastResult = await api("/api/analyze/conllu", { method: "POST", body: fd });
    // the API uses default thresholds for files; recompute levels with the page's thresholds
    applyThresholds(lastResult, thresholds());
    setStatus(`${lastResult.sentences.length} phrase(s) analysée(s).`);
    render();
  } catch (e) {
    setStatus(e.message, true);
  }
}

function levelOf(tail, th) {
  return th.filter((t) => tail <= t).length;
}
function applyThresholds(result, th) {
  result.thresholds = th;
  for (const s of result.sentences) {
    for (const p of s.positions) {
      p.weight_level = levelOf(p.weight_tail, th.weight);
      p.size_level = levelOf(p.size_tail, th.size);
    }
  }
}

// ------------------------------------------------------------------- render
function normLabel(name) {
  return name.replace(/^(S?UD)_French-(.*)$/, (_, s, t) => `${t === "merged" ? "les trois corpus" : t} (${s})`);
}

function render() {
  const out = $("#results");
  out.textContent = "";
  if (!lastResult) return;
  $("#legend").hidden = false;
  const m = metric();
  for (const s of lastResult.sentences) out.append(renderSentence(s, m));
}

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

function renderSentence(s, m) {
  const card = el("article", "sentence");
  const scroll = el("div", "tree-scroll");
  scroll.append(drawTree(s, m));
  card.append(scroll);
  card.append(summaryEl(s, m));
  if (s.warnings.length) {
    const ul = el("ul", "warnings");
    for (const w of s.warnings) ul.append(el("li", null, "Avertissement : " + w));
    card.append(ul);
  }
  return card;
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

function drawTree(s, m) {
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
  for (const { p, x: sx } of slots) {
    const left = words[byId.get(p.left_id)].form, right = words[byId.get(p.right_id)].form;
    const g = svg("rect", { class: `gap l${p[m + "_level"]}`, x: sx, y: wordY + 2, width: 10, height: T.wordH - 2,
      rx: 3, tabindex: 0, "aria-label": `Entre « ${left} » et « ${right} » : poids ${p.weight}, taille ${p.size}` });
    const show = () => { g.classList.add("active"); highlight(view, p, true); showTooltip(g, p, s); };
    const hide = () => { g.classList.remove("active"); highlight(view, p, false); $("#tooltip").hidden = true; };
    g.addEventListener("mouseenter", show);
    g.addEventListener("mouseleave", hide);
    g.addEventListener("focus", show);
    g.addEventListener("blur", hide);
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

function showTooltip(anchor, p, s) {
  const tt = $("#tooltip");
  tt.textContent = "";
  const left = s.tokens[p.left_token].form, right = s.tokens[p.right_token].form;
  tt.append(el("div", "tt-head", p.inside_token ? `À l'intérieur de « ${left} »` : `Entre « ${left} » et « ${right} »`));
  const line = (label, value, tail) => {
    const d = el("div");
    d.append(document.createTextNode(label + " : "));
    d.append(el("b", null, String(value)));
    d.append(document.createTextNode(` — ${fmtTail(tail)} des positions du corpus de référence atteignent cette valeur`));
    return d;
  };
  tt.append(line("Poids", p.weight, p.weight_tail));
  tt.append(line("Taille", p.size, p.size_tail));
  tt.append(el("div", "tt-head tt-sub", `${p.deps.length} lien(s) traversent cet endroit :`));
  const form = (id) => {
    const t = s.tokens.find((x) => x.first_id <= id && id <= x.last_id);
    return t.first_id === t.last_id ? t.form : `${t.form}[${id - t.first_id + 1}]`;
  };
  const list = el("ul", "tt-deps");
  for (const [gov, dep, rel] of p.deps.slice(0, 10)) list.append(el("li", null, `${form(gov)} → ${form(dep)} (${rel})`));
  if (p.deps.length > 10) list.append(el("li", null, "…"));
  tt.append(list);
  tt.hidden = false;
  const r = anchor.getBoundingClientRect();
  const x = Math.min(window.innerWidth - tt.offsetWidth - 8, Math.max(8, r.left - tt.offsetWidth / 2));
  const y = r.bottom + 8 + tt.offsetHeight > window.innerHeight ? r.top - tt.offsetHeight - 8 : r.bottom + 8;
  tt.style.left = x + "px";
  tt.style.top = y + "px";
}

function summaryEl(s, m) {
  const p = el("p", "summary");
  if (!s.positions.length) {
    p.append(el("span", "muted", "Aucun flux dans cette phrase (un seul mot, ou seulement de la ponctuation)."));
    return p;
  }
  const peak = s.positions.reduce((a, b) => (b[m] > a[m] ? b : a));
  const tail = peak[m + "_tail"];
  const where = peak.inside_token
    ? `à l'intérieur de « ${s.tokens[peak.left_token].form} »`
    : `entre « ${s.tokens[peak.left_token].form} » et « ${s.tokens[peak.right_token].form} »`;
  const strong = el("strong", null, `${MAX_LABEL[m]} : ${peak[m]}`);
  p.append(strong);
  p.append(document.createTextNode(` ${where}. `));
  const ref = normLabel(lastResult.norm);
  p.append(el("span", "muted",
    tail >= 0.5
      ? `Valeur courante : ${fmtTail(tail)} des positions de ${ref} atteignent cette valeur.`
      : `Seulement ${fmtTail(tail)} des positions de ${ref} atteignent cette valeur.`));
  return p;
}

// --------------------------------------------------------------------- init
async function init() {
  try {
    norms = await api("/api/norms");
  } catch {
    norms = [];
  }
  fillNorms("UD");
  $("#analyze").addEventListener("click", analyzeText);
  $("#text").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) analyzeText();
  });
  $("#analyze-file").addEventListener("click", analyzeFile);
  $("#scheme").addEventListener("change", (e) => fillNorms(e.target.value));
  $("#upload-box").addEventListener("toggle", (e) => {
    fillNorms(e.target.open ? $("#scheme").value : "UD");
  });
  for (const r of document.querySelectorAll('input[name="metric"]')) r.addEventListener("change", render);
  for (const i of document.querySelectorAll(".thresholds input")) {
    i.addEventListener("change", () => {
      if (lastResult) { applyThresholds(lastResult, thresholds()); render(); }
    });
  }
  $("#reset-thresholds").addEventListener("click", () => {
    for (const row of document.querySelectorAll(".thresholds tr[data-metric]")) {
      row.querySelectorAll("input").forEach((inp, k) => (inp.value = DEFAULT_THRESHOLDS[row.dataset.metric][k]));
    }
    if (lastResult) { applyThresholds(lastResult, thresholds()); render(); }
  });
  pollHealth();
}
init();
