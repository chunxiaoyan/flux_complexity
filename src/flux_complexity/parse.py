"""Raw text -> UD sentences with Stanza (spec §1: user text is always UD).

Stanza is an optional dependency (`pip install flux_complexity[parser]`): the
computation core and uploaded CoNLL-U files work without it.
"""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass

from .core import Sentence, parse_conllu

PROCESSORS = "tokenize,mwt,pos,lemma,depparse"


class ParserUnavailable(RuntimeError):
    """Stanza is not installed or its model cannot be loaded."""


@dataclass(frozen=True)
class ParserInfo:
    language: str
    stanza_version: str
    models: dict[str, str]  # processor -> model file name, e.g. depparse -> combined_charlm.pt


class StanzaParser:
    """Lazy wrapper around a Stanza pipeline. The model is loaded on first use.

    download=True fetches the model the first time (≈320 MB for French); later runs
    work offline. model_dir defaults to Stanza's own location, or $FLUX_STANZA_DIR.
    """

    def __init__(self, language: str = "fr", model_dir: str | None = None, download: bool = True):
        self.language = language
        self.model_dir = model_dir or os.environ.get("FLUX_STANZA_DIR")
        self.download = download
        self._nlp = None

    def _pipeline(self):
        if self._nlp is not None:
            return self._nlp
        try:
            import stanza
        except ImportError as e:
            raise ParserUnavailable(
                "Stanza is not installed. Install it with: pip install 'flux_complexity[parser]'"
            ) from e
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        kwargs = {"processors": PROCESSORS, "verbose": False}
        if self.model_dir:
            kwargs["dir"] = self.model_dir
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                if self.download:
                    stanza.download(self.language, processors=PROCESSORS, verbose=False,
                                    **({"model_dir": self.model_dir} if self.model_dir else {}))  # fmt: skip
                self._nlp = stanza.Pipeline(self.language, download_method=None, **kwargs)
            except Exception as e:  # network errors, missing model files...
                raise ParserUnavailable(f"could not load the Stanza model for {self.language!r}: {e}") from e
        return self._nlp

    def info(self) -> ParserInfo:
        import stanza

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
