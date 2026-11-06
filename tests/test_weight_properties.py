"""Weight = maximum bipartite matching, cross-checked against networkx and brute force."""

import itertools
import random

import pytest

from flux_complexity.core import Dependency, ProcessedSentence, Sentence, Word, compute_flux
from flux_complexity.core.matching import max_bipartite_matching

nx = pytest.importorskip("networkx")


def nx_matching(edges):
    g = nx.Graph()
    g.add_edges_from((("L", a), ("R", b)) for a, b in edges)
    top = [v for v in g if v[0] == "L"]
    return len(nx.bipartite.maximum_matching(g, top_nodes=top)) // 2


def brute_weight(deps):
    """Largest subset of arcs with pairwise distinct endpoints."""
    for r in range(len(deps), 0, -1):
        for sub in itertools.combinations(deps, r):
            ends = [e for d in sub for e in (d.left, d.right)]
            if len(ends) == len(set(ends)):
                return r
    return 0


def test_matching_on_random_bipartite_graphs_incl_cycles():
    rng = random.Random(0)
    for _ in range(2000):
        edges = {(rng.randint(1, 6), rng.randint(1, 6)) for _ in range(rng.randint(1, 15))}
        assert max_bipartite_matching(edges) == nx_matching(edges)


def test_matching_full_2x2_is_2():
    # the case that made the legacy greedy algorithm crash
    assert max_bipartite_matching([(1, 1), (1, 2), (2, 1), (2, 2)]) == 2


def random_tree_sentence(rng, n):
    order = list(range(1, n + 1))
    rng.shuffle(order)
    root, rest = order[0], order[1:]
    heads = {root: 0}
    attached = [root]
    for w in rest:
        heads[w] = rng.choice(attached)
        attached.append(w)
    words = [Word(i, f"w{i}", "", "X", heads[i], "dep") for i in range(1, n + 1)]
    sent = Sentence("t", words, "UD")
    deps = [Dependency(heads[i], i, "dep") for i in range(1, n + 1) if heads[i]]
    return ProcessedSentence(sent, list(range(1, n + 1)), deps, [], ())


def test_flux_on_random_trees_vs_brute_force():
    rng = random.Random(1)
    for _ in range(500):
        n = rng.randint(2, 14)
        ps = random_tree_sentence(rng, n)
        positions = compute_flux(ps)
        assert len(positions) == n - 1  # a tree has no empty flux
        for p in positions:
            assert p.size == sum(1 for d in ps.deps if d.left <= p.position < d.right)
            assert p.weight == brute_weight(list(p.deps))
            assert 1 <= p.weight <= p.size
