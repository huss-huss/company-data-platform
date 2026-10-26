from __future__ import annotations

from datetime import datetime

from cdp.normalize import name_key, normalize_name
from cdp.resolve.records import Record


def rec(record_id: str, name: str, **kw) -> Record:
    source = kw.pop("source", record_id.split(":", 1)[0])
    kw.setdefault("country_code", "DE")
    if isinstance(kw.get("source_updated_at"), str):
        kw["source_updated_at"] = datetime.fromisoformat(kw["source_updated_at"])
    return Record(
        record_id=record_id,
        source=source,
        source_record_id=record_id.split(":", 1)[-1],
        company_name=name,
        name_norm=normalize_name(name),
        name_key=name_key(name),
        **kw,
    )
