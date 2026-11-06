"""Shared helpers: build small CoNLL-U sentences inline."""

from __future__ import annotations

import pytest

from flux_complexity.core import compute_flux, parse_conllu, process


def make_conllu(rows: list[tuple], sent_id: str = "s1") -> str:
    """rows: (id, form, upos, head, deprel); id may be '3-4' for an MWT line."""
    lines = [f"# sent_id = {sent_id}"]
    for r in rows:
        tid, form = r[0], r[1]
        if isinstance(tid, str) and "-" in tid:
            lines.append(f"{tid}\t{form}\t_\t_\t_\t_\t_\t_\t_\t_")
            continue
        _, _, upos, head, deprel = r
        lines.append(f"{tid}\t{form}\t{form.lower()}\t{upos}\t_\t_\t{head}\t{deprel}\t_\t_")
    return "\n".join(lines) + "\n\n"


@pytest.fixture
def run():
    """rows -> (processed sentence, flux positions)."""

    def _run(rows, scheme="UD", **kw):
        (sent,) = parse_conllu(make_conllu(rows), scheme)
        ps = process(sent, **kw)
        return ps, compute_flux(ps)

    return _run
