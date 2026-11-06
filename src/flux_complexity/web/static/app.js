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

function renderSentence(s, m) {
  const card = el("article", "sentence");
  const line = el("div", "sentence-text");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("arcs");
  line.append(svg);

  const before = new Map(); // token index -> position (gap just before the token)
  const after = new Map(); // MWT token index -> positions inside it
  for (const p of s.positions) {
    if (p.inside_token) {
      if (!after.has(p.left_token)) after.set(p.left_token, []);
      after.get(p.left_token).push(p);
    } else before.set(p.right_token, p);
  }
  const tokEls = [];
  const idToTok = new Map();
  for (const t of s.tokens) {
    for (let id = t.first_id; id <= t.last_id; id++) idToTok.set(id, t.index);
    if (before.has(t.index)) line.append(gapEl(before.get(t.index), m, s, tokEls, idToTok, svg, line));
    const te = el("span", "tok" + (t.is_punct ? " punct" : ""), t.form);
    tokEls[t.index] = te;
    line.append(te);
    for (const p of after.get(t.index) || []) {
      line.append(gapEl(p, m, s, tokEls, idToTok, svg, line, true));
    }
    if (t.space_after) line.append(document.createTextNode(" "));
  }
  card.append(line);
  card.append(summaryEl(s, m));
  if (s.warnings.length) {
    const ul = el("ul", "warnings");
    for (const w of s.warnings) ul.append(el("li", null, "Avertissement : " + w));
    card.append(ul);
  }
  return card;
}

function gapEl(p, m, s, tokEls, idToTok, svg, line, inside = false) {
  const lvl = p[m + "_level"];
  const g = el("span", `gap l${lvl}` + (inside ? " inside" : ""));
  g.tabIndex = 0;
  g.setAttribute("aria-label",
    `Entre « ${s.tokens[p.left_token].form} » et « ${s.tokens[p.right_token].form} » : poids ${p.weight}, taille ${p.size}`);
  const show = () => {
    g.classList.add("active");
    highlight(p, tokEls, idToTok, svg, line, true);
    showTooltip(g, p, s);
  };
  const hide = () => {
    g.classList.remove("active");
    highlight(p, tokEls, idToTok, svg, line, false);
    $("#tooltip").hidden = true;
  };
  g.addEventListener("mouseenter", show);
  g.addEventListener("mouseleave", hide);
  g.addEventListener("focus", show);
  g.addEventListener("blur", hide);
  return g;
}

function highlight(p, tokEls, idToTok, svg, line, on) {
  svg.textContent = "";
  for (const [gov, dep] of p.deps) {
    for (const id of [gov, dep]) tokEls[idToTok.get(id)].classList.toggle("hl", on);
  }
  if (!on) return;
  const box = line.getBoundingClientRect();
  for (const [gov, dep, rel] of p.deps) {
    const a = tokEls[idToTok.get(gov)].getBoundingClientRect();
    const b = tokEls[idToTok.get(dep)].getBoundingClientRect();
    if (a === b || idToTok.get(gov) === idToTok.get(dep)) continue;
    const x1 = a.left + a.width / 2 - box.left, x2 = b.left + b.width / 2 - box.left;
    const y1 = a.top - box.top + 4, y2 = b.top - box.top + 4;
    const h = Math.min(30, 10 + Math.abs(x2 - x1) / 8);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M${x1},${y1} C${x1},${Math.min(y1, y2) - h} ${x2},${Math.min(y1, y2) - h} ${x2},${y2}`);
    path.setAttribute("aria-label", rel);
    svg.append(path);
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
