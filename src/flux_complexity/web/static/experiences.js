// Page « Corpus et expériences » — vanilla JS, no build step, works offline.
// Text from corpora is only ever inserted with textContent, never parsed as HTML.
"use strict";

const $ = (sel) => document.querySelector(sel);
const PAGE = 50;
const MATRIX_MAX = 8;
const PARATAXIS_LABEL = { exact: "parataxis coupée", all: "parataxis:* coupées", keep: "non coupée" };
const pct = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 2 });
const num = new Intl.NumberFormat("fr-FR");
const plural = (n, word) => `${num.format(n)} ${word}${n > 1 ? "s" : ""}`; // French: 0 and 1 are singular

const state = { corpora: [], corpus: null, query: null, offset: 0, total: 0, matches: new Map(), detail: null, position: null };

// ------------------------------------------------------------------ helpers
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function setStatus(sel, msg, isError = false) {
  const s = $(sel);
  s.textContent = msg;
  s.classList.toggle("error", isError);
}
async function api(path, options) {
  const r = await fetch(path, options);
  if (r.status === 204) return null;
  let body = null;
  try { body = await r.json(); } catch { /* empty body */ }
  if (!r.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : "Erreur inattendue du serveur (" + r.status + ").");
  }
  return body;
}
function intOrNull(sel) {
  const v = $(sel).value.trim();
  return v === "" ? null : Number(v);
}

// ------------------------------------------------------------------ corpora
async function loadCorpora() {
  state.corpora = await api("/api/corpora");
  const body = $("#corpora tbody");
  body.textContent = "";
  $("#corpora").hidden = state.corpora.length === 0;
  $("#no-corpus").hidden = state.corpora.length > 0;
  if (!state.corpora.length) $("#import-box").open = true;
  for (const c of state.corpora) {
    const tr = el("tr");
    if (state.corpus && state.corpus.id === c.id) tr.classList.add("selected");
    tr.append(el("td", null, c.name), el("td", null, c.scheme), el("td", null, PARATAXIS_LABEL[c.parataxis] || c.parataxis),
      el("td", "num", num.format(c.n_sentences)), el("td", "num", num.format(c.n_positions)),
      el("td", "num", num.format(c.n_warnings)), el("td", null, c.created.replace("T", " ")));
    const actions = el("td", "actions");
    const open = el("button", "secondary-btn", "Ouvrir");
    open.type = "button";
    open.addEventListener("click", () => openCorpus(c.id));
    const csv = el("a", null, "CSV");
    csv.href = `/api/corpora/${c.id}/export.csv`;
    csv.setAttribute("download", "");
    const del = el("button", "link danger", "Supprimer");
    del.type = "button";
    del.addEventListener("click", () => deleteCorpus(c));
    actions.append(open, csv, del);
    tr.append(actions);
    body.append(tr);
  }
}

