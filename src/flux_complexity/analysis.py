"""Beginner-page analysis (spec §8): sentences -> positions with tails, colour levels
and a mapping back to the surface text (punctuation shown, MWTs as one token).

This module has no web code; the API (stage 4) serialises AnalysisResult.to_dict().
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from .core import DEFAULT_PIPELINE, Sentence, Transform, compute_flux, parse_conllu, process
from .norms import DEFAULT_NORMS, DEFAULT_THRESHOLDS, METRICS, Norm


@dataclass(frozen=True)
class SurfaceToken:
    index: int  # 0-based position in the displayed sentence
    form: str
    first_id: int  # original word ids covered (equal unless an MWT such as "au")
    last_id: int
    is_punct: bool
    space_after: bool


@dataclass(frozen=True)
class PositionResult:
    position: int  # flux position i (new numbering, punctuation excluded)
    left_id: int  # original ids of the two words around the gap
    right_id: int
    left_token: int  # surface token indices of those words
    right_token: int
    inside_token: bool  # both words belong to the same MWT (e.g. à|le inside "au")
    size: int
    weight: int
    size_tail: float  # P(size >= value) in the norm
    weight_tail: float
    size_level: int  # colour level 0..3
    weight_level: int
    deps: tuple[tuple[int, int, str], ...]  # (gov, dep, deprel) in original ids


@dataclass(frozen=True)
class TreeWord:
    """One syntactic word of the dependency tree, for drawing (original ids).

    head/deprel are those used for the computation (a word whose head was punctuation
    is shown reattached, spec §3.1). status says whether its incoming arc is counted:
    "flux" (counted), "root", "punct" (punctuation, not counted) or "cut" (cut
    parataxis, not counted).
    """

    id: int
    form: str
    upos: str
    head: int
    deprel: str
    status: str


@dataclass
class SentenceResult:
    sent_id: str
    text: str
    tokens: list[SurfaceToken]
    positions: list[PositionResult]
    warnings: list[str]
    words: list[TreeWord] = field(default_factory=list)

    def peak(self, metric: str) -> PositionResult | None:
        """The position with the highest value of metric (first one on ties)."""
        if not self.positions:
            return None
        return max(self.positions, key=lambda p: (getattr(p, metric), -p.position))

    @property
    def max_size(self) -> int | None:
        p = self.peak("size")
        return p.size if p else None

    @property
    def max_weight(self) -> int | None:
        p = self.peak("weight")
        return p.weight if p else None


@dataclass
class AnalysisResult:
    norm: str
    scheme: str
    pipeline: list[str]
    thresholds: dict[str, list[float]]
    sentences: list[SentenceResult] = field(default_factory=list)
    parser: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        for sd, s in zip(d["sentences"], self.sentences):
            sd["max_size"], sd["max_weight"] = s.max_size, s.max_weight
        return d


def surface_tokens(sent: Sentence) -> tuple[list[SurfaceToken], dict[int, int]]:
    """Surface tokens of a sentence and the map original word id -> token index."""
    mwt_at = {m.first: m for m in sent.mwts}
    tokens: list[SurfaceToken] = []
    word2tok: dict[int, int] = {}
    i = 1
    while i <= len(sent.words):
        m = mwt_at.get(i)
        if m is not None:
            ids = range(m.first, m.last + 1)
            punct = all(sent.word(k).upos == "PUNCT" for k in ids)
            tok = SurfaceToken(len(tokens), m.form, m.first, m.last, punct, m.space_after)
            i = m.last + 1
        else:
            w = sent.word(i)
            ids = range(i, i + 1)
            tok = SurfaceToken(len(tokens), w.form, i, i, w.upos == "PUNCT", w.space_after)
            i += 1
        for k in ids:
            word2tok[k] = tok.index
        tokens.append(tok)
    return tokens, word2tok


def tree_words(sent: Sentence, ps) -> list[TreeWord]:
    """The tree to draw: counted arcs as computed, other arcs as annotated."""
    counted = {ps.new2orig[d.dep - 1]: d for d in ps.deps}
    out = []
    for w in sent.words:
        d = counted.get(w.id)
        if d is not None:
            out.append(TreeWord(w.id, w.form, w.upos, ps.new2orig[d.gov - 1], d.deprel, "flux"))
            continue
        status = "root" if w.head == 0 else ("punct" if w.upos == "PUNCT" else "cut")
        out.append(TreeWord(w.id, w.form, w.upos, w.head or 0, w.deprel, status))
    return out


def render_text(tokens: Sequence[SurfaceToken]) -> str:
    return "".join(t.form + (" " if t.space_after else "") for t in tokens).rstrip()


def analyze_sentences(
    sentences: Sequence[Sentence],
    norm: Norm,
    pipeline: Sequence[Transform] = DEFAULT_PIPELINE,
    thresholds: dict[str, Sequence[float]] | None = None,
) -> AnalysisResult:
    th = {m: tuple((thresholds or {}).get(m, DEFAULT_THRESHOLDS[m])) for m in METRICS}
    result = AnalysisResult(
        norm=norm.name,
        scheme=norm.scheme,
        pipeline=[t.name for t in pipeline],
        thresholds={m: list(v) for m, v in th.items()},
    )
    for sent in sentences:
        if sent.scheme != norm.scheme:
            raise ValueError(
                f"sentence {sent.sent_id} is {sent.scheme} but norm {norm.name} is {norm.scheme}"
            )
        ps = process(sent, pipeline)
        tokens, word2tok = surface_tokens(sent)
        positions = []
        for p in compute_flux(ps):
            a, b = ps.new2orig[p.position - 1], ps.new2orig[p.position]
            positions.append(
                PositionResult(
                    position=p.position,
                    left_id=a,
                    right_id=b,
                    left_token=word2tok[a],
                    right_token=word2tok[b],
                    inside_token=word2tok[a] == word2tok[b],
                    size=p.size,
                    weight=p.weight,
                    size_tail=round(norm.tail("size", p.size), 6),
                    weight_tail=round(norm.tail("weight", p.weight), 6),
                    size_level=norm.level("size", p.size, th["size"]),
                    weight_level=norm.level("weight", p.weight, th["weight"]),
                    deps=tuple(
                        (ps.new2orig[d.gov - 1], ps.new2orig[d.dep - 1], d.deprel) for d in p.deps
                    ),
                )
            )
        result.sentences.append(
            SentenceResult(
                sent_id=sent.sent_id,
                text=sent.text or render_text(tokens),
                tokens=tokens,
                positions=positions,
                warnings=list(ps.warnings),
                words=tree_words(sent, ps),
            )
        )
    return result


def analyze_conllu(text: str, scheme: str, norm: Norm | None = None, **kw) -> AnalysisResult:
    """Uploaded CoNLL-U (UD or SUD) -> analysis against the scheme's default norm."""
    norm = norm or Norm.builtin(DEFAULT_NORMS[scheme])
    return analyze_sentences(parse_conllu(text, scheme), norm, **kw)


def analyze_text(text: str, parser, norm: Norm | None = None, **kw) -> AnalysisResult:
    """Raw text -> Stanza (UD) -> analysis against a UD norm (default UD Sequoia)."""
    norm = norm or Norm.builtin(DEFAULT_NORMS["UD"])
    if norm.scheme != "UD":
        raise ValueError("raw text is parsed into UD; use a UD norm (spec §1)")
    result = analyze_sentences(parser.parse(text), norm, **kw)
    info = parser.info()
    result.parser = {"language": info.language, "stanza": info.stanza_version, "models": info.models}
    return result
