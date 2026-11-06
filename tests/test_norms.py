"""Norm building, tail proportions and colour levels (spec §7, §8)."""

import json

import pytest

from flux_complexity.cli import main
from flux_complexity.core import build_pipeline
from flux_complexity.norms import DEFAULT_UD_NORM, FORMAT, Norm, build_norm, list_builtin, write_norm

from .conftest import make_conllu

EX1 = [
    (1, "Le", "DET", 2, "det"),
    (2, "chat", "NOUN", 6, "nsubj"),
    (3, "de", "ADP", 5, "case"),
    (4, "ma", "DET", 5, "det"),
    (5, "sœur", "NOUN", 2, "nmod"),
    (6, "dort", "VERB", 0, "root"),
    (7, ".", "PUNCT", 6, "punct"),
]
PARA = [
    (1, "Il", "PRON", 2, "nsubj"),
    (2, "pleut", "VERB", 0, "root"),
    (3, "je", "PRON", 4, "nsubj"),
    (4, "reste", "VERB", 2, "parataxis"),
]


@pytest.fixture
def small_norm(tmp_path):
    f = tmp_path / "c.conllu"
    f.write_text(make_conllu(EX1, "a") + make_conllu(PARA, "b"), encoding="utf-8")
    return build_norm([f], "UD", "test", ["test"], "r0", build_pipeline("exact"))


def test_build_norm_counts(small_norm):
    # EX1: weights 1,1,2,2,1 sizes 1,2,3,4,1 ; PARA: positions 1 and 3 (2 is empty), all 1
    d = small_norm
    assert d["format"] == FORMAT and d["n_sentences"] == 2 and d["n_positions"] == 7
    assert d["pipeline"] == ["remove_punct", "cut_parataxis"]
    assert d["metrics"]["weight"]["counts"] == {"1": 5, "2": 2}
    assert d["metrics"]["size"]["counts"] == {"1": 4, "2": 1, "3": 1, "4": 1}
    assert d["metrics"]["weight"]["tail"] == {"1": 1.0, "2": round(2 / 7, 6)}


def test_tail_and_levels(small_norm, tmp_path):
    path = tmp_path / "n.json"
    write_norm(small_norm, path)
    norm = Norm.load(path)
    assert norm.tail("weight", 1) == 1.0
    assert norm.tail("weight", 2) == pytest.approx(2 / 7)
    assert norm.tail("weight", 3) == 0.0  # beyond observed max: rarer than anything
    assert norm.tail("size", 4) == pytest.approx(1 / 7)
    assert norm.level("weight", 1) == 0
    assert norm.level("weight", 2) == 0  # 28.6% > 10%
    assert norm.level("weight", 3) == 3
    assert norm.level("size", 4, thresholds=(0.2, 0.15, 0.1)) == 2  # 14.3%
    with pytest.raises(ValueError):
        norm.tail("mdd", 1)


def test_load_rejects_foreign_json(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"format": "other"}), encoding="utf-8")
    with pytest.raises(ValueError):
        Norm.load(p)


def test_builtin_norms_present_and_consistent():
    names = list_builtin()
    expected = {f"{s}_French-{t}" for s in ("UD", "SUD") for t in ("Sequoia", "ParisStories", "Rhapsodie", "merged")}
    assert expected <= set(names)
    assert DEFAULT_UD_NORM in names
    for name in expected:
        norm = Norm.builtin(name)
        d = norm.data
        assert d["scheme"] == name.split("_")[0] and d["release"] == "r2.18"
        assert d["pipeline"] == ["remove_punct", "cut_parataxis"]
        for metric in ("size", "weight"):
            assert sum(d["metrics"][metric]["counts"].values()) == d["n_positions"]
            assert norm.tail(metric, 1) == 1.0
    for scheme in ("UD", "SUD"):
        merged = Norm.builtin(f"{scheme}_French-merged").data
        parts = [Norm.builtin(f"{scheme}_French-{t}").data for t in ("Sequoia", "ParisStories", "Rhapsodie")]
        assert merged["n_positions"] == sum(p["n_positions"] for p in parts)
        assert merged["n_sentences"] == sum(p["n_sentences"] for p in parts)


def test_ud_and_sud_cover_same_sentences():
    for t in ("Sequoia", "ParisStories", "Rhapsodie"):
        ud, sud = Norm.builtin(f"UD_French-{t}").data, Norm.builtin(f"SUD_French-{t}").data
        assert ud["n_sentences"] == sud["n_sentences"]


def test_cli_norms_show(capsys):
    assert main(["norms", "show", DEFAULT_UD_NORM]) == 0
    out = capsys.readouterr().out
    assert "UD_French-Sequoia" in out and "weight=1" in out and "level=0" in out
    assert main(["norms", "list"]) == 0
    assert "SUD_French-merged" in capsys.readouterr().out