async function importCorpus(e) {
  e.preventDefault();
  const f = $("#imp-file").files[0];
  if (!f) { setStatus("#corpus-status", "Choisissez d'abord un fichier.", true); return; }
  const fd = new FormData();
  fd.append("file", f);
  fd.append("scheme", $("#imp-scheme").value);
  fd.append("parataxis", $("#imp-parataxis").value);
  if ($("#imp-name").value.trim()) fd.append("name", $("#imp-name").value.trim());
  const btn = $("#imp-submit");
  btn.disabled = true;
  setStatus("#corpus-status", `Import de « ${f.name} » : calcul de toutes les positions du flux…`);
  const t0 = performance.now();
  try {
    const c = await api("/api/corpora", { method: "POST", body: fd });
    const t = (performance.now() - t0) / 1000;
    const secs = t < 0.1 ? "< 0,1" : t.toLocaleString("fr-FR", { maximumFractionDigits: 1 });
    setStatus("#corpus-status", `« ${c.name} » importé : ${plural(c.n_sentences, "phrase")}, ` +
      `${plural(c.n_positions, "position")} (${secs} s).`);
    $("#import-form").reset();
    $("#import-box").open = false;
    await openCorpus(c.id);
  } catch (err) {
    setStatus("#corpus-status", err.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function deleteCorpus(c) {
  if (!window.confirm(`Supprimer le corpus « ${c.name} » et toutes ses positions ? Le fichier d'origine n'est pas touché.`)) return;
  try {
    await api(`/api/corpora/${c.id}`, { method: "DELETE" });
    if (state.corpus && state.corpus.id === c.id) { state.corpus = null; $("#corpus-view").hidden = true; }
    setStatus("#corpus-status", `« ${c.name} » supprimé.`);
    await loadCorpora();
  } catch (err) {
    setStatus("#corpus-status", err.message, true);
  }
}

async function openCorpus(id) {
  try {
    state.corpus = await api(`/api/corpora/${id}`);
  } catch (err) {
    setStatus("#corpus-status", err.message, true);
    return;
  }
  const c = state.corpus;
  await loadCorpora();
  $("#corpus-view").hidden = false;
  $("#corpus-title").textContent = `« ${c.name} »`;
  $("#corpus-meta").textContent = `${c.scheme} · parataxe : ${PARATAXIS_LABEL[c.parataxis] || c.parataxis} · ` +
    `${num.format(c.n_sentences)} phrases · ${num.format(c.n_positions)} positions non vides · ` +
    `chaîne de traitement : ${c.pipeline}` + (c.source_file ? ` · fichier : ${c.source_file}` : "");
  distTable($("#dist-size"), c.size_counts);
  distTable($("#dist-weight"), c.weight_counts);
  const dl = $("#deprels");
  dl.textContent = "";
  for (const d of c.deprels) { const o = el("option"); o.value = d; dl.append(o); }
  $("#export-link").href = `/api/corpora/${c.id}/export.csv`;
  $("#detail").hidden = true;
  state.detail = null;
  await search(0);
  $("#h-dist").scrollIntoView({ behavior: "smooth", block: "start" });
}

const fmtShare = (x) => (x > 0 && x < 0.0001 ? "< 0,01 %" : pct.format(x));
const DIST_ROWS = 12; // longer distributions end with one row « ≥ k » for the rare tail

function distTable(table, counts) {
  table.textContent = "";
  let entries = Object.entries(counts).map(([k, n]) => [String(k), Number(k), n]).sort((a, b) => a[1] - b[1]);
  const total = entries.reduce((a, [, , n]) => a + n, 0);
  if (entries.length > DIST_ROWS) {
    const rest = entries.slice(DIST_ROWS - 1);
    entries = entries.slice(0, DIST_ROWS - 1);
    entries.push([`≥ ${rest[0][1]} (max ${rest[rest.length - 1][1]})`, rest[0][1], rest.reduce((a, [, , n]) => a + n, 0)]);
  }
  const maxShare = Math.max(...entries.map(([, , n]) => n)) / total;
  const head = el("tr");
  for (const h of ["k", "positions", "%", "P(X ≥ k)"]) head.append(el("th", h === "k" ? null : "num", h));
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  let above = total;
  for (const [label, , n] of entries) {
    const tr = el("tr");
    const share = total ? n / total : 0;
    const bar = el("td", "num bar-cell");
    const b = el("span", "bar");
    b.style.width = Math.max(1, Math.round((share / maxShare) * 100)) + "%";
    bar.append(b, el("span", "bar-label", fmtShare(share)));
    tr.append(el("td", null, label), el("td", "num", num.format(n)), bar, el("td", "num", fmtShare(total ? above / total : 0)));
    above -= n;
    tbody.append(tr);
  }
  table.append(thead, tbody);
}

// ------------------------------------------------------------- matrix grid
function buildMatrixGrid(keep = true) {
  const rows = Number($("#m-rows").value), cols = Number($("#m-cols").value);
  const old = keep ? selectedCells() : [];
  const grid = $("#m-grid");
  grid.textContent = "";
  const head = el("tr");
  head.append(el("th"));
  for (let c = 1; c <= cols; c++) head.append(el("th", null, `col. ${c}`));
  grid.append(head);
  for (let r = 1; r <= rows; r++) {
    const tr = el("tr");
    tr.append(el("th", null, `lig. ${r}`));
    for (let c = 1; c <= cols; c++) {
      const td = el("td");
      const b = el("button", "cell", `${r},${c}`);
      b.type = "button";
      b.dataset.cell = `${r},${c}`;
      b.setAttribute("aria-pressed", String(old.includes(`${r},${c}`)));
      b.addEventListener("click", () => b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true")));
      td.append(b);
      tr.append(td);
    }
    grid.append(tr);
  }
}
function selectedCells() {
  return [...document.querySelectorAll("#m-grid button[aria-pressed=true]")].map((b) => b.dataset.cell);
}

// ------------------------------------------------------------------ search
function readQuery() {
  const q = {};
  const put = (k, v) => { if (v !== null && v !== "" && !Number.isNaN(v)) q[k] = v; };
  put("min_weight", intOrNull("#q-wmin"));
  put("max_weight", intOrNull("#q-wmax"));
  put("min_size", intOrNull("#q-smin"));
  put("max_size", intOrNull("#q-smax"));
  put("deprel", $("#q-deprel").value.trim());
  put("text", $("#q-text").value.trim());
  const cells = selectedCells();
  if (cells.length) {
    q.matrix = cells.join(" ");
    q.matrix_mode = document.querySelector('input[name="m-mode"]:checked').value;
  }
  return q;
}

function describeQuery(q) {
  const parts = [];
  const range = (label, lo, hi) => {
    if (lo != null && hi != null) parts.push(lo === hi ? `${label} = ${lo}` : `${label} entre ${lo} et ${hi}`);
    else if (lo != null) parts.push(`${label} ≥ ${lo}`);
    else if (hi != null) parts.push(`${label} ≤ ${hi}`);
  };
  range("poids", q.min_weight, q.max_weight);
  range("taille", q.min_size, q.max_size);
  if (q.deprel) parts.push(`relation ${q.deprel}`);
  if (q.matrix) parts.push(`matrice ${q.matrix_mode === "exact" ? "exactement" : "contenant"} ${q.matrix.split(" ").map((c) => `(${c})`).join(" ")}`);
  if (q.text) parts.push(`texte contenant « ${q.text} »`);
  return parts.length ? parts.join(", ") : "toutes les phrases";
}

async function search(offset = 0, q = null) {
  if (!state.corpus) return;
  if (q) { $("#detail").hidden = true; state.detail = null; } // a new query: the open sentence is stale
  state.query = q || state.query || {};
  state.offset = offset;
  const params = new URLSearchParams({ ...state.query, limit: PAGE, offset });
  setStatus("#search-status", "Recherche…");
  let res;
  try {
    res = await api(`/api/corpora/${state.corpus.id}/sentences?${params}`);
  } catch (err) {
    setStatus("#search-status", err.message, true);
    return;
  }
  state.total = res.total;
  state.matches = new Map(res.sentences.map((s) => [s.id, s.positions]));
  const hasPosCond = ["min_weight", "max_weight", "min_size", "max_size", "deprel", "matrix"].some((k) => k in state.query);
  setStatus("#search-status", `${plural(res.total, "phrase")} — ${describeQuery(state.query)}.`);
  const body = $("#results-table tbody");
  body.textContent = "";
  $("#results-table").hidden = res.sentences.length === 0;
  for (const s of res.sentences) {
    const tr = el("tr", "clickable");
    tr.tabIndex = 0;
    const open = () => openSentence(s.id, s.positions);
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    tr.append(el("td", "num", String(s.idx)), el("td", "mono", s.sent_id), el("td", "sent-text", s.text || ""),
      el("td", "num", s.max_weight ?? "—"), el("td", "num", s.max_size ?? "—"),
      el("td", null, hasPosCond ? s.positions.join(", ") : ""));
    body.append(tr);
  }
  const pages = Math.ceil(res.total / PAGE);
  $("#pager").hidden = pages <= 1;
  $("#page-info").textContent = `page ${Math.floor(offset / PAGE) + 1} sur ${pages}`;
  $("#prev").disabled = offset === 0;
  $("#next").disabled = offset + PAGE >= res.total;
}

// ------------------------------------------------------------------ detail
async function openSentence(id, matched = []) {
  let s;
  try {
    s = await api(`/api/sentences/${id}`);
  } catch (err) {
    setStatus("#search-status", err.message, true);
    return;
  }
  state.detail = { s, matched: new Set(matched) };
  state.position = matched.length ? matched[0] : (s.flux[0] ? s.flux[0].position : null);
  $("#detail").hidden = false;
  $("#d-id").textContent = `${s.idx} · ${s.sent_id}`;
  $("#d-text").textContent = s.text || "";
  $("#d-norm").textContent = `Couleurs par rapport à ${s.analysis.norm.replace(/^(S?UD)_French-(.*)$/, "$2 ($1)")}.`;
  const w = $("#d-warnings");
  w.textContent = "";
  for (const m of s.warnings) w.append(el("li", null, "Avertissement : " + m));
  renderDetail();
  $("#detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

function detailMetric() {
  return document.querySelector('input[name="d-metric"]:checked').value;
}

function renderDetail() {
  if (!state.detail) return;
  const { s, matched } = state.detail;
  const a = s.analysis.sentences[0];
  const tree = $("#d-tree");
  tree.textContent = "";
  const svgEl = drawTree(a, detailMetric(), { marked: matched, onClick: (p) => selectPosition(p.position) });
  tree.append(svgEl);
  state.detail.svg = svgEl;
  const forms = new Map(a.words.map((x) => [x.id, x.form]));
  const body = $("#d-positions tbody");
  body.textContent = "";
  for (const f of s.flux) {
    const tr = el("tr", "clickable");
    tr.dataset.position = f.position;
    tr.tabIndex = 0;
    if (matched.has(f.position)) tr.classList.add("marked");
    tr.append(el("td", "num", String(f.position)), el("td", null, `${forms.get(f.left_id)} | ${forms.get(f.right_id)}`),
      el("td", "num", String(f.size)), el("td", "num", String(f.weight)));
    tr.addEventListener("click", () => selectPosition(f.position));
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") selectPosition(f.position); });
    body.append(tr);
  }
  selectPosition(state.position);
}

function selectPosition(position) {
  state.position = position;
  const { s, svg: svgEl } = state.detail;
  for (const tr of document.querySelectorAll("#d-positions tbody tr")) {
    const on = Number(tr.dataset.position) === position;
    tr.classList.toggle("selected", on);
    if (on) tr.scrollIntoView({ block: "nearest" }); // the table scrolls inside its own box
  }
  for (const [pos, g] of svgEl.gapEls) g.classList.toggle("selected", pos === position);
  const box = $("#d-matrix");
  box.textContent = "";
  const f = s.flux.find((x) => x.position === position);
  if (!f) { box.append(el("p", "muted", "Aucune position de flux dans cette phrase.")); return; }
  const forms = new Map(s.analysis.sentences[0].words.map((x) => [x.id, x.form]));
  box.append(el("h3", null, `Matrice du flux en ${forms.get(f.left_id)} | ${forms.get(f.right_id)}`));
  box.append(el("p", "muted", `taille ${f.size} · poids ${f.weight}`));
  const rowWord = new Map(), colWord = new Map(), cell = new Map();
  for (const d of f.deps) {
    rowWord.set(d.row, Math.min(d.gov, d.dep));
    colWord.set(d.col, Math.max(d.gov, d.dep));
    cell.set(`${d.row},${d.col}`, d);
  }
  const nr = Math.max(...rowWord.keys()), nc = Math.max(...colWord.keys());
  const t = el("table", "matrix-grid matrix-result");
  const head = el("tr");
  head.append(el("th"));
  for (let c = 1; c <= nc; c++) head.append(el("th", null, `${c} · ${forms.get(colWord.get(c))}`));
  t.append(head);
  for (let r = 1; r <= nr; r++) {
    const tr = el("tr");
    tr.append(el("th", null, `${r} · ${forms.get(rowWord.get(r))}`));
    for (let c = 1; c <= nc; c++) {
      const d = cell.get(`${r},${c}`);
      const td = el("td", d ? "filled" : null);
      if (d) {
        const arrow = d.gov < d.dep ? "→" : "←";
        td.append(el("span", "rel", d.deprel), el("span", "muted", ` ${arrow}`));
        td.title = `${forms.get(d.gov)} → ${forms.get(d.dep)} (${d.deprel})`;
      }
      tr.append(td);
    }
    t.append(tr);
  }
  box.append(t);
  box.append(el("p", "hint", "→ : le gouverneur est à gauche ; ← : le gouverneur est à droite."));
  const fillShape = el("button", "link", "Chercher cette forme de matrice");
  fillShape.type = "button";
  fillShape.addEventListener("click", () => useShape(f));
  box.append(fillShape);
}

// put the shape of a stored matrix into the search form (exact mode)
function useShape(f) {
  const nr = Math.max(...f.deps.map((d) => d.row)), nc = Math.max(...f.deps.map((d) => d.col));
  if (nr > MATRIX_MAX || nc > MATRIX_MAX) { setStatus("#search-status", "Matrice trop grande pour la grille.", true); return; }
  $("#m-rows").value = nr;
  $("#m-cols").value = nc;
  buildMatrixGrid(false);
  for (const d of f.deps) {
    document.querySelector(`#m-grid button[data-cell="${d.row},${d.col}"]`).setAttribute("aria-pressed", "true");
  }
  document.querySelector('input[name="m-mode"][value="exact"]').checked = true;
  $("#matrix-box").open = true;
  $("#h-search").scrollIntoView({ behavior: "smooth", block: "start" });
}

// --------------------------------------------------------------------- init
async function init() {
  for (const sel of ["#m-rows", "#m-cols"]) {
    for (let i = 1; i <= MATRIX_MAX; i++) {
      const o = el("option", null, String(i));
      o.value = i;
      if (i === 3) o.selected = true;
      $(sel).append(o);
    }
    $(sel).addEventListener("change", () => buildMatrixGrid(true));
  }
  buildMatrixGrid(false);
  $("#m-clear").addEventListener("click", () => buildMatrixGrid(false));
  $("#import-form").addEventListener("submit", importCorpus);
  $("#search-form").addEventListener("submit", (e) => { e.preventDefault(); search(0, readQuery()); });
  $("#q-reset").addEventListener("click", () => {
    for (const id of ["#q-wmin", "#q-wmax", "#q-smin", "#q-smax", "#q-deprel", "#q-text"]) $(id).value = "";
    buildMatrixGrid(false);
    search(0, {});
  });
  $("#prev").addEventListener("click", () => search(Math.max(0, state.offset - PAGE)));
  $("#next").addEventListener("click", () => search(state.offset + PAGE));
  for (const r of document.querySelectorAll('input[name="d-metric"]')) r.addEventListener("change", renderDetail);
  try {
    const h = await api("/api/health");
    $("#footer").textContent = `flux_complexity ${h.version}`;
    await loadCorpora();
  } catch (err) {
    setStatus("#corpus-status", "Impossible de joindre le serveur.", true);
  }
}
init();
