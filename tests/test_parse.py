"""Stanza integration. Skipped when Stanza or its French model is not available."""

import sys

import pytest

from flux_complexity import parse as parse_mod
from flux_complexity.parse import ParserUnavailable, StanzaParser


def test_missing_stanza_gives_clear_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "stanza", None)  # makes `import stanza` fail
    with pytest.raises(ParserUnavailable, match="uv tool install"):
        StanzaParser(download=False).parse("Bonjour.")
    with pytest.raises(ParserUnavailable, match="not installed"):
        StanzaParser(download=False).info()  # used by `fluxcalc setup`: no raw ImportError


class FakeStanza:
    """Stands in for the stanza module: no model until download() is called."""

    def __init__(self, hf_cache, have_model=False):
        self.hf_cache, self.have_model, self.downloads = hf_cache, have_model, 0

    def download(self, lang, **kw):
        self.downloads += 1
        (self.hf_cache / f"models--stanfordnlp--stanza-{lang}" / "blobs").mkdir(parents=True, exist_ok=True)
        self.have_model = True

    def Pipeline(self, lang, **kw):  # noqa: N802 (stanza's name)
        assert kw["download_method"] is None  # never let Stanza go to the network by itself
        if not self.have_model:
            raise FileNotFoundError("resources.json")
        return object()


@pytest.fixture
def fake_stanza(tmp_path, monkeypatch):
    pytest.importorskip("huggingface_hub")
    from huggingface_hub import constants

    monkeypatch.setattr(constants, "HF_HUB_CACHE", str(tmp_path))
    fake = FakeStanza(tmp_path)
    monkeypatch.setattr(parse_mod, "_import_stanza", lambda: fake)
    return fake


def test_local_model_is_used_without_network(fake_stanza):
    fake_stanza.have_model = True
    StanzaParser()._pipeline()
    assert fake_stanza.downloads == 0


def test_download_removes_the_hf_copy_it_created(fake_stanza, tmp_path):
    StanzaParser()._pipeline()
    assert fake_stanza.downloads == 1
    assert not (tmp_path / "models--stanfordnlp--stanza-fr").exists()  # no second 320 MB copy


def test_download_keeps_a_preexisting_hf_copy(fake_stanza, tmp_path):
    mine = tmp_path / "models--stanfordnlp--stanza-fr"
    mine.mkdir()
    StanzaParser()._pipeline()
    assert mine.exists()  # not ours: left alone (fluxcalc setup --remove-duplicate deletes it on request)


def test_no_download_mode_reports_the_folder(fake_stanza, tmp_path):
    with pytest.raises(ParserUnavailable, match="no Stanza model"):
        StanzaParser(download=False, model_dir=str(tmp_path / "models"))._pipeline()
    assert fake_stanza.downloads == 0


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
