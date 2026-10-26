import pytest

from cdp.resolve.evaluate import pairwise_metrics


def test_perfect_clustering():
    truth = {"a": "1", "b": "1", "c": "2"}
    assert pairwise_metrics({"a": "x", "b": "x", "c": "y"}, truth)[:3] == (1.0, 1.0, 1.0)


def test_over_merge_hurts_precision_only():
    truth = {"a": "1", "b": "1", "c": "2"}
    p, r, f1, n_true, n_pred, tp = pairwise_metrics({"a": "x", "b": "x", "c": "x"}, truth)
    assert (n_true, n_pred, tp) == (1, 3, 1)
    assert p == pytest.approx(1 / 3)
    assert r == 1.0
    assert f1 == pytest.approx(0.5)


def test_under_merge_hurts_recall_only():
    truth = {"a": "1", "b": "1", "c": "1"}
    p, r, *_ = pairwise_metrics({"a": "x", "b": "x", "c": "y"}, truth)
    assert p == 1.0
    assert r == pytest.approx(1 / 3)
