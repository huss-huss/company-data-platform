"""Union-find clustering over accepted match edges, with cannot-link constraints."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence


class UnionFind:
    """Disjoint-set forest with path halving and union by size."""

    def __init__(self, items: Iterable[str] = ()) -> None:
        self._parent: dict[str, str] = {}
        self._size: dict[str, int] = {}
        for item in items:
            self.add(item)

    def add(self, item: str) -> None:
        if item not in self._parent:
            self._parent[item] = item
            self._size[item] = 1

    def find(self, item: str) -> str:
        parent = self._parent
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(self, a: str, b: str) -> str:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return ra
        if self._size[ra] < self._size[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        self._size[ra] += self._size[rb]
        return ra

    def connected(self, a: str, b: str) -> bool:
        return self.find(a) == self.find(b)

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for item in self._parent:
            out.setdefault(self.find(item), []).append(item)
        return {root: sorted(members) for root, members in out.items()}


CannotLink = Callable[[Sequence[str], Sequence[str]], bool]


def cluster(
    items: Iterable[str],
    edges: Iterable[tuple[str, str, float]],
    cannot_link: CannotLink | None = None,
) -> tuple[UnionFind, list[tuple[str, str, float]]]:
    """Merge along edges in descending score order.

    ``cannot_link(members_a, members_b)`` may veto merging two components (e.g. two distinct
    registry entries). Vetoed edges are returned so the caller can route them to review.
    Strongest evidence is applied first, so a weak edge cannot pre-empt a strong one.
    """
    uf = UnionFind(items)
    members: dict[str, list[str]] = {root: [root] for root in uf.groups()}
    rejected: list[tuple[str, str, float]] = []
    for a, b, s in sorted(edges, key=lambda e: (-e[2], e[0], e[1])):
        ra, rb = uf.find(a), uf.find(b)
        if ra == rb:
            continue
        if cannot_link and cannot_link(members[ra], members[rb]):
            rejected.append((a, b, s))
            continue
        root = uf.union(a, b)
        other = rb if root == ra else ra
        members[root] = members[root] + members.pop(other)
    return uf, rejected
