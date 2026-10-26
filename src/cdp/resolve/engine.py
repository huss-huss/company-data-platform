"""End-to-end resolution: load -> block -> score -> cluster -> survive -> persist."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from cdp.normalize import normalize_name
from cdp.resolve.blocking import DEFAULT_MAX_BLOCK_SIZE, candidate_pairs
from cdp.resolve.clustering import cluster
from cdp.resolve.records import Record, load_records
from cdp.resolve.scoring import Thresholds, compute_features, score
from cdp.resolve.survivorship import GoldenRecord, survive

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScoredPair:
    left: str
    right: str
    blocking_keys: str
    features: dict
    score: float
    decision: str
    reason: str


@dataclass
class Resolution:
    records: list[Record]
    pairs: list[ScoredPair]
    membership: dict[str, str]  # record_id -> entity_id
    golden: list[GoldenRecord]
    skipped_blocks: dict[str, int]

    @property
    def n_entities(self) -> int:
        return len(self.golden)

    @property
    def review_queue(self) -> list[ScoredPair]:
        return [p for p in self.pairs if p.decision == "review"]

    def summary(self) -> dict[str, int]:
        decisions = {
            d: sum(p.decision == d for p in self.pairs) for d in ("match", "review", "non_match")
        }
        return {
            "records": len(self.records),
            "candidate_pairs": len(self.pairs),
            **decisions,
            "entities": self.n_entities,
            "skipped_blocks": len(self.skipped_blocks),
        }


def registry_cannot_link(by_id: dict[str, Record]):
    """Two *different* registry registrations are by definition two legal entities."""

    def veto(a: Sequence[str], b: Sequence[str]) -> bool:
        regs_a = {by_id[x].registration_number for x in a if by_id[x].source == "registry"}
        regs_b = {by_id[x].registration_number for x in b if by_id[x].source == "registry"}
        return bool(regs_a and regs_b and regs_a != regs_b)

    return veto


def resolve_records(
    records: list[Record],
    thresholds: Thresholds | None = None,
    max_block_size: int = DEFAULT_MAX_BLOCK_SIZE,
) -> Resolution:
    thresholds = thresholds or Thresholds()
    by_id = {r.record_id: r for r in records}
    blocking = candidate_pairs(records, max_block_size=max_block_size)
    for key, size in blocking.skipped_blocks.items():
        log.warning("skipped oversized block %s (%d records)", key, size)

    scored: dict[tuple[str, str], ScoredPair] = {}
    for (a, b), keys in sorted(blocking.pairs.items()):
        feats = compute_features(by_id[a], by_id[b])
        s = score(feats)
        scored[(a, b)] = ScoredPair(
            a,
            b,
            ",".join(sorted(keys)),
            feats.as_dict(),
            round(s, 6),
            thresholds.decide(s),
            "threshold",
        )

    edges = [(p.left, p.right, p.score) for p in scored.values() if p.decision == "match"]
    uf, vetoed = cluster(by_id, edges, cannot_link=registry_cannot_link(by_id))
    for a, b, _ in vetoed:
        p = scored[(a, b)]
        scored[(a, b)] = ScoredPair(
            p.left, p.right, p.blocking_keys, p.features, p.score, "review", "cannot_link:registry"
        )

    golden: list[GoldenRecord] = []
    membership: dict[str, str] = {}
    for members in uf.groups().values():
        g = survive([by_id[m] for m in members])
        golden.append(g)
        membership.update(dict.fromkeys(members, g.entity_id))
    golden.sort(key=lambda g: g.entity_id)
    return Resolution(records, list(scored.values()), membership, golden, blocking.skipped_blocks)


PERSIST_DDL = """
create schema if not exists resolved;
create or replace table resolved.entity_membership (
    record_id varchar primary key, entity_id varchar not null, cluster_size integer not null,
    resolved_at timestamptz not null
);
create or replace table resolved.pair_scores (
    pair_id varchar primary key, left_record_id varchar not null,
    right_record_id varchar not null, blocking_keys varchar not null,
    name_sim double, name_jw double, extra_tokens integer, domain_match integer,
    phone_match integer, country_match integer, city_match integer, street_sim double,
    score double not null, decision varchar not null, reason varchar not null,
    resolved_at timestamptz not null
);
create or replace table resolved.golden_records (
    entity_id varchar primary key, company_name varchar, name_norm varchar,
    registration_number varchar, status varchar, incorporation_date date,
    country_code varchar, street varchar, city varchar, domain varchar, phone varchar,
    employee_count integer, industry varchar, record_count integer not null,
    source_count integer not null, sources varchar not null,
    last_source_update timestamp, field_provenance json not null,
    resolved_at timestamptz not null
);
"""

FEATURE_ORDER = (
    "name_sim",
    "name_jw",
    "extra_tokens",
    "domain_match",
    "phone_match",
    "country_match",
    "city_match",
    "street_sim",
)


def persist(con: duckdb.DuckDBPyConnection, res: Resolution) -> None:
    """Replace resolved.* atomically (one transaction)."""
    now = datetime.now(UTC)
    sizes: dict[str, int] = {}
    for eid in res.membership.values():
        sizes[eid] = sizes.get(eid, 0) + 1
    con.execute("begin transaction")
    try:
        con.execute(PERSIST_DDL)
        con.executemany(
            "insert into resolved.entity_membership values (?, ?, ?, ?)",
            [(rid, eid, sizes[eid], now) for rid, eid in sorted(res.membership.items())],
        )
        con.executemany(
            "insert into resolved.pair_scores values "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    hashlib.sha256(f"{p.left}|{p.right}".encode()).hexdigest()[:20],
                    p.left,
                    p.right,
                    p.blocking_keys,
                    *(p.features[k] for k in FEATURE_ORDER),
                    p.score,
                    p.decision,
                    p.reason,
                    now,
                )
                for p in res.pairs
            ],
        )
        con.executemany(
            "insert into resolved.golden_records values "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    g.entity_id,
                    g.values["company_name"],
                    normalize_name(g.values["company_name"]),
                    g.values["registration_number"],
                    g.values["status"],
                    g.values["incorporation_date"],
                    g.values["country_code"],
                    g.values["street"],
                    g.values["city"],
                    g.values["domain"],
                    g.values["phone_norm"],
                    g.values["employee_count"],
                    g.values["industry"],
                    len(g.member_ids),
                    len(g.sources),
                    ",".join(g.sources),
                    g.last_source_update,
                    json.dumps(g.provenance, sort_keys=True),
                    now,
                )
                for g in res.golden
            ],
        )
        con.execute("commit")
    except BaseException:
        con.execute("rollback")
        raise


def run_resolve(con: duckdb.DuckDBPyConnection, thresholds: Thresholds | None = None) -> Resolution:
    res = resolve_records(load_records(con), thresholds)
    persist(con, res)
    log.info("resolve complete: %s", res.summary())
    return res
