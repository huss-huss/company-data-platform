"""Central configuration. Everything is overridable via environment variables so the same
code runs locally, in CI and under Dagster without edits."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: _env_path("CDP_DATA_DIR", PROJECT_ROOT / "data"))
    fixtures_dir: Path = field(
        default_factory=lambda: _env_path("CDP_FIXTURES_DIR", PROJECT_ROOT / "fixtures")
    )
    dbt_project_dir: Path = PROJECT_ROOT / "dbt"
    raw_bucket: str = os.environ.get("CDP_RAW_BUCKET", "cdp-raw")

    @property
    def warehouse_path(self) -> Path:
        return _env_path("CDP_WAREHOUSE", self.data_dir / "warehouse.duckdb")

    @property
    def storage_root(self) -> Path:
        return self.data_dir / "lake"


def get_settings() -> Settings:
    return Settings()
