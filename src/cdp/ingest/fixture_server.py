"""Offline provider emulation via ``httpx.MockTransport``.

Serves the committed fixtures with the same URL shapes, pagination and content types as the
"real" providers, and can inject deterministic transient failures (429 with ``Retry-After``,
503) so the retry path is exercised on every offline run, not just in unit tests.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import httpx


class FixtureProvider:
    def __init__(self, fixtures_dir: Path, *, fail_every: int = 0) -> None:
        self.fixtures_dir = Path(fixtures_dir)
        self.fail_every = fail_every
        self.requests = 0

    def _maybe_fail(self) -> httpx.Response | None:
        self.requests += 1
        if self.fail_every and self.requests % self.fail_every == 0:
            if (self.requests // self.fail_every) % 2:
                return httpx.Response(429, headers={"Retry-After": "0"}, text="slow down")
            return httpx.Response(503, text="temporarily unavailable")
        return None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if failure := self._maybe_fail():
            return failure
        path = request.url.path
        if path == "/registry/v1/companies.csv":
            body = (self.fixtures_dir / "registry" / "companies.csv").read_bytes()
            return httpx.Response(200, content=body, headers={"content-type": "text/csv"})
        if path == "/directory/export.jsonl":
            body = (self.fixtures_dir / "directory" / "export.jsonl").read_bytes()
            return httpx.Response(
                200, content=body, headers={"content-type": "application/x-ndjson"}
            )
        if path == "/api/v1/companies":
            rows = json.loads((self.fixtures_dir / "api" / "companies.json").read_text("utf-8"))
            page = int(request.url.params.get("page", 1))
            size = int(request.url.params.get("page_size", 50))
            pages = max(1, math.ceil(len(rows) / size))
            if page < 1 or page > pages:
                return httpx.Response(404, json={"error": "page out of range"})
            body = {
                "data": rows[(page - 1) * size : page * size],
                "page": page,
                "total": len(rows),
                "next_page": page + 1 if page < pages else None,
            }
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"error": f"unknown path {path}"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)
