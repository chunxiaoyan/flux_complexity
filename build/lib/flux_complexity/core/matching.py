"""Maximum bipartite matching (Kuhn's augmenting paths).

Flux matrices are tiny (a handful of arcs), so the simple O(V·E) algorithm is
more than fast enough and keeps the package free of heavy dependencies.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable


def max_bipartite_matching(edges: Iterable[tuple[Hashable, Hashable]]) -> int:
    """Size of a maximum matching between left and right vertices of the given edges."""
    adj: dict[Hashable, list[Hashable]] = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    match_right: dict[Hashable, Hashable] = {}

    def augment(a: Hashable, visited: set[Hashable]) -> bool:
        for b in adj[a]:
            if b in visited:
                continue
            visited.add(b)
            if b not in match_right or augment(match_right[b], visited):
                match_right[b] = a
                return True
        return False

    return sum(1 for a in list(adj) if augment(a, set()))
