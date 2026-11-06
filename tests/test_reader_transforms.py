"""Reader edge cases and preprocessing rules (spec §2, §3)."""

import pytest

from flux_complexity.core import (
    CutParataxis,
    RemoveFunctionWords,
    RemovePunct,
    parse_conllu,
    process,
)

from .conftest import make_conllu


def test_mwt_kept_for_display_and_words_used_for_computation(run):
    rows = [
        (1, "Il", "PRON", 2, "nsubj"),
        (2, "parle", "VERB", 0, "root"),
        ("3-4", "du"),
        (3, "de", "ADP", 5, "case"),
        (4, "le", "DET", 5, "det"),
        (5, "film", "NOUN", 2, "obl"),
    ]
    (sent,) = parse_conllu(make_conllu(rows), "UD")
    assert [w.form for w in sent.words] == ["Il", "parle", "de", "le", "film"]
    assert [(m.first, m.last, m.form) for m in sent.mwts] == [(3, 4, "du")]
    ps, pos = run(rows)
    assert ps.n == 5 and len(pos) == 4


def test_empty_nodes_are_ignored():
    text = (
        "# sent_id = e\n"
        "1\tA\ta\tNOUN\t_\t_\t0\troot\t_\t_\n"
        "1.1\tX\tx\tVERB\t_\t_\t_\t_\t0:root\t_\n"
        "2\tB\tb\tNOUN\t_\t_\t1\tnmod\t_\t_\n\n"
    )
    (sent,) = parse_conllu(text, "UD")
    assert [w.form for w in sent.words] == ["A", "B"]


def test_missing_sent_id_falls_back_to_index():
    text = "1\tA\ta\tNOUN\t_\t_\t0\troot\t_\t_\n\n1\tB\tb\tNOUN\t_\t_\t0\troot\t_\t_\n\n"
    assert [s.sent_id for s in parse_conllu(text, "SUD")] == ["1", "2"]


def test_unknown_scheme_rejected():
    with pytest.raises(ValueError):
        parse_conllu("", "XYZ")


def test_punct_chain_climbs_to_first_non_punct_ancestor(run):
    rows = [
        (1, "Oui", "INTJ", 0, "root"),
        (2, "(", "PUNCT", 1, "punct"),
        (3, "-", "PUNCT", 2, "punct"),
        (4, "bien", "ADV", 3, "advmod"),  # depends on punct whose head is punct
    ]
    ps, pos = run(rows)
    assert [(d.gov, d.dep) for d in ps.deps] == [(1, 2)]
    assert "reattached to Oui" in ps.warnings[0] and "'-' -> '('" in ps.warnings[0]


def test_punct_root_children_become_roots(run):
    rows = [
        (1, "a", "NOUN", 2, "dep"),
        (2, "!", "PUNCT", 0, "root"),
        (3, "b", "NOUN", 2, "dep"),
    ]
    ps, pos = run(rows)
    assert ps.deps == [] and pos == []
    assert len(ps.warnings) == 2 and all("reattached to root" in w for w in ps.warnings)


def test_punct_detected_by_upos_not_deprel(run):
    rows = [
        (1, "a", "NOUN", 0, "root"),
        (2, "b", "SYM", 1, "punct"),  # deprel punct but UPOS SYM -> kept
        (3, ",", "PUNCT", 1, "dep"),  # UPOS PUNCT -> removed
    ]
    ps, _ = run(rows)
    assert [ps.word(k).form for k in range(1, ps.n + 1)] == ["a", "b"]


def test_parataxis_subtype_is_cut_and_toggle(run):
    rows = [
        (1, "a", "VERB", 0, "root"),
        (2, "b", "VERB", 1, "parataxis:insert"),
    ]
    _, pos = run(rows)
    assert pos == []
    _, pos = run(rows, pipeline=(RemovePunct(),))
    assert [(p.size, p.weight) for p in pos] == [(1, 1)]
    # legacy mode: only the bare label is cut, subtypes are kept
    ps, pos = run(rows, pipeline=(RemovePunct(), CutParataxis(include_subtypes=False)))
    assert [(p.size, p.weight) for p in pos] == [(1, 1)]
    assert ps.pipeline == ("remove_punct", "cut_parataxis_exact")
    _, pos = run([(1, "a", "VERB", 0, "root"), (2, "b", "VERB", 1, "parataxis")],
                 pipeline=(RemovePunct(), CutParataxis(include_subtypes=False)))  # fmt: skip
    assert pos == []


def test_function_word_stub_is_ud_only():
    rows = [(1, "a", "NOUN", 0, "root")]
    (ud,) = parse_conllu(make_conllu(rows), "UD")
    with pytest.raises(NotImplementedError):
        process(ud, pipeline=(RemovePunct(), CutParataxis(), RemoveFunctionWords()))
    (sud,) = parse_conllu(make_conllu(rows), "SUD")
    with pytest.raises(ValueError, match="only applies to"):
        process(sud, pipeline=(RemovePunct(), RemoveFunctionWords()))


def test_pipeline_names_recorded(run):
    ps, _ = run([(1, "a", "NOUN", 0, "root")])
    assert ps.pipeline == ("remove_punct", "cut_parataxis")
