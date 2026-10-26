"""Evaluate clustering against labelled ground truth (pairwise precision / recall / F1)."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path

from cdp.resolve.engine import Resolution


@dataclass(frozen=True)
class Metrics:
    records: int
    true_entities: int
    predicted_entities: int
    true_pairs: int
    predicted_pairs: int
    true_positive_pairs: int
    precision: float
    recall: float
    f1: float
    blocking_recall: float
    candidate_pairs: int
    uncertain_pairs: int
    uncertain_true_matches: int

    def as_dict(self) -> dict:
        return asdict(self)


def load_ground_truth(path: Path) -> dict[str, str]:
    """record_id (``<source>:<source_id>``) -> true entity id."""
    with Path(path).open(encoding="utf-8") as fh:
        return {
            f"{row['source']}:{row['source_id']}": row["entity_id"] for row in csv.DictReader(fh)
        }


def _pairs(assignment: dict[str, str]) -> set[tuple[str, str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for rid, cid in assignment.items():
        groups[cid].append(rid)
    return {pair for members in groups.values() for pair in combinations(sorted(members), 2)}


def pairwise_metrics(
    predicted: dict[str, str], truth: dict[str, str]
) -> tuple[float, float, float, int, int, int]:
    common = predicted.keys() & truth.keys()
    pred = _pairs({r: predicted[r] for r in common})
    true = _pairs({r: truth[r] for r in common})
    tp = len(pred & true)
    precision = tp / len(pred) if pred else 1.0
    recall = tp / len(true) if true else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1, len(true), len(pred), tp


def evaluate(res: Resolution, truth: dict[str, str]) -> Metrics:
    missing = {r.record_id for r in res.records} - truth.keys()
    if missing:
        raise ValueError(f"{len(missing)} records have no ground-truth label, e.g. {min(missing)}")
    precision, recall, f1, n_true, n_pred, tp = pairwise_metrics(res.membership, truth)
    true_pairs = _pairs({r: truth[r] for r in res.membership})
    candidates = {(p.left, p.right) for p in res.pairs}
    review = res.review_queue
    return Metrics(
        records=len(res.membership),
        true_entities=len({truth[r] for r in res.membership}),
        predicted_entities=res.n_entities,
        true_pairs=n_true,
        predicted_pairs=n_pred,
        true_positive_pairs=tp,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        blocking_recall=round(len(true_pairs & candidates) / len(true_pairs), 4)
        if true_pairs
        else 1.0,
        candidate_pairs=len(res.pairs),
        uncertain_pairs=len(review),
        uncertain_true_matches=sum(truth[p.left] == truth[p.right] for p in review),
    )


def baseline_exact_key(res: Resolution) -> dict[str, str]:
    """Naive baseline: same normalised name and country => same company."""
    return {r.record_id: f"{r.name_norm}|{r.country_code}" for r in res.records}


def baseline_metrics(res: Resolution, truth: dict[str, str]) -> dict[str, float]:
    precision, recall, f1, *_ = pairwise_metrics(baseline_exact_key(res), truth)
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}
