"""Reference norms (spec §7) and colour levels (spec §8).

A norm is the distribution of flux size and weight over all non-empty flux
positions of a reference corpus, stored as a small JSON file. The beginner page
compares each position of the user's text with it through the tail proportion
P(X >= value).
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .. import __version__
from ..core import CorpusSummary, Distribution, Transform, compute_flux, process, read_conllu

FORMAT = "flux_complexity.norm/1"
METRICS = ("size", "weight")
# Tail-proportion thresholds for light / medium / dark red (spec §8). Weight gets its
# own, looser first threshold: its values are so coarse that with 10% the first level
# would never be reached (UD Sequoia: P(w>=2)=38%, P(w>=3)=4.3%).
DEFAULT_THRESHOLDS: dict[str, tuple[float, ...]] = {
    "weight": (0.40, 0.05, 0.01),
    "size": (0.10, 0.05, 0.02),
}
DEFAULT_NORMS = {"UD": "UD_French-Sequoia", "SUD": "SUD_French-Sequoia"}  # per scheme (spec §9)
DEFAULT_UD_NORM = DEFAULT_NORMS["UD"]  # beginner page default


def _dist_to_json(d: Distribution) -> dict:
    keys = sorted(d.counts)
    return {
        "counts": {str(k): d.counts[k] for k in keys},
        "tail": {str(k): round(d.tail(k), 6) for k in keys},
        "mean": round(d.mean, 6) if d.total else None,
        "std": round(d.std, 6) if d.total else None,
        "max": max(keys) if keys else None,
    }


def build_norm(
    files: Iterable[str | Path],
    scheme: str,
    name: str,
    treebanks: Sequence[str],
    release: str,
    pipeline: Sequence[Transform],
    language: str = "fr",
) -> dict:
    """Compute a norm (as a JSON-ready dict) from CoNLL-U files."""
    summary = CorpusSummary()
    files = [Path(f) for f in files]
    for f in files:
        for sent in read_conllu(f, scheme):
            ps = process(sent, pipeline)
            summary.add(compute_flux(ps), len(ps.warnings))
    return {
        "format": FORMAT,
        "name": name,
        "language": language,
        "scheme": scheme,
        "treebanks": list(treebanks),
        "release": release,
        "files": [f.name for f in files],
        "pipeline": [t.name for t in pipeline],
        "code_version": __version__,
        "created": _dt.date.today().isoformat(),
        "n_sentences": summary.n_sentences,
        "n_sentences_without_flux": summary.n_sentences_without_flux,
        "n_positions": summary.size.total,
        "n_warnings": summary.n_warnings,
        "metrics": {"size": _dist_to_json(summary.size), "weight": _dist_to_json(summary.weight)},
    }


@dataclass(frozen=True)
class Norm:
    data: dict

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def scheme(self) -> str:
        return self.data["scheme"]

    def tail(self, metric: str, value: int) -> float:
        """P(X >= value) in the reference corpus; 0.0 beyond the observed maximum."""
        if metric not in METRICS:
            raise ValueError(f"metric must be one of {METRICS}")
        if value <= 0:
            return 1.0
        counts = {int(k): v for k, v in self.data["metrics"][metric]["counts"].items()}
        total = sum(counts.values())
        return sum(c for k, c in counts.items() if k >= value) / total if total else 0.0

    def level(self, metric: str, value: int, thresholds: Sequence[float] | None = None) -> int:
        """Colour level 0 (none) .. len(thresholds): how rare a value is in this norm.

        thresholds defaults to DEFAULT_THRESHOLDS[metric].
        """
        t = self.tail(metric, value)
        if thresholds is None:
            thresholds = DEFAULT_THRESHOLDS[metric]
        return sum(1 for th in thresholds if t <= th)

    @classmethod
    def load(cls, path: str | Path) -> Norm:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("format") != FORMAT:
            raise ValueError(f"{path}: not a {FORMAT} file")
        return cls(data)

    @classmethod
    def builtin(cls, name: str) -> Norm:
        ref = resources.files(__package__) / "data" / f"{name}.json"
        if not ref.is_file():
            raise KeyError(f"no built-in norm {name!r}; available: {list_builtin()}")
        return cls(json.loads(ref.read_text(encoding="utf-8")))


def list_builtin() -> list[str]:
    folder = resources.files(__package__) / "data"
    return sorted(p.name[:-5] for p in folder.iterdir() if p.name.endswith(".json"))


def write_norm(data: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
