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


def test_baseline_groups_by_exact_name_and_country():
    from cdp.resolve.engine import Resolution
    from cdp.resolve.evaluate import baseline_exact_key, baseline_metrics

    from .factories import rec

    records = [
        rec("api:1", "Kestrel Data GmbH"),
        rec("registry:1", "KESTREL DATA"),
        rec("directory:1", "Kestrel Dtaa"),
    ]
    res = Resolution(records, [], {}, [], {})
    keys = baseline_exact_key(res)
    assert keys["api:1"] == keys["registry:1"] != keys["directory:1"]
    truth = dict.fromkeys(keys, "E1")
    assert baseline_metrics(res, truth)["recall"] == pytest.approx(1 / 3, abs=1e-4)
