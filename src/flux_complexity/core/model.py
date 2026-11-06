"""Data model shared by the reader, the transforms and the flux computation.

Two numbering systems coexist (see docs/spec.md §3.1):
- *original* ids: the integer ids of the CoNLL-U file (punctuation included);
- *new* ids: 1..n after preprocessing removed words (punctuation does not take a slot).
Flux positions are defined on new ids; display maps them back to original ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SCHEMES = ("UD", "SUD")


@dataclass(frozen=True)
class Word:
    """A syntactic word (integer-id line of a CoNLL-U sentence), original numbering."""

    id: int
    form: str
    lemma: str
    upos: str
    head: int | None  # None when HEAD is "_"
    deprel: str


@dataclass(frozen=True)
class MultiWordToken:
    """A surface token covering several syntactic words, e.g. fr. "du" = de + le (ids 3-4)."""

    first: int
    last: int
    form: str


@dataclass
class Sentence:
    sent_id: str
    words: list[Word]
    scheme: str
    text: str | None = None
    mwts: list[MultiWordToken] = field(default_factory=list)

    def word(self, orig_id: int) -> Word:
        return self.words[orig_id - 1]


@dataclass(frozen=True)
class Dependency:
    """An arc taking part in fluxes, in *new* numbering."""

    gov: int
    dep: int
    deprel: str

    @property
    def left(self) -> int:
        return min(self.gov, self.dep)

    @property
    def right(self) -> int:
        return max(self.gov, self.dep)

    @property
    def gov_on_left(self) -> bool:
        return self.gov < self.dep


@dataclass
class ProcessedSentence:
    """A sentence after the preprocessing pipeline: renumbered words + flux-relevant arcs."""

    source: Sentence
    new2orig: list[int]  # new2orig[k-1] = original id of new word k
    deps: list[Dependency]
    warnings: list[str]
    pipeline: tuple[str, ...]

    @property
    def n(self) -> int:
        return len(self.new2orig)

    def word(self, new_id: int) -> Word:
        return self.source.word(self.new2orig[new_id - 1])
