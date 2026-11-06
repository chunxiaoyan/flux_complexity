"""Preprocessing pipeline (spec §3).

Transforms operate on a mutable working state expressed in *original* ids; the
pipeline renumbers the remaining words at the end. Each transform declares the
annotation schemes it applies to; using one on another scheme is an error.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .model import SCHEMES, Dependency, ProcessedSentence, Sentence


@dataclass
class WorkingState:
    sentence: Sentence
    heads: dict[int, int | None]  # original id -> original head id (0 = root)
    removed: set[int] = field(default_factory=set)  # words removed from the sequence
    cut: set[int] = field(default_factory=set)  # dependents whose incoming arc is cut
    warnings: list[str] = field(default_factory=list)

    def warn(self, msg: str) -> None:
        self.warnings.append(f"[{self.sentence.sent_id}] {msg}")


class Transform:
    name: str = "transform"
    schemes: frozenset[str] = frozenset(SCHEMES)

    def apply(self, state: WorkingState) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class RemovePunct(Transform):
    """Remove UPOS=PUNCT words; reattach their dependents to the nearest non-punct ancestor."""

    name = "remove_punct"

    def apply(self, state: WorkingState) -> None:
        s = state.sentence
        punct = {w.id for w in s.words if w.upos == "PUNCT"}
        state.removed |= punct
        for w in s.words:
            if w.id in state.removed:
                continue
            h = state.heads[w.id]
            if h not in punct:
                continue
            path: list[str] = []
            seen: set[int] = set()
            while h in punct:  # climb through punctuation ancestors
                if h in seen:  # malformed cycle made only of punctuation
                    h = None
                    break
                seen.add(h)
                path.append(s.word(h).form)
                h = state.heads[h]
            target = "root" if h == 0 else ("nothing (no head)" if h is None else s.word(h).form)
            state.warn(
                f"'{w.form}' (id {w.id}) depended on punctuation "
                f"{' -> '.join(repr(p) for p in path)}; reattached to {target}"
            )
            state.heads[w.id] = h


class CutParataxis(Transform):
    """Remove parataxis arcs.

    include_subtypes=False (default, spec §3.2): only the bare label 'parataxis';
    subtypes such as 'parataxis:insert' are kept. This is what the legacy
    update_parataxis_gov did (it reproduces the saved experimental_data_*.xlsx exactly).
    include_subtypes=True: 'parataxis' and every 'parataxis:*'.
    """

    def __init__(self, include_subtypes: bool = False) -> None:
        self.include_subtypes = include_subtypes
        self.name = "cut_parataxis_all" if include_subtypes else "cut_parataxis"

    def matches(self, deprel: str) -> bool:
        return (deprel.split(":")[0] if self.include_subtypes else deprel) == "parataxis"

    def apply(self, state: WorkingState) -> None:
        for w in state.sentence.words:
            if w.id not in state.removed and self.matches(w.deprel):
                state.cut.add(w.id)


class RemoveFunctionWords(Transform):
    """Placeholder for the UD-only 'no functional words' mode (not implemented in v1)."""

    name = "remove_function_words"
    schemes = frozenset({"UD"})

    def apply(self, state: WorkingState) -> None:
        raise NotImplementedError("remove_function_words is planned but not implemented in v1")


DEFAULT_PIPELINE: tuple[Transform, ...] = (RemovePunct(), CutParataxis())

PARATAXIS_MODES = {
    "exact": "cut only the bare label 'parataxis', keep parataxis:* subtypes (default, legacy)",
    "all": "cut parataxis and all parataxis:* subtypes",
    "keep": "do not cut parataxis",
}


def build_pipeline(parataxis: str = "exact") -> tuple[Transform, ...]:
    """The v1 pipeline for a given parataxis mode (spec §3.2)."""
    if parataxis == "exact":
        return (RemovePunct(), CutParataxis())
    if parataxis == "all":
        return (RemovePunct(), CutParataxis(include_subtypes=True))
    if parataxis == "keep":
        return (RemovePunct(),)
    raise ValueError(f"parataxis mode must be one of {list(PARATAXIS_MODES)}")


def process(sentence: Sentence, pipeline: Sequence[Transform] = DEFAULT_PIPELINE) -> ProcessedSentence:
    for t in pipeline:
        if sentence.scheme not in t.schemes:
            raise ValueError(
                f"transform {t.name!r} only applies to {sorted(t.schemes)}, "
                f"not to {sentence.scheme} (sentence {sentence.sent_id})"
            )
    state = WorkingState(sentence=sentence, heads={w.id: w.head for w in sentence.words})
    for t in pipeline:
        t.apply(state)

    kept = [w.id for w in sentence.words if w.id not in state.removed]
    orig2new = {o: k for k, o in enumerate(kept, start=1)}
    deps: list[Dependency] = []
    for o in kept:
        h = state.heads[o]
        if h is None:
            state.warn(f"'{sentence.word(o).form}' (id {o}) has no head; ignored")
            continue
        if h == 0 or o in state.cut:
            continue
        if h not in orig2new:
            state.warn(f"'{sentence.word(o).form}' (id {o}) points to removed word {h}; ignored")
            continue
        deps.append(Dependency(gov=orig2new[h], dep=orig2new[o], deprel=sentence.word(o).deprel))
    return ProcessedSentence(
        source=sentence,
        new2orig=kept,
        deps=deps,
        warnings=state.warnings,
        pipeline=tuple(t.name for t in pipeline),
    )
