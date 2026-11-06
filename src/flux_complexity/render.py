"""Plain-terminal rendering of an AnalysisResult (preview of the beginner page).

Gaps whose colour level is > 0 get a marker placed just before the word on the
right of the gap: ░ light, ▒ medium, ▓ dark. A gap inside an MWT (e.g. à|le in
"au") is shown as a marker after that token.
"""

from __future__ import annotations

from .analysis import AnalysisResult, SentenceResult

MARKS = {1: "░", 2: "▒", 3: "▓"}


def render_sentence(s: SentenceResult, metric: str) -> str:
    before: dict[int, int] = {}  # token index -> level of the gap just before it
    after: dict[int, int] = {}  # MWT token index -> level of a gap inside it
    for p in s.positions:
        lvl = getattr(p, f"{metric}_level")
        if not lvl:
            continue
        target = after if p.inside_token else before
        key = p.left_token if p.inside_token else p.right_token
        target[key] = max(lvl, target.get(key, 0))
    out = []
    for t in s.tokens:
        if t.index in before:
            out.append(MARKS[before[t.index]])
        out.append(t.form)
        if t.index in after:
            out.append(MARKS[after[t.index]])
        if t.space_after:
            out.append(" ")
    return "".join(out).rstrip()


def render(result: AnalysisResult, metric: str = "weight") -> str:
    other = "size" if metric == "weight" else "weight"
    th = " / ".join(f"{x:.0%}" for x in result.thresholds[metric])
    lines = [
        f"norm: {result.norm} ({result.scheme})   colour by: {metric}   "
        f"thresholds P(>=) <= {th}   marks: ░ light ▒ medium ▓ dark",
    ]
    if result.parser:
        lines.append(f"parser: stanza {result.parser['stanza']} ({result.parser['language']}), "
                     f"depparse={result.parser['models'].get('depparse', '?')}")  # fmt: skip
    for s in result.sentences:
        lines.append("")
        lines.append(f"[{s.sent_id}] {render_sentence(s, metric)}")
        peak = s.peak(metric)
        if peak is None:
            lines.append("    (no flux)")
            continue
        tail = getattr(peak, f"{metric}_tail")
        lines.append(
            f"    max {metric} = {getattr(peak, metric)} "
            f"between '{s.tokens[peak.left_token].form}' and '{s.tokens[peak.right_token].form}'"
            f" — {tail:.1%} of positions in {result.norm} reach this value"
        )
        for p in s.positions:
            lvl = getattr(p, f"{metric}_level")
            if not lvl:
                continue
            left, right = s.tokens[p.left_token].form, s.tokens[p.right_token].form
            gap = f"{left}|{right}" if not p.inside_token else f"{left} (inside)"
            lines.append(
                f"    {MARKS[lvl]} pos {p.position:<3} {gap:<24} {metric}={getattr(p, metric)} "
                f"(P>={getattr(p, f'{metric}_tail'):.3f})  {other}={getattr(p, other)}"
            )
        for w in s.warnings:
            lines.append(f"    warning: {w}")
    return "\n".join(lines)
