"""FastAPI backend (stage 4). JSON API only; the pages come in stages 5-6.

User-facing error messages ("detail") are in French (spec §9.4).
Interactive documentation: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import csv
import io
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..analysis import analyze_conllu, analyze_sentences
from ..core import PARATAXIS_MODES, build_pipeline
from ..norms import DEFAULT_NORMS, METRICS, Norm, list_builtin
from .db import Database

MAX_TEXT_CHARS = 20_000
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
Scheme = Literal["UD", "SUD"]
POSITION_COLUMNS = ["sent_id", "position", "left_id", "left_form", "right_id", "right_form", "size", "weight", "deps"]


class ParserState:
    """Loads the parser in a background thread so the server starts at once."""

    def __init__(self, parser, enabled: bool = True):
        self.parser = parser
        self.status = "disabled" if not enabled or parser is None else "loading"
        self.error: str | None = None
        self.info: dict | None = None

    def start(self) -> None:
        if self.status != "loading":
            return
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            self.parser.parse("Bonjour.")  # forces model loading (and download on first run)
            i = self.parser.info()
            self.info = {"language": i.language, "stanza": i.stanza_version, "models": i.models}
            self.status = "ready"
        except Exception as e:  # noqa: BLE001 - report any failure to the UI
            self.status, self.error = "unavailable", str(e)


class AnalyzeTextRequest(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT_CHARS, description="Texte en français")
    norm: str | None = Field(None, description="Nom d'un corpus de référence UD (défaut : UD_French-Sequoia)")
    thresholds: dict[str, list[float]] | None = Field(
        None, description='Seuils facultatifs, ex. {"weight": [0.4, 0.05, 0.01]}'
    )


def _norm_or_404(name: str) -> Norm:
    try:
        return Norm.builtin(name)
    except KeyError:
        raise HTTPException(404, f"Corpus de référence inconnu : {name}") from None


def _check_thresholds(th: dict | None) -> dict | None:
    if th is None:
        return None
    for k, v in th.items():
        if k not in METRICS or not v or not all(0 <= x <= 1 for x in v):
            raise HTTPException(422, f"Seuils invalides pour « {k} » : valeurs entre 0 et 1 attendues.")
    return th


async def _read_upload(file: UploadFile) -> str:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Fichier trop volumineux (50 Mo maximum).")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "Le fichier doit être encodé en UTF-8.") from None


def create_app(db_path: str | Path, parser=None, load_parser: bool = True) -> FastAPI:
    """parser: object with .parse(text) and .info() (StanzaParser by default)."""
    if parser is None and load_parser:
        from ..parse import StanzaParser

        parser = StanzaParser()
    state = ParserState(parser, enabled=load_parser)
    db = Database(db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.start()
        yield

    app = FastAPI(
        title="flux_complexity",
        version=__version__,
        description="Flux de dépendances (taille et poids) et complexité syntaxique.",
        lifespan=lifespan,
    )
    app.state.db, app.state.parser = db, state

    # ------------------------------------------------------------ status
    @app.get("/api/health", tags=["statut"])
    def health():
        """État du serveur et de l'analyseur syntaxique (loading / ready / unavailable / disabled)."""
        return {"version": __version__, "parser": state.status, "parser_error": state.error,
                "parser_info": state.info, "database": str(db.path)}  # fmt: skip

    # ------------------------------------------------------------- norms
    @app.get("/api/norms", tags=["références"])
    def norms():
        """Corpus de référence intégrés."""
        out = []
        for name in list_builtin():
            d = Norm.builtin(name).data
            out.append({k: d[k] for k in ("name", "scheme", "release", "n_sentences", "n_positions")}
                       | {"default": DEFAULT_NORMS.get(d["scheme"]) == name})  # fmt: skip
        return out

    @app.get("/api/norms/{name}", tags=["références"])
    def norm(name: str):
        return _norm_or_404(name).data

    # ----------------------------------------------------------- analyse
    @app.post("/api/analyze/text", tags=["analyse"])
    def analyze_text(req: AnalyzeTextRequest):
        """Analyse un texte brut : Stanza (UD) → flux → comparaison au corpus de référence."""
        if not req.text.strip():
            raise HTTPException(422, "Le texte est vide.")
        if state.status == "loading":
            raise HTTPException(503, "L'analyseur syntaxique est en cours de chargement, réessayez dans un instant.")
        if state.status != "ready":
            raise HTTPException(503, f"L'analyseur syntaxique n'est pas disponible. {state.error or ''}".strip())
        n = _norm_or_404(req.norm or DEFAULT_NORMS["UD"])
        if n.scheme != "UD":
            raise HTTPException(422, "Un texte brut est analysé en UD : choisissez un corpus de référence UD.")
        result = analyze_sentences(state.parser.parse(req.text), n, thresholds=_check_thresholds(req.thresholds))
        result.parser = state.info
        return result.to_dict()

    @app.post("/api/analyze/conllu", tags=["analyse"])
    async def analyze_uploaded(
        file: UploadFile = File(..., description="Fichier .conllu"),
        scheme: Scheme = Form("UD"),
        norm: str | None = Form(None),
    ):
        """Analyse un fichier CoNLL-U déjà annoté (UD ou SUD), sans passer par Stanza."""
        text = await _read_upload(file)
        n = _norm_or_404(norm) if norm else None
        if n is not None and n.scheme != scheme:
            raise HTTPException(422, f"Le fichier est en {scheme} mais le corpus de référence est en {n.scheme}.")
        try:
            return analyze_conllu(text, scheme, n).to_dict()
        except ValueError as e:
            raise HTTPException(422, f"Fichier CoNLL-U invalide : {e}") from None

    # ----------------------------------------------------------- corpora
    @app.post("/api/corpora", tags=["corpus"], status_code=201)
    async def import_corpus(
        file: UploadFile = File(...),
        scheme: Scheme = Form(...),
        name: str | None = Form(None),
        parataxis: Literal["exact", "all", "keep"] = Form("exact", description=str(PARATAXIS_MODES)),
    ):
        """Importe un corpus CoNLL-U : calcule et enregistre toutes les positions de flux."""
        text = await _read_upload(file)
        try:
            cid = db.import_conllu(text, name or Path(file.filename or "corpus").stem, scheme, parataxis, file.filename)
        except ValueError as e:
            raise HTTPException(422, f"Fichier CoNLL-U invalide : {e}") from None
        return db.corpus(cid)

    @app.get("/api/corpora", tags=["corpus"])
    def list_corpora():
        return db.corpora()

    @app.get("/api/corpora/{corpus_id}", tags=["corpus"])
    def get_corpus(corpus_id: int):
        """Métadonnées et distributions (taille, poids) d'un corpus importé."""
        c = db.corpus(corpus_id)
        if c is None:
            raise HTTPException(404, "Corpus introuvable.")
        return c

    @app.delete("/api/corpora/{corpus_id}", tags=["corpus"], status_code=204)
    def delete_corpus(corpus_id: int):
        if not db.delete_corpus(corpus_id):
            raise HTTPException(404, "Corpus introuvable.")

    @app.get("/api/corpora/{corpus_id}/sentences", tags=["corpus"])
    def search_sentences(
        corpus_id: int,
        min_weight: int | None = Query(None, ge=1, description="Au moins une position de poids ≥ cette valeur"),
        min_size: int | None = Query(None, ge=1, description="Au moins une position de taille ≥ cette valeur"),
        deprel: str | None = Query(None, description="Relation présente dans cette même position, ex. nmod"),
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ):
        """Recherche de phrases. Les conditions portent sur une même position de flux."""
        if db.corpus(corpus_id) is None:
            raise HTTPException(404, "Corpus introuvable.")
        total, rows = db.sentences(corpus_id, min_weight, min_size, deprel, limit, offset)
        return {"total": total, "limit": limit, "offset": offset, "sentences": rows}

    @app.get("/api/sentences/{sentence_id}", tags=["corpus"])
    def get_sentence(sentence_id: int, norm: str | None = None):
        """Détail d'une phrase : flux stockés + analyse par rapport à un corpus de référence."""
        s = db.sentence(sentence_id)
        if s is None:
            raise HTTPException(404, "Phrase introuvable.")
        n = _norm_or_404(norm or DEFAULT_NORMS[s["scheme"]])
        if n.scheme != s["scheme"]:
            raise HTTPException(422, f"La phrase est en {s['scheme']} mais le corpus de référence est en {n.scheme}.")
        pipeline = build_pipeline(s["parataxis"])  # same preprocessing as at import time
        s["analysis"] = analyze_conllu(s["conllu"], s["scheme"], n, pipeline=pipeline).to_dict()
        return s

    @app.get("/api/corpora/{corpus_id}/export.csv", tags=["corpus"])
    def export_csv(corpus_id: int):
        """Toutes les positions de flux du corpus (une ligne par position, avec sent_id)."""
        c = db.corpus(corpus_id)
        if c is None:
            raise HTTPException(404, "Corpus introuvable.")

        def rows():
            buf = io.StringIO()
            w = csv.writer(buf)
            buf.write("﻿")
            w.writerow(POSITION_COLUMNS)
            for r in db.export_positions(corpus_id):
                w.writerow(r)
                if buf.tell() > 64_000:
                    yield buf.getvalue()
                    buf.seek(0), buf.truncate()
            yield buf.getvalue()

        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", c["name"]).strip("_") or "corpus"
        filename += ".positions.csv"
        return StreamingResponse(rows(), media_type="text/csv; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="{filename}"'})  # fmt: skip

    return app
