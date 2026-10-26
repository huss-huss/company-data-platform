"""Ingestion entry point: fetch all sources concurrently, land raw, load idempotently."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

import duckdb
import httpx

from cdp.config import Settings
from cdp.ingest.clients import CLIENTS, RawResponse
from cdp.ingest.fixture_server import FixtureProvider
from cdp.ingest.loader import LoadResult, land, load_objects
from cdp.ingest.resilience import RetryPolicy
from cdp.ingest.storage import LocalFilesystemClient

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    results: dict[str, LoadResult] = field(default_factory=dict)
    retries: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = []
        for source, r in self.results.items():
            lines.append(
                f"{source:<10} objects={r.objects_seen} loaded={r.objects_loaded} "
                f"skipped={r.objects_skipped} records={r.records_loaded} "
                f"retries={self.retries.get(source, 0)}"
            )
        return "\n".join(lines)


async def _fetch_all(
    transport: httpx.AsyncBaseTransport, base_url: str, sources: list[str], retry: RetryPolicy
) -> tuple[dict[str, list[RawResponse]], dict[str, int]]:
    async with httpx.AsyncClient(
        transport=transport, base_url=base_url, timeout=httpx.Timeout(30.0)
    ) as http:
        clients = {s: CLIENTS[s](http, retry=retry) for s in sources}

        async def collect(source: str) -> list[RawResponse]:
            return [raw async for raw in clients[source].fetch()]

        fetched = await asyncio.gather(*(collect(s) for s in sources))
        return dict(zip(sources, fetched, strict=True)), {s: c.retries for s, c in clients.items()}


def run_ingest(
    settings: Settings,
    *,
    sources: list[str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = "https://providers.local",
    retry: RetryPolicy | None = None,
    fail_every: int = 4,
) -> IngestReport:
    """Fetch -> land -> load. Defaults to the offline fixture provider (with fault injection)."""
    sources = sources or list(CLIENTS)
    transport = (
        transport or FixtureProvider(settings.fixtures_dir, fail_every=fail_every).transport()
    )
    retry = retry or RetryPolicy(max_attempts=5, base_delay=0.05, max_delay=1.0)
    fetched, retries = asyncio.run(_fetch_all(transport, base_url, sources, retry))

    bucket = LocalFilesystemClient(settings.storage_root).bucket(settings.raw_bucket)
    settings.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    report = IngestReport(retries=retries)
    with duckdb.connect(str(settings.warehouse_path)) as con:
        for source in sources:
            landed = [land(bucket, raw) for raw in fetched[source]]
            report.results[source] = load_objects(con, landed, source)
    log.info("ingest complete\n%s", report.summary())
    return report
