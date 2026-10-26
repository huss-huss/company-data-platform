"""Rate limiting and retry primitives with injectable clocks (so tests never sleep)."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class AsyncTokenBucket:
    """Token-bucket limiter: ``rate`` tokens/second, bursts up to ``capacity``."""

    def __init__(
        self,
        rate: float,
        capacity: float | None = None,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self.capacity = capacity if capacity is not None else max(1.0, rate)
        self._tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    async def acquire(self, tokens: float = 1.0) -> float:
        """Wait until ``tokens`` are available. Returns the total time spent waiting."""
        waited = 0.0
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                deficit = (tokens - self._tokens) / self.rate
                waited += deficit
                await self._sleep(deficit)


@dataclass(frozen=True)
class RetryPolicy:
    """Exponential backoff with *full jitter* (AWS architecture blog variant).

    delay(attempt) = uniform(0, min(max_delay, base_delay * 2**attempt)), attempt from 0.
    A server-provided ``Retry-After`` takes precedence (capped at ``max_delay``).
    """

    max_attempts: int = 5
    base_delay: float = 0.5
    max_delay: float = 30.0

    def backoff(self, attempt: int, rng: random.Random) -> float:
        ceiling = min(self.max_delay, self.base_delay * (2**attempt))
        return rng.uniform(0, ceiling)


class RetryableHTTPError(Exception):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code} for {response.request.url}")
        self.response = response


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


async def call_with_retries[T](
    fn: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Sleep = asyncio.sleep,
    rng: random.Random | None = None,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Run ``fn`` retrying on transport errors and retryable HTTP statuses."""
    rng = rng or random.Random()
    for attempt in range(policy.max_attempts):
        try:
            return await fn()
        except (httpx.TransportError, RetryableHTTPError) as exc:
            if attempt == policy.max_attempts - 1:
                raise
            delay = policy.backoff(attempt, rng)
            if isinstance(exc, RetryableHTTPError):
                retry_after = _retry_after_seconds(exc.response)
                if retry_after is not None:
                    delay = min(policy.max_delay, retry_after)
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            await sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
