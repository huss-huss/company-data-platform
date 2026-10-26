"""Land raw payloads in object storage and load them idempotently into DuckDB.

Idempotency is content-based: every payload is addressed by its SHA-256. Re-fetching identical
content writes nothing new to storage (create-only precondition) and inserts no rows (the
checksum is already in ``raw.load_manifest``). Each object loads inside a single transaction,
so a crash never leaves a half-loaded object.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

import duckdb

from cdp.ingest.clients import RawResponse
from cdp.ingest.storage import Bucket, PreconditionFailedError

RAW_TABLES = {
    "registry": "registry_companies",
    "api": "api_companies",
    "directory": "directory_listings",
}

DDL = """
create schema if not exists raw;
create table if not exists raw.load_manifest (
    checksum      varchar primary key,
    source        varchar not null,
    object_uri    varchar not null,
    request_url   varchar not null,
    fetched_at    timestamptz not null,
    loaded_at     timestamptz not null,
    record_count  integer not null
);
"""

RAW_TABLE_DDL = """
create table if not exists raw.{table} (
    payload        json not null,
    _record_index  integer not null,
    _source        varchar not null,
    _object_uri    varchar not null,
    _checksum      varchar not null,
    _fetched_at    timestamptz not null,
    _loaded_at     timestamptz not null
);
"""


@dataclass(frozen=True)
class LandedObject:
    source: str
    uri: str
    checksum: str
    request_url: str
    fetched_at: datetime
    content: bytes
    newly_written: bool


@dataclass
class LoadResult:
    source: str
    objects_seen: int = 0
    objects_loaded: int = 0
    records_loaded: int = 0
    objects_skipped: int = 0


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def land(bucket: Bucket, raw: RawResponse) -> LandedObject:
    """Write a payload to the raw layer, content-addressed. Safe to call repeatedly."""
    checksum = sha256(raw.content)
    blob = bucket.blob(f"source={raw.source}/sha256={checksum}.{raw.extension}")
    fetched_at = raw.fetched_at
    written = False
    if blob.exists():
        blob.reload()
        fetched_at = datetime.fromisoformat((blob.metadata or {})["fetched_at"])
    else:
        blob.metadata = {
            "source": raw.source,
            "fetched_at": raw.fetched_at.isoformat(),
            "checksum": checksum,
            "request_url": raw.url,
            "content_type": raw.content_type,
        }
        try:
            blob.upload_from_string(raw.content, raw.content_type, if_generation_match=0)
            written = True
        except PreconditionFailedError:  # lost a race with a concurrent writer: same bytes
            pass
    return LandedObject(
        source=raw.source,
        uri=f"gs://{bucket.name}/{blob.name}",
        checksum=checksum,
        request_url=raw.url,
        fetched_at=fetched_at,
        content=raw.content,
        newly_written=written,
    )


def parse_records(source: str, content: bytes) -> list[dict]:
    """Split a raw payload into records. Values are not cleaned here (that is dbt's job)."""
    text = content.decode("utf-8")
    if source == "registry":
        return list(csv.DictReader(io.StringIO(text)))
    if source == "api":
        return json.loads(text)["data"]
    if source == "directory":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    raise ValueError(f"unknown source {source!r}")


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)
    for table in RAW_TABLES.values():
        con.execute(RAW_TABLE_DDL.format(table=table))


def load_objects(
    con: duckdb.DuckDBPyConnection, objects: Iterable[LandedObject], source: str
) -> LoadResult:
    ensure_schema(con)
    result = LoadResult(source=source)
    table = RAW_TABLES[source]
    for obj in objects:
        result.objects_seen += 1
        already = con.execute(
            "select 1 from raw.load_manifest where checksum = ?", [obj.checksum]
        ).fetchone()
        if already:
            result.objects_skipped += 1
            continue
        records = parse_records(source, obj.content)
        loaded_at = datetime.now(UTC)
        con.execute("begin transaction")
        try:
            con.executemany(
                f"insert into raw.{table} values (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        json.dumps(r, ensure_ascii=False),
                        i,
                        source,
                        obj.uri,
                        obj.checksum,
                        obj.fetched_at,
                        loaded_at,
                    )
                    for i, r in enumerate(records)
                ],
            )
            con.execute(
                "insert into raw.load_manifest values (?, ?, ?, ?, ?, ?, ?)",
                [
                    obj.checksum,
                    source,
                    obj.uri,
                    obj.request_url,
                    obj.fetched_at,
                    loaded_at,
                    len(records),
                ],
            )
            con.execute("commit")
        except BaseException:
            con.execute("rollback")
            raise
        result.objects_loaded += 1
        result.records_loaded += len(records)
    return result
