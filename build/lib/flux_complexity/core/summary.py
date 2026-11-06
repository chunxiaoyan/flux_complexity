"""Sentence- and corpus-level aggregation of flux size and weight (spec §5).

Averages are taken over non-empty flux positions only.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from .flux import FluxPosition


@dataclass(frozen=True)
class SentenceSummary:
    sent_id: str
    n_words: int  # after preprocessing
    n_positions: int  # non-empty flux positions
    max_size: int | None
    mean_size: float | None
    max_weight: int | None
    mean_weight: float | None


def summarize_sentence(sent_id: str, n_words: int, positions: list[FluxPosition]) -> SentenceSummary:
    if not positions:
        return SentenceSummary(sent_id, n_words, 0, None, None, None, None)
    sizes = [p.size for p in positions]
    weights = [p.weight for p in positions]
    return SentenceSummary(
        sent_id=sent_id,
        n_words=n_words,
        n_positions=len(positions),
        max_size=max(sizes),
        mean_size=sum(sizes) / len(sizes),
        max_weight=max(weights),
        mean_weight=sum(weights) / len(weights),
    )


@dataclass
class Distribution:
    """Frequency table of a discrete metric over flux positions."""

    counts: Counter[int] = field(default_factory=Counter)

    def add(self, value: int) -> None:
        self.counts[value] += 1

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def mean(self) -> float | None:
        t = self.total
        return sum(k * c for k, c in self.counts.items()) / t if t else None

    @property
    def std(self) -> float | None:
        m, t = self.mean, self.total
        if m is None:
            return None
        return math.sqrt(sum(c * (k - m) ** 2 for k, c in self.counts.items()) / t)

    def tail(self, k: int) -> float | None:
        """P(X >= k) over all positions."""
        t = self.total
        return sum(c for v, c in self.counts.items() if v >= k) / t if t else None


@dataclass
class CorpusSummary:
    n_sentences: int = 0
    n_sentences_without_flux: int = 0
    n_warnings: int = 0
    size: Distribution = field(default_factory=Distribution)
    weight: Distribution = field(default_factory=Distribution)

    def add(self, positions: Iterable[FluxPosition], n_warnings: int = 0) -> None:
        self.n_sentences += 1
        self.n_warnings += n_warnings
        empty = True
        for p in positions:
            empty = False
            self.size.add(p.size)
            self.weight.add(p.weight)
        if empty:
            self.n_sentences_without_flux += 1
