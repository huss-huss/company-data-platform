from cdp.resolve.clustering import UnionFind, cluster


def test_union_find_is_transitive():
    uf = UnionFind("abcde")
    uf.union("a", "b")
    uf.union("b", "c")
    assert uf.connected("a", "c")
    assert not uf.connected("a", "d")
    assert sorted(uf.groups().values()) == [["a", "b", "c"], ["d"], ["e"]]


def test_union_is_idempotent_and_handles_large_chains():
    uf = UnionFind(str(i) for i in range(2000))
    for i in range(1999):
        uf.union(str(i), str(i + 1))
        uf.union(str(i + 1), str(i))
    assert len(uf.groups()) == 1


def test_cluster_applies_strongest_edges_first_and_respects_cannot_link():
    # x and y are two different legal entities; z looks like both.
    forbidden = {frozenset({"x", "y"})}

    def cannot_link(a, b):
        return any(frozenset({i, j}) in forbidden for i in a for j in b)

    edges = [("x", "z", 0.91), ("y", "z", 0.99)]
    uf, rejected = cluster("xyz", edges, cannot_link)
    assert uf.connected("y", "z")
    assert not uf.connected("x", "z")
    assert rejected == [("x", "z", 0.91)]


def test_cluster_without_edges_gives_singletons():
    uf, rejected = cluster(["a", "b"], [])
    assert len(uf.groups()) == 2
    assert rejected == []
