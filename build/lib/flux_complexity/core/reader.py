"""CoNLL-U reading (spec §2): syntactic words only, MWTs kept for display, empty nodes ignored."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import conllu

from .model import SCHEMES, MultiWordToken, Sentence, Word


def _check_scheme(scheme: str) -> str:
    if scheme not in SCHEMES:
        raise ValueError(f"scheme must be one of {SCHEMES}, got {scheme!r}")
    return scheme


def _space_after(tok: conllu.Token) -> bool:
    misc = tok.get("misc") or {}
    return misc.get("SpaceAfter") != "No"


def _to_sentence(tokenlist: conllu.TokenList, index: int, scheme: str) -> Sentence:
    words: list[Word] = []
    mwts: list[MultiWordToken] = []
    for tok in tokenlist:
        tid = tok["id"]
        if isinstance(tid, int):
            if tid != len(words) + 1:
                raise ValueError(
                    f"sentence {tokenlist.metadata.get('sent_id', index)}: "
                    f"word ids must be 1..n in order, found {tid} after {len(words)}"
                )
            head = tok["head"]
            words.append(
                Word(
                    id=tid,
                    form=tok["form"],
                    lemma=tok["lemma"] or "",
                    upos=tok["upos"] or "",
                    head=head if isinstance(head, int) else None,
                    deprel=tok["deprel"] or "",
                    space_after=_space_after(tok),
                )
            )
        elif isinstance(tid, tuple) and len(tid) == 3 and tid[1] == "-":
            mwts.append(
                MultiWordToken(first=tid[0], last=tid[2], form=tok["form"], space_after=_space_after(tok))
            )
        # empty nodes (8.1) are ignored
    meta = tokenlist.metadata
    return Sentence(
        sent_id=str(meta.get("sent_id", index)),
        words=words,
        scheme=scheme,
        text=meta.get("text"),
        mwts=mwts,
    )


def _safe(tokenlist: conllu.TokenList, index: int, scheme: str) -> Sentence:
    try:
        return _to_sentence(tokenlist, index, scheme)
    except KeyError as e:  # line with missing columns
        sid = tokenlist.metadata.get("sent_id", index)
        raise ValueError(f"sentence {sid}: malformed line (missing column {e})") from None


def parse_conllu(text: str, scheme: str) -> list[Sentence]:
    """Parse a CoNLL-U string. Sentences without sent_id get their 1-based index."""
    _check_scheme(scheme)
    try:
        tokenlists = conllu.parse(text)
    except conllu.exceptions.ParseException as e:
        raise ValueError(str(e)) from None
    return [_safe(tl, i, scheme) for i, tl in enumerate(tokenlists, start=1)]


def read_conllu(path: str | Path, scheme: str) -> Iterator[Sentence]:
    """Stream sentences from a CoNLL-U file."""
    _check_scheme(scheme)
    with open(path, encoding="utf-8") as fh:
        for i, tl in enumerate(conllu.parse_incr(fh), start=1):
            yield _safe(tl, i, scheme)
