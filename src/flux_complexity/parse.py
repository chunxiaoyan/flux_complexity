"""Raw text -> UD sentences with Stanza (spec §1: user text is always UD).

Stanza is an optional dependency (`pip install flux_complexity[parser]`): the
computation core and uploaded CoNLL-U files work without it.
"""

from __future__ import annotations

import os
import shutil
import warnings
from dataclasses import dataclass
from pathlib import Path

from .core import Sentence, parse_conllu

PROCESSORS = "tokenize,mwt,pos,lemma,depparse"


class ParserUnavailable(RuntimeError):
    """Stanza is not installed or its model cannot be loaded."""


def _import_stanza():
    try:
        import stanza
    except ImportError as e:
        raise ParserUnavailable(
            "Stanza is not installed. In the flux_complexity folder, run: uv tool install --force \".[web,parser]\""
            " (or: pip install \".[parser]\")"
        ) from e
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return stanza


def hf_duplicate(language: str = "fr") -> Path | None:
    """The Hugging Face cache copy of Stanza's model repo for `language`, if any.

    Stanza only uses it while downloading; its own copy is what it loads.
    """
    try:
        from huggingface_hub import constants
    except ImportError:
        return None
    path = Path(constants.HF_HUB_CACHE) / f"models--stanfordnlp--stanza-{language}"
    return path if path.exists() else None


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


@dataclass(frozen=True)
class ParserInfo:
    language: str
    stanza_version: str
    models: dict[str, str]  # processor -> model file name, e.g. depparse -> combined_charlm.pt


class StanzaParser:
    """Lazy wrapper around a Stanza pipeline. The model is loaded on first use.

    The local model is tried first, so a machine that already has it works offline;
    only if it is missing (and download=True) is it fetched (≈320 MB for French).
    model_dir defaults to Stanza's own location, or $FLUX_STANZA_DIR.

    Stanza downloads through the Hugging Face cache and then *copies* the files into
    its own folder, so every model would be stored twice. After a download made here,
    the Hugging Face copy is removed if (and only if) this download created it.
    """

    def __init__(self, language: str = "fr", model_dir: str | None = None, download: bool = True):
        self.language = language
        self.model_dir = model_dir or os.environ.get("FLUX_STANZA_DIR")
        self.download = download
        self._nlp = None

    def _pipeline(self):
        if self._nlp is not None:
            return self._nlp
        stanza = _import_stanza()
        kwargs = {"processors": PROCESSORS, "verbose": False, "download_method": None}
        if self.model_dir:
            kwargs["dir"] = self.model_dir
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                self._nlp = stanza.Pipeline(self.language, **kwargs)
            except Exception as first:  # model (or resources.json) not there yet
                if not self.download:
                    raise ParserUnavailable(f"no Stanza model for {self.language!r} in {self.location()}: {first}") from first
                try:
                    self.fetch_model()
                    self._nlp = stanza.Pipeline(self.language, **kwargs)
                except Exception as e:  # network errors, broken files...
                    raise ParserUnavailable(f"could not load the Stanza model for {self.language!r}: {e}") from e
        return self._nlp

    def location(self) -> Path:
        """Folder holding the Stanza models."""
        if self.model_dir:
            return Path(self.model_dir)
        from stanza.resources.common import DEFAULT_MODEL_DIR

        return Path(DEFAULT_MODEL_DIR)

    def fetch_model(self) -> None:
        """Download the model, then drop the Hugging Face duplicate if we created it."""
        stanza = _import_stanza()
        dup = hf_duplicate(self.language)
        existed = dup is not None and dup.exists()
        stanza.download(self.language, processors=PROCESSORS, verbose=False,
                        **({"model_dir": self.model_dir} if self.model_dir else {}))  # fmt: skip
        dup = hf_duplicate(self.language)
        if not existed and dup is not None and dup.exists():
            shutil.rmtree(dup, ignore_errors=True)

    def info(self) -> ParserInfo:
        stanza = _import_stanza()
        nlp = self._pipeline()
        models = {
            name: os.path.basename(str(p.config.get("model_path", "")))
            for name, p in nlp.processors.items()
        }
        return ParserInfo(self.language, stanza.__version__, models)

    def to_conllu(self, text: str) -> str:
        """Parse raw text and return CoNLL-U (sentences numbered s1, s2, ...)."""
        doc = self._pipeline()(text)
        for i, sent in enumerate(doc.sentences, start=1):
            sent.sent_id = f"s{i}"
        return "{:C}".format(doc) + "\n"

    def parse(self, text: str) -> list[Sentence]:
        """Parse raw text into UD sentences."""
        if not text.strip():
            return []
        return parse_conllu(self.to_conllu(text), "UD")
