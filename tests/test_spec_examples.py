"""The three worked examples of docs/spec.md §6, number for number."""

from flux_complexity.core import summarize_sentence


def table(positions):
    return [(p.position, p.size, p.weight) for p in positions]


def test_example1_basic(run):
    rows = [
        (1, "Le", "DET", 2, "det"),
        (2, "chat", "NOUN", 6, "nsubj"),
        (3, "de", "ADP", 5, "case"),
        (4, "ma", "DET", 5, "det"),
        (5, "sœur", "NOUN", 2, "nmod"),
        (6, "dort", "VERB", 0, "root"),
        (7, ".", "PUNCT", 6, "punct"),
    ]
    ps, pos = run(rows)
    assert ps.n == 6
    assert table(pos) == [(1, 1, 1), (2, 2, 1), (3, 3, 2), (4, 4, 2), (5, 1, 1)]
    assert [(d.left, d.right) for d in pos[3].deps] == [(2, 5), (2, 6), (3, 5), (4, 5)]
    s = summarize_sentence("s1", ps.n, pos)
    assert (s.max_size, s.mean_size, s.max_weight, s.mean_weight) == (4, 2.2, 2, 1.4)
    assert ps.warnings == []


def test_example2_parataxis_cut_and_empty_flux(run):
    rows = [
        (1, "Il", "PRON", 2, "nsubj"),
        (2, "pleut", "VERB", 0, "root"),
        (3, ",", "PUNCT", 5, "punct"),
        (4, "je", "PRON", 5, "nsubj"),
        (5, "reste", "VERB", 2, "parataxis"),
        (6, ".", "PUNCT", 2, "punct"),
    ]
    ps, pos = run(rows)
    assert [ps.word(k).form for k in range(1, ps.n + 1)] == ["Il", "pleut", "je", "reste"]
    assert table(pos) == [(1, 1, 1), (3, 1, 1)]  # position 2 is empty -> excluded
    s = summarize_sentence("s1", ps.n, pos)
    assert (s.n_positions, s.mean_size, s.mean_weight) == (2, 1.0, 1.0)


def test_example3_punct_with_child_is_reattached(run):
    rows = [
        (1, "Il", "PRON", 2, "nsubj"),
        (2, "dit", "VERB", 0, "root"),
        (3, ":", "PUNCT", 2, "punct"),
        (4, "«", "PUNCT", 5, "punct"),
        (5, "non", "INTJ", 3, "obj"),  # parser error: depends on ':'
        (6, "»", "PUNCT", 5, "punct"),
    ]
    ps, pos = run(rows)
    assert table(pos) == [(1, 1, 1), (2, 1, 1)]
    assert len(ps.warnings) == 1
    assert "'non'" in ps.warnings[0] and "reattached to dit" in ps.warnings[0]
