"""Flux positions with size and weight (spec §5)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .matching import max_bipartite_matching
from .model import Dependency, ProcessedSentence


@dataclass(frozen=True)
class FluxPosition:
    position: int  # i: the gap between new words i and i+1
    deps: tuple[Dependency, ...]  # arcs crossing the gap, sorted by (left, right)
    size: int
    weight: int


def flux_weight(deps: Iterable[Dependency]) -> int:
    """Largest number of arcs sharing no endpoint = max matching left ends <-> right ends."""
    return max_bipartite_matching((d.left, d.right) for d in deps)


def compute_flux(ps: ProcessedSentence) -> list[FluxPosition]:
    """All non-empty flux positions of a processed sentence, in order."""
    out: list[FluxPosition] = []
    for i in range(1, ps.n):
        crossing = tuple(
            sorted((d for d in ps.deps if d.left <= i < d.right), key=lambda d: (d.left, d.right))
        )
        if not crossing:  # empty flux: excluded (spec §5)
            continue
        out.append(FluxPosition(position=i, deps=crossing, size=len(crossing), weight=flux_weight(crossing)))
    return out
