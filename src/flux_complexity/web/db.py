"""SQLite storage for the experiment part: imported corpora and their flux positions.

Plain sqlite3 (no ORM) so the schema below *is* the documentation. One file, no
server: suitable for local single-user use.

Matrix coordinates (flux_dep.row / col) follow the legacy flux matrix: rows are the
distinct left endpoints of the flux in ascending order, columns the distinct right
endpoints in descending order, both numbered from 1. They enable the
"matrix shape" query of the old web tool (stage 6).
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from ..analysis import render_text, surface_tokens
from ..core import (
    CorpusSummary,
    Sentence,
    build_pipeline,
    compute_flux,
    parse_conllu,
    process,
    summarize_sentence,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    scheme        TEXT NOT NULL CHECK (scheme IN ('UD', 'SUD')),
    parataxis     TEXT NOT NULL,          -- exact / all / keep (spec §3.2)
    pipeline      TEXT NOT NULL,          -- e.g. "remove_punct -> cut_parataxis"
    source_file   TEXT,
    created       TEXT NOT NULL,
    n_sentences   INTEGER NOT NULL DEFAULT 0,
    n_positions   INTEGER NOT NULL DEFAULT 0,
    n_warnings    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sentence (
    id            INTEGER PRIMARY KEY,
    corpus_id     INTEGER NOT NULL REFERENCES corpus(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,       -- 1-based order in the file
    sent_id       TEXT NOT NULL,
    text          TEXT,
    n_words       INTEGER NOT NULL,       -- after preprocessing
    n_positions   INTEGER NOT NULL,       -- non-empty flux positions
    max_size      INTEGER,
    mean_size     REAL,
    max_weight    INTEGER,
    mean_weight   REAL,
    conllu        TEXT NOT NULL           -- original CoNLL-U block, for display
);
CREATE TABLE IF NOT EXISTS flux (
    id            INTEGER PRIMARY KEY,
    sentence_id   INTEGER NOT NULL REFERENCES sentence(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,       -- new numbering (punctuation excluded)
    left_id       INTEGER NOT NULL,       -- original word ids around the gap
    right_id      INTEGER NOT NULL,
    size          INTEGER NOT NULL,
    weight        INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS flux_dep (
    flux_id       INTEGER NOT NULL REFERENCES flux(id) ON DELETE CASCADE,
    gov           INTEGER NOT NULL,       -- original word ids
    dep           INTEGER NOT NULL,
    deprel        TEXT NOT NULL,
    row           INTEGER NOT NULL,       -- matrix coordinates (see module docstring)
    col           INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS warning (
    sentence_id   INTEGER NOT NULL REFERENCES sentence(id) ON DELETE CASCADE,
    message       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sentence_corpus ON sentence(corpus_id, idx);
CREATE INDEX IF NOT EXISTS ix_flux_sentence ON flux(sentence_id);
CREATE INDEX IF NOT EXISTS ix_flux_weight ON flux(weight);
CREATE INDEX IF NOT EXISTS ix_flux_size ON flux(size);
CREATE INDEX IF NOT EXISTS ix_flux_dep_flux ON flux_dep(flux_id);
CREATE INDEX IF NOT EXISTS ix_flux_dep_deprel ON flux_dep(deprel);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        # SQLite's lower() only folds ASCII; this one also folds « É », « Œ »…
        con.create_function("casefold", 1, lambda t: t.casefold() if t is not None else None, deterministic=True)
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    # ---------------------------------------------------------------- import
    def import_conllu(
        self, text: str, name: str, scheme: str, parataxis: str = "exact", source_file: str | None = None
    ) -> int:
        """Parse, compute and store a whole CoNLL-U corpus in one transaction. Returns corpus id."""
        pipeline = build_pipeline(parataxis)
        sentences = parse_conllu(text, scheme)  # raises ValueError on bad input, before writing
        blocks = _split_blocks(text)
        if len(blocks) != len(sentences):
            raise ValueError("could not align CoNLL-U blocks with parsed sentences")
        summary = CorpusSummary()
        with self.connect() as con:
            cur = con.execute(
                "INSERT INTO corpus (name, scheme, parataxis, pipeline, source_file, created) VALUES (?,?,?,?,?,?)",
                (name, scheme, parataxis, " -> ".join(t.name for t in pipeline), source_file,
                 _dt.datetime.now().isoformat(timespec="seconds")),
            )  # fmt: skip
            corpus_id = cur.lastrowid
            for idx, (sent, block) in enumerate(zip(sentences, blocks), start=1):
                self._insert_sentence(con, corpus_id, idx, sent, block, pipeline, summary)
            con.execute(
                "UPDATE corpus SET n_sentences=?, n_positions=?, n_warnings=? WHERE id=?",
                (summary.n_sentences, summary.size.total, summary.n_warnings, corpus_id),
            )
        return corpus_id

    @staticmethod
    def _insert_sentence(con, corpus_id, idx, sent: Sentence, block, pipeline, summary) -> None:
        ps = process(sent, pipeline)
        positions = compute_flux(ps)
        summary.add(positions, len(ps.warnings))
        s = summarize_sentence(sent.sent_id, ps.n, positions)
        sid = con.execute(
            "INSERT INTO sentence (corpus_id, idx, sent_id, text, n_words, n_positions, max_size, mean_size,"
            " max_weight, mean_weight, conllu) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (corpus_id, idx, sent.sent_id, sent.text or render_text(surface_tokens(sent)[0]), s.n_words, s.n_positions, s.max_size, s.mean_size,
             s.max_weight, s.mean_weight, block),
        ).lastrowid  # fmt: skip
        orig = ps.new2orig
        for p in positions:
            fid = con.execute(
                "INSERT INTO flux (sentence_id, position, left_id, right_id, size, weight) VALUES (?,?,?,?,?,?)",
                (sid, p.position, orig[p.position - 1], orig[p.position], p.size, p.weight),
            ).lastrowid
            rows = {v: i for i, v in enumerate(sorted({d.left for d in p.deps}), start=1)}
            cols = {v: i for i, v in enumerate(sorted({d.right for d in p.deps}, reverse=True), start=1)}
            con.executemany(
                "INSERT INTO flux_dep (flux_id, gov, dep, deprel, row, col) VALUES (?,?,?,?,?,?)",
                [(fid, orig[d.gov - 1], orig[d.dep - 1], d.deprel, rows[d.left], cols[d.right]) for d in p.deps],
            )
        con.executemany("INSERT INTO warning (sentence_id, message) VALUES (?, ?)", [(sid, w) for w in ps.warnings])

    # --------------------------------------------------------------- queries
    def corpora(self) -> list[dict]:
        with self.connect() as con:
            return [dict(r) for r in con.execute("SELECT * FROM corpus ORDER BY id")]

    def corpus(self, corpus_id: int) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM corpus WHERE id=?", (corpus_id,)).fetchone()
            if row is None:
                return None
            d = dict(row)
            for metric in ("size", "weight"):
                d[f"{metric}_counts"] = {
                    r[0]: r[1]
                    for r in con.execute(
                        f"SELECT f.{metric}, COUNT(*) FROM flux f JOIN sentence s ON s.id=f.sentence_id"
                        f" WHERE s.corpus_id=? GROUP BY f.{metric} ORDER BY f.{metric}",
                        (corpus_id,),
                    )
                }
            # relations that occur in at least one flux position, for the search form
            d["deprels"] = [
                r[0]
                for r in con.execute(
                    "SELECT DISTINCT d.deprel FROM flux_dep d JOIN flux f ON f.id=d.flux_id"
                    " JOIN sentence s ON s.id=f.sentence_id WHERE s.corpus_id=? ORDER BY d.deprel",
                    (corpus_id,),
                )
            ]
            return d

    def delete_corpus(self, corpus_id: int) -> bool:
        with self.connect() as con:
            return con.execute("DELETE FROM corpus WHERE id=?", (corpus_id,)).rowcount > 0

    def sentences(
        self,
        corpus_id: int,
        *,
        min_weight: int | None = None,
        max_weight: int | None = None,
        min_size: int | None = None,
        max_size: int | None = None,
        deprel: str | None = None,
        text: str | None = None,
        matrix: Sequence[tuple[int, int]] | None = None,
        matrix_mode: str = "exact",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[dict]]:
        """Sentences having at least one flux position matching all position conditions.

        Position conditions (weight, size, deprel, matrix) must hold in the *same* flux
        position; each returned sentence lists those positions in "positions".
        - deprel without subtype ("acl") also matches its subtypes ("acl:relcl");
          with a subtype it matches exactly.
        - matrix: cells (row, col) of the flux matrix that must hold a dependency.
          "exact": the matrix is exactly these cells (the legacy list_mat query);
          "contains": these cells are filled, other cells may be too.
        text is a case-insensitive substring of the sentence text.
        """
        if matrix_mode not in ("exact", "contains"):
            raise ValueError(f"unknown matrix mode {matrix_mode!r}")
        where, args = ["s.corpus_id = ?"], [corpus_id]
        if text:
            where.append("instr(casefold(s.text), casefold(?)) > 0")
            args.append(text)
        flux_cond, flux_args = [], []
        for expr, value in (("f.weight >= ?", min_weight), ("f.weight <= ?", max_weight),
                            ("f.size >= ?", min_size), ("f.size <= ?", max_size)):  # fmt: skip
            if value is not None:
                flux_cond.append(expr)
                flux_args.append(value)
        if deprel:
            if ":" in deprel:
                flux_cond.append("EXISTS (SELECT 1 FROM flux_dep d WHERE d.flux_id=f.id AND d.deprel=?)")
                flux_args.append(deprel)
            else:
                flux_cond.append(
                    "EXISTS (SELECT 1 FROM flux_dep d WHERE d.flux_id=f.id"
                    " AND (d.deprel=? OR substr(d.deprel, 1, length(?) + 1) = ? || ':'))"
                )
                flux_args += [deprel, deprel, deprel]
        if matrix:
            cells = sorted(set(matrix))
            match = " OR ".join(["(d.row=? AND d.col=?)"] * len(cells))
            flux_cond.append(f"(SELECT COUNT(*) FROM flux_dep d WHERE d.flux_id=f.id AND ({match})) = ?")
            flux_args += [v for cell in cells for v in cell] + [len(cells)]
            if matrix_mode == "exact":
                flux_cond.append("f.size = ?")
                flux_args.append(len(cells))
        cols = "s.id, s.idx, s.sent_id, s.text, s.n_words, s.n_positions, s.max_size, s.mean_size, " \
               "s.max_weight, s.mean_weight"  # fmt: skip
        select_args: list = []
        if flux_cond:
            # INDEXED BY: without it SQLite may pick ix_flux_size for « f.size = ? » and scan
            # every position of that size for each sentence (7 s instead of 0.3 s on Sequoia)
            fc = " AND ".join(flux_cond)
            where.append(f"EXISTS (SELECT 1 FROM flux f INDEXED BY ix_flux_sentence WHERE f.sentence_id=s.id AND {fc})")
            args += flux_args
            cols += f", (SELECT group_concat(f.position) FROM flux f INDEXED BY ix_flux_sentence WHERE f.sentence_id=s.id AND {fc}) AS positions"
            select_args = flux_args
        clause = " AND ".join(where)
        with self.connect() as con:
            total = con.execute(f"SELECT COUNT(*) FROM sentence s WHERE {clause}", args).fetchone()[0]
            rows = con.execute(
                f"SELECT {cols} FROM sentence s WHERE {clause} ORDER BY s.idx LIMIT ? OFFSET ?",
                [*select_args, *args, limit, offset],
            )
            out = []
            for r in rows:
                d = dict(r)
                d["positions"] = sorted(int(p) for p in (d.get("positions") or "").split(",") if p)
                out.append(d)
            return total, out

    def sentence(self, sentence_id: int) -> dict | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM sentence WHERE id=?", (sentence_id,)).fetchone()
            if row is None:
                return None
            d = dict(row)
            c = con.execute("SELECT scheme, parataxis FROM corpus WHERE id=?", (d["corpus_id"],)).fetchone()
            d["scheme"], d["parataxis"] = c["scheme"], c["parataxis"]
            d["warnings"] = [r[0] for r in con.execute("SELECT message FROM warning WHERE sentence_id=?", (sentence_id,))]
            fluxes = []
            for f in con.execute("SELECT * FROM flux WHERE sentence_id=? ORDER BY position", (sentence_id,)):
                fd = dict(f)
                fd["deps"] = [
                    dict(r)
                    for r in con.execute(
                        "SELECT gov, dep, deprel, row, col FROM flux_dep WHERE flux_id=? ORDER BY MIN(gov, dep), MAX(gov, dep)", (f["id"],)
                    )
                ]
                fluxes.append(fd)
            d["flux"] = fluxes
            return d

    def export_positions(self, corpus_id: int) -> Iterator[tuple]:
        """Rows for the positions CSV (same columns as `fluxcalc compute`)."""
        with self.connect() as con:
            q = (
                "SELECT s.sent_id, f.position, f.left_id, f.right_id, f.size, f.weight, s.conllu, f.id"
                " FROM flux f JOIN sentence s ON s.id=f.sentence_id WHERE s.corpus_id=? ORDER BY s.idx, f.position"
            )
            forms_cache: dict[str, dict[int, str]] = {}
            for sent_id, pos, left, right, size, weight, conllu, fid in con.execute(q, (corpus_id,)).fetchall():
                forms = forms_cache.setdefault(sent_id, _forms(conllu))
                deps = "|".join(
                    f"{forms[g]}->{forms[d]}:{rel}"
                    for g, d, rel in con.execute(
                        "SELECT gov, dep, deprel FROM flux_dep WHERE flux_id=? ORDER BY MIN(gov, dep), MAX(gov, dep)", (fid,)
                    )
                )
                yield (sent_id, pos, left, forms[left], right, forms[right], size, weight, deps)


def _split_blocks(text: str) -> list[str]:
    """CoNLL-U sentence blocks (comments + token lines), in order."""
    blocks, cur = [], []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append("\n".join(cur) + "\n")
            cur = []
    if cur:
        blocks.append("\n".join(cur) + "\n")
    return [b for b in blocks if any(not ln.startswith("#") for ln in b.splitlines())]


def _forms(conllu_block: str) -> dict[int, str]:
    out = {}
    for line in conllu_block.splitlines():
        cols = line.split("\t")
        if len(cols) == 10 and cols[0].isdigit():
            out[int(cols[0])] = cols[1]
    return out
