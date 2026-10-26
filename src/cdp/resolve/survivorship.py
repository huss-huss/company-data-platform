"""Survivorship: build one golden record per cluster, field by field.

Rule per field (or field group): take the value from the *most trusted source* that has a
non-null value; ties within a source go to the *most recently updated* record, then to the
smallest record_id so the outcome is deterministic. Every surviving value carries the
record_id it came from (provenance), which feeds ``dim_company.field_provenance``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cdp.resolve.records import Record

# Lower index = more trusted. Sources missing from a list never supply that field.
FIELD_TRUST: dict[str, tuple[str, ...]] = {
    "company_name": ("registry", "api", "directory"),
    "registration_number": ("registry",),
    "status": ("registry",),
    "incorporation_date": ("registry",),
    "country_code": ("registry", "api", "directory"),
    "address": ("registry", "api", "directory"),  # street + city survive together
    "domain": ("api", "directory", "registry"),
    "phone_norm": ("directory", "api", "registry"),
    "employee_count": ("api",),
    "industry": ("api", "directory"),
}

FIELD_GROUPS: dict[str, tuple[str, ...]] = {"address": ("street", "city")}

_EPOCH = datetime.min


@dataclass
class GoldenRecord:
    entity_id: str
    values: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)
    member_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    last_source_update: datetime | None = None


def entity_id_for(member_ids: Sequence[str]) -> str:
    """Stable id anchored on the smallest member record_id (see README: limitations)."""
    anchor = min(member_ids)
    return "cmp_" + hashlib.sha256(anchor.encode()).hexdigest()[:16]


def pick(
    records: Sequence[Record], attrs: tuple[str, ...], trust: tuple[str, ...]
) -> Record | None:
    """Return the record that should supply ``attrs`` (all of them must be non-null)."""
    rank = {s: i for i, s in enumerate(trust)}
    eligible = [
        r
        for r in records
        if r.source in rank and all(getattr(r, a) not in (None, "") for a in attrs)
    ]
    if not eligible:
        return None
    # most trusted source, then most recent, then smallest record_id
    return min(
        eligible,
        key=lambda r: (
            rank[r.source],
            -(r.source_updated_at or _EPOCH).timestamp() if r.source_updated_at else 0.0,
            r.source_updated_at is None,
            r.record_id,
        ),
    )


def survive(records: Sequence[Record]) -> GoldenRecord:
    if not records:
        raise ValueError("cannot survive an empty cluster")
    ids = sorted(r.record_id for r in records)
    golden = GoldenRecord(entity_id=entity_id_for(ids), member_ids=ids)
    golden.sources = sorted({r.source for r in records})
    updates = [r.source_updated_at for r in records if r.source_updated_at]
    golden.last_source_update = max(updates) if updates else None
    for name, trust in FIELD_TRUST.items():
        attrs = FIELD_GROUPS.get(name, (name,))
        winner = pick(records, attrs, trust)
        for attr in attrs:
            golden.values[attr] = getattr(winner, attr) if winner else None
            if winner:
                golden.provenance[attr] = winner.record_id
    return golden
