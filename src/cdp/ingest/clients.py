"""Async HTTP clients for the three company-data providers.

Each client yields :class:`RawResponse` objects: the exact bytes the provider returned plus
request provenance. Parsing into records happens later (``loader.parse_records``) so that the
raw layer always holds the untouched payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from cdp.ingest.resilience import (
    RETRYABLE_STATUS,
    AsyncTokenBucket,
    RetryableHTTPError,
    RetryPolicy,
    Sleep,
    call_with_retries,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RawResponse:
    source: str
    url: str
    content: bytes
    content_type: str
    fetched_at: datetime
    extension: str


class SourceClient:
    """Base client: rate limited, retried GETs over a shared ``httpx.AsyncClient``."""

    source: str = ""
    extension: str = ""

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        rate_per_sec: float = 5.0,
        retry: RetryPolicy | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.http = http
        self.limiter = AsyncTokenBucket(rate_per_sec, sleep=sleep)
        self.retry = retry or RetryPolicy()
        self._sleep = sleep
        self._rng = rng or random.Random()
        self.retries = 0

    async def _get(self, path: str, params: dict[str, str | int] | None = None) -> RawResponse:
        async def attempt() -> httpx.Response:
            await self.limiter.acquire()
            response = await self.http.get(path, params=params)
            if response.status_code in RETRYABLE_STATUS:
                raise RetryableHTTPError(response)
            response.raise_for_status()
            return response

        def on_retry(n: int, exc: BaseException, delay: float) -> None:
            self.retries += 1
            log.warning("%s: retry %d after %s (sleep %.2fs)", self.source, n, exc, delay)

        response = await call_with_retries(
            attempt, self.retry, sleep=self._sleep, rng=self._rng, on_retry=on_retry
        )
        return RawResponse(
            source=self.source,
            url=str(response.request.url),
            content=response.content,
            content_type=response.headers.get("content-type", "application/octet-stream"),
            fetched_at=datetime.now(UTC),
            extension=self.extension,
        )

    def fetch(self) -> AsyncIterator[RawResponse]:  # pragma: no cover - abstract
        raise NotImplementedError


class RegistryClient(SourceClient):
    """Company registry bulk export (CSV, single file)."""

    source = "registry"
    extension = "csv"

    async def fetch(self) -> AsyncIterator[RawResponse]:
        yield await self._get("/registry/v1/companies.csv")


class CompanyApiClient(SourceClient):
    """Paginated JSON API: ``GET /api/v1/companies?page=N`` -> ``{data, next_page}``."""

    source = "api"
    extension = "json"
    page_size = 50

    async def fetch(self) -> AsyncIterator[RawResponse]:
        page: int | None = 1
        while page is not None:
            raw = await self._get("/api/v1/companies", {"page": page, "page_size": self.page_size})
            yield raw
            page = json.loads(raw.content).get("next_page")


class DirectoryClient(SourceClient):
    """Business directory export (JSON Lines, single file)."""

    source = "directory"
    extension = "jsonl"

    async def fetch(self) -> AsyncIterator[RawResponse]:
        yield await self._get("/directory/export.jsonl")


CLIENTS: dict[str, type[SourceClient]] = {
    c.source: c for c in (RegistryClient, CompanyApiClient, DirectoryClient)
}
