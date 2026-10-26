from __future__ import annotations

from datetime import UTC, datetime

import duckdb
import pytest

from cdp.ingest.clients import RawResponse
from cdp.ingest.loader import land, load_objects
from cdp.ingest.pipeline import run_ingest
from cdp.ingest.storage import LocalFilesystemClient, PreconditionFailedError


def _raw(content: bytes, when: datetime | None = None) -> RawResponse:
    return RawResponse(
        source="directory",
        url="https://p.local/directory/export.jsonl",
        content=content,
        content_type="application/x-ndjson",
        fetched_at=when or datetime.now(UTC),
        extension="jsonl",
    )


def test_storage_create_only_precondition(tmp_path):
    blob = LocalFilesystemClient(tmp_path).bucket("b").blob("x/y.json")
    blob.upload_from_string(b"{}", "application/json", if_generation_match=0)
    with pytest.raises(PreconditionFailedError):
        blob.upload_from_string(b"{}", "application/json", if_generation_match=0)


def test_storage_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        LocalFilesystemClient(tmp_path).bucket("b").blob("../escape")


def test_land_preserves_bytes_and_metadata(tmp_path):
    bucket = LocalFilesystemClient(tmp_path).bucket("raw")
    payload = '{"business_name": "Ébène Data  S.L."}\n'.encode()
    obj = land(bucket, _raw(payload))
    blob = bucket.blob(obj.uri.removeprefix("gs://raw/"))
    blob.reload()
    assert blob.download_as_bytes() == payload
    assert blob.metadata["source"] == "directory"
    assert blob.metadata["checksum"] == obj.checksum
    assert "fetched_at" in blob.metadata


def test_land_and_load_twice_is_a_noop(tmp_path):
    bucket = LocalFilesystemClient(tmp_path).bucket("raw")
    payload = b'{"listing_id": "a"}\n{"listing_id": "b"}\n'
    first_time = datetime(2026, 1, 1, tzinfo=UTC)
    con = duckdb.connect()
    first = load_objects(con, [land(bucket, _raw(payload, first_time))], "directory")
    second_obj = land(bucket, _raw(payload))
    second = load_objects(con, [second_obj], "directory")

    assert (first.records_loaded, second.records_loaded, second.objects_skipped) == (2, 0, 1)
    assert not second_obj.newly_written
    # the original fetch time is kept for identical content
    assert second_obj.fetched_at == first_time
    assert con.execute("select count(*) from raw.directory_listings").fetchone()[0] == 2
    assert len(list(bucket.list_blobs())) == 1


def test_changed_content_is_loaded_as_new_object(tmp_path):
    bucket = LocalFilesystemClient(tmp_path).bucket("raw")
    con = duckdb.connect()
    load_objects(con, [land(bucket, _raw(b'{"listing_id": "a"}\n'))], "directory")
    load_objects(con, [land(bucket, _raw(b'{"listing_id": "a", "x": 1}\n'))], "directory")
    assert con.execute("select count(*) from raw.load_manifest").fetchone()[0] == 2


def test_full_ingest_rerun_is_idempotent(settings):
    first = run_ingest(settings)
    second = run_ingest(settings)
    assert {s: r.records_loaded for s, r in first.results.items()} == {
        "registry": 176,
        "api": 175,
        "directory": 164,
    }
    assert sum(r.records_loaded for r in second.results.values()) == 0
    assert sum(first.retries.values()) >= 1  # fault injection exercised the retry path
