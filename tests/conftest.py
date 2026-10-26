from __future__ import annotations

from pathlib import Path

import pytest

from cdp.config import PROJECT_ROOT, Settings


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings isolated to a temp dir; fixtures are the committed ones."""
    monkeypatch.setenv("CDP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("CDP_WAREHOUSE", raising=False)
    monkeypatch.setenv("CDP_FIXTURES_DIR", str(PROJECT_ROOT / "fixtures"))
    return Settings()


class FakeClock:
    """Deterministic monotonic clock + async sleep that advances it instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()
