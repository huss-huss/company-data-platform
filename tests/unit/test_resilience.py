from __future__ import annotations

import random

import httpx
import pytest

from cdp.config import PROJECT_ROOT
from cdp.ingest.clients import CompanyApiClient, RegistryClient
from cdp.ingest.fixture_server import FixtureProvider
from cdp.ingest.resilience import (
    AsyncTokenBucket,
    RetryableHTTPError,
    RetryPolicy,
    call_with_retries,
)


def test_backoff_is_bounded_by_exponential_ceiling():
    policy = RetryPolicy(base_delay=0.5, max_delay=4.0)
    rng = random.Random(1)
    for attempt in range(10):
        ceiling = min(4.0, 0.5 * 2**attempt)
        delays = [policy.backoff(attempt, rng) for _ in range(200)]
        assert all(0 <= d <= ceiling for d in delays)
        # full jitter actually spreads values (not a constant)
        assert max(delays) - min(delays) > ceiling * 0.5


def test_backoff_is_reproducible_with_seeded_rng():
    policy = RetryPolicy()
    a = [policy.backoff(i, random.Random(7)) for i in range(5)]
    b = [policy.backoff(i, random.Random(7)) for i in range(5)]
    assert a == b


async def test_retries_transport_errors_with_fake_clock(fake_clock):
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return "ok"

    policy = RetryPolicy(max_attempts=5, base_delay=1.0, max_delay=10.0)
    result = await call_with_retries(flaky, policy, sleep=fake_clock.sleep, rng=random.Random(0))
    assert result == "ok"
    assert calls["n"] == 3
    assert len(fake_clock.sleeps) == 2
    assert 0 <= fake_clock.sleeps[0] <= 1.0
    assert 0 <= fake_clock.sleeps[1] <= 2.0


async def test_gives_up_after_max_attempts(fake_clock):
    async def always_fails():
        raise httpx.ReadTimeout("slow")

    with pytest.raises(httpx.ReadTimeout):
        await call_with_retries(always_fails, RetryPolicy(max_attempts=3), sleep=fake_clock.sleep)
    assert len(fake_clock.sleeps) == 2


async def test_non_retryable_errors_propagate_immediately(fake_clock):
    async def bad():
        raise ValueError("bug")

    with pytest.raises(ValueError):
        await call_with_retries(bad, RetryPolicy(), sleep=fake_clock.sleep)
    assert fake_clock.sleeps == []


async def test_retry_after_header_is_honoured(fake_clock):
    request = httpx.Request("GET", "https://x.local/a")
    responses = [httpx.Response(429, headers={"Retry-After": "3"}, request=request)]

    async def fn():
        if responses:
            raise RetryableHTTPError(responses.pop())
        return 1

    await call_with_retries(fn, RetryPolicy(max_delay=10), sleep=fake_clock.sleep)
    assert fake_clock.sleeps == [3.0]


async def test_token_bucket_enforces_rate(fake_clock):
    bucket = AsyncTokenBucket(rate=2.0, capacity=2.0, clock=fake_clock, sleep=fake_clock.sleep)
    for _ in range(6):
        await bucket.acquire()
    # 2 burst tokens free, the remaining 4 at 2/s -> 2 seconds of (fake) waiting
    assert fake_clock.now == pytest.approx(2.0)


async def test_client_recovers_from_injected_failures(fake_clock):
    provider = FixtureProvider(PROJECT_ROOT / "fixtures", fail_every=2)
    async with httpx.AsyncClient(transport=provider.transport(), base_url="https://p.local") as h:
        api = CompanyApiClient(h, sleep=fake_clock.sleep, rng=random.Random(0), rate_per_sec=100)
        pages = [r async for r in api.fetch()]
        registry = RegistryClient(h, sleep=fake_clock.sleep, rate_per_sec=100)
        [csv_payload] = [r async for r in registry.fetch()]
    assert len(pages) == 4
    assert api.retries >= 1
    assert csv_payload.content.startswith(b"registration_number,")


async def test_client_fails_fast_on_404():
    transport = httpx.MockTransport(lambda req: httpx.Response(404))
    async with httpx.AsyncClient(transport=transport, base_url="https://p.local") as h:
        client = RegistryClient(h)
        with pytest.raises(httpx.HTTPStatusError):
            [r async for r in client.fetch()]
    assert client.retries == 0
