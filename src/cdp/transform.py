"""Thin wrapper around dbt's programmatic runner.

The warehouse path is passed to dbt through ``CDP_WAREHOUSE`` (read by ``dbt/profiles.yml``),
so the CLI, tests and Dagster all point dbt at the same file without editing profiles.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Literal

from cdp.config import Settings

# The pipeline builds dbt in two passes around the Python resolver.
UPSTREAM_SELECT = ["path:seeds", "path:models/staging", "path:models/intermediate"]
MARTS_SELECT = ["path:models/marts"]
Stage = Literal["upstream", "marts", "all"]


class DbtError(RuntimeError):
    pass


@contextmanager
def warehouse_env(settings: Settings):
    previous = os.environ.get("CDP_WAREHOUSE")
    os.environ["CDP_WAREHOUSE"] = str(settings.warehouse_path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CDP_WAREHOUSE", None)
        else:
            os.environ["CDP_WAREHOUSE"] = previous


def dbt_args(settings: Settings, command: str, *extra: str) -> list[str]:
    project = str(settings.dbt_project_dir)
    return [command, "--project-dir", project, "--profiles-dir", project, *extra]


def run_dbt(settings: Settings, command: str, *extra: str) -> None:
    from dbt.cli.main import dbtRunner  # heavy import, keep it lazy

    settings.warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    with warehouse_env(settings):
        result = dbtRunner().invoke(dbt_args(settings, command, *extra))
    if not result.success:
        raise DbtError(f"dbt {command} failed: {result.exception or 'see dbt output above'}")


def build(settings: Settings, stage: Stage = "all") -> None:
    select = {"upstream": UPSTREAM_SELECT, "marts": MARTS_SELECT, "all": []}[stage]
    # cautious: a test runs only when *all* models it references are selected, so mart
    # tests that also touch intermediate models do not run in the upstream pass.
    extra = ["--select", *select, "--indirect-selection", "cautious"] if select else []
    run_dbt(settings, "build", *extra)
