"""Beginner analysis: surface mapping, levels, scheme checks, rendering (no parser needed)."""

import json

import pytest

from flux_complexity.analysis import analyze_conllu, surface_tokens
from flux_complexity.core import parse_conllu
from flux_complexity.norms import Norm
from flux_complexity.render import render, render_sentence

from .conftest import make_conllu

# "Il pleut, je reste au lit." as Stanza outputs it (au = à + le, SpaceAfter=No)
AU = """# sent_id = s1
# text = Il pleut, je reste au lit.
1\tIl\til\tPRON\t_\t_\t2\tnsubj\t_\t_
2\tpleut\tpleuvoir\tVERB\t_\t_\t0\troot\t_\tSpaceAfter=No
3\t,\t,\tPUNCT\t_\t_\t5\tpunct\t_\t_
4\tje\tje\tPRON\t_\t_\t5\tnsubj\t_\t_
5\treste\trester\tVERB\t_\t_\t2\tconj\t_\t_
6-7\tau\t_\t_\t_\t_\t_\t_\t_\t_
6\tà\tà\tADP\t_\t_\t8\tcase\t_\t_
7\tle\tle\tDET\t_\t_\t8\tdet\t_\t_
8\tlit\tlit\tNOUN\t_\t_\t5\tobl\t_\tSpaceAfter=No
9\t.\t.\tPUNCT\t_\t_\t2\tpunct\t_\tSpaceAfter=No

"""


def test_surface_tokens_mwt_and_punct():
    (sent,) = parse_conllu(AU, "UD")
    tokens, word2tok = surface_tokens(sent)
    assert [t.form for t in tokens] == ["Il", "pleut", ",", "je", "reste", "au", "lit", "."]
    assert [t.is_punct for t in tokens] == [False, False, True, False, False, False, False, True]
    assert word2tok[6] == word2tok[7] == 5
    assert (tokens[5].first_id, tokens[5].last_id) == (6, 7)


def test_positions_map_back_to_surface():
    res = analyze_conllu(AU, "UD")
    (s,) = res.sentences
    assert s.text == "Il pleut, je reste au lit."
    by_pos = {p.position: p for p in s.positions}
    # new ids: Il1 pleut2 je3 reste4 à5 le6 lit7 ; gap pleut|je skips the comma
    p2 = by_pos[2]
    assert (p2.left_id, p2.right_id, p2.left_token, p2.right_token) == (2, 4, 1, 3)
    assert not p2.inside_token
    p5 = by_pos[5]  # à|le inside "au"
    assert (p5.left_id, p5.right_id, p5.inside_token, p5.left_token) == (6, 7, True, 5)
    assert p5.deps == ((5, 8, "obl"), (8, 6, "case"))


def test_tree_words_for_drawing():
    (s,) = analyze_conllu(AU, "UD").sentences
    tree = {w.id: (w.form, w.upos, w.head, w.deprel, w.status) for w in s.words}
    assert len(tree) == 9  # syntactic words: "au" is à + le
    assert tree[2] == ("pleut", "VERB", 0, "root", "root")
    assert tree[3] == (",", "PUNCT", 5, "punct", "punct")
    assert tree[6] == ("à", "ADP", 8, "case", "flux")
    # every counted arc is exactly a dependency crossing some flux position
    crossing = {(g, d) for p in s.positions for g, d, _ in p.deps}
    assert {(w.head, w.id) for w in s.words if w.status == "flux"} == crossing


def test_tree_words_cut_parataxis_and_reattachment():
    rows = [
        (1, "Il", "PRON", 2, "nsubj"),
        (2, "dort", "VERB", 0, "root"),
        (3, "(", "PUNCT", 2, "punct"),
        (4, "vite", "ADV", 3, "advmod"),
        (5, "je", "PRON", 6, "nsubj"),
        (6, "pense", "VERB", 2, "parataxis"),
    ]
    text = make_conllu(rows)
    (s,) = analyze_conllu(text, "UD").sentences
    tree = {w.id: (w.head, w.status) for w in s.words}
    assert tree[6] == (2, "cut")  # parataxis is drawn but not counted
    assert tree[4] == (2, "flux")  # child of "(" is drawn reattached, as computed
    assert tree[3] == (2, "punct")


def test_levels_and_tails_against_default_norm():
    res = analyze_conllu(AU, "UD")
    norm = Norm.builtin("UD_French-Sequoia")
    for p in res.sentences[0].positions:
        assert p.weight_tail == pytest.approx(norm.tail("weight", p.weight), abs=1e-6)
        assert p.weight_level == norm.level("weight", p.weight)
        assert p.size_level == norm.level("size", p.size)
    assert res.norm == "UD_French-Sequoia" and res.thresholds["weight"] == [0.4, 0.05, 0.01]


def test_sud_upload_uses_sud_norm_and_scheme_mismatch_rejected():
    assert analyze_conllu(AU, "SUD").norm == "SUD_French-Sequoia"
    with pytest.raises(ValueError, match="is UD but norm"):
        analyze_conllu(AU, "UD", Norm.builtin("SUD_French-Sequoia"))


def test_custom_thresholds():
    res = analyze_conllu(AU, "UD", thresholds={"weight": (1.0, 1.0, 1.0)})
    assert all(p.weight_level == 3 for p in res.sentences[0].positions)


def test_to_dict_is_json_serialisable():
    d = analyze_conllu(AU, "UD").to_dict()
    s = json.loads(json.dumps(d, ensure_ascii=False))["sentences"][0]
    # every gap of this sentence has arcs sharing an endpoint -> weight 1; size peaks at le|lit
    assert (s["max_weight"], s["max_size"]) == (1, 3) and s["tokens"][5]["form"] == "au"


def test_render_marks():
    assert render_sentence(analyze_conllu(AU, "UD").sentences[0], "weight") == "Il pleut, je reste au lit."
    # force every gap to dark: marker before the right word, after "au" for the gap inside it,
    # and after the comma for pleut|je (the gap spans the punctuation)
    res = analyze_conllu(AU, "UD", thresholds={"weight": (1.0, 1.0, 1.0)})
    assert render_sentence(res.sentences[0], "weight") == "Il ▓pleut, ▓je ▓reste ▓au▓ ▓lit."
    out = render(res, "size")
    assert "colour by: size" in out and "max size" in out
