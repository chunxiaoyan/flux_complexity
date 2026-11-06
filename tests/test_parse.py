"""Stanza integration. Skipped when Stanza or its French model is not available."""

import sys

import pytest

from flux_complexity.parse import ParserUnavailable, StanzaParser


def test_missing_stanza_gives_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "stanza", None)  # makes `import stanza` fail
    with pytest.raises(ParserUnavailable, match="pip install"):
        StanzaParser(download=False).parse("Bonjour.")


@pytest.fixture(scope="module")
def parser():
    pytest.importorskip("stanza")
    p = StanzaParser(download=False)  # never download during tests
    try:
        p.parse("Test.")
    except ParserUnavailable as e:
        pytest.skip(f"French Stanza model not available: {e}")
    return p


def test_parse_text_into_ud_sentences(parser):
    sents = parser.parse("Il pleut. Je reste au lit.")
    assert [s.sent_id for s in sents] == ["s1", "s2"]
    assert all(s.scheme == "UD" for s in sents)
    assert [m.form for m in sents[1].mwts] == ["au"]
    assert sents[1].text == "Je reste au lit."
    assert parser.parse("   ") == []


def test_analyze_text_records_parser(parser):
    from flux_complexity.analysis import analyze_text

    res = analyze_text("Le chat de ma sœur dort.", parser)
    assert res.parser["stanza"] and res.parser["models"]["depparse"].endswith(".pt")
    (s,) = res.sentences
    assert [(p.size, p.weight) for p in s.positions] == [(1, 1), (2, 1), (3, 2), (4, 2), (1, 1)]
