"""Dagster software-defined assets: ingest -> dbt (upstream) -> resolve -> dbt (marts).

Run locally with ``dagster dev -m cdp.orchestration.definitions``.

* Ingest and resolve are Python assets with exponential, jittered retry policies.
* dbt models (and their tests, as asset checks) come from the dbt manifest via dagster-dbt,
  split into two asset groups so the resolver sits between them in the graph.
* ``daily_refresh`` materialises everything every day at 05:00 UTC.

No ``from __future__ import annotations`` here: Dagster inspects the real type of ``context``.
"""

import os
import shutil
import sys
from pathlib import Path

import duckdb
from dagster import (
    AssetExecutionContext,
    AssetKey,
    AssetSelection,
    AssetSpec,
    Backoff,
    DefaultScheduleStatus,
    Definitions,
    Jitter,
    MaterializeResult,
    RetryPolicy,
    ScheduleDefinition,
    define_asset_job,
    multi_asset,
)
from dagster_dbt import DbtCliResource, DbtProject, dbt_assets, get_asset_key_for_model

from cdp.config import get_settings
from cdp.ingest.pipeline import run_ingest
from cdp.resolve.engine import run_resolve
from cdp.transform import INDIRECT_SELECTION, MARTS_SELECT, UPSTREAM_SELECT, run_dbt

settings = get_settings()
# dbt (run as a subprocess by DbtCliResource) reads the warehouse location from here.
os.environ.setdefault("CDP_WAREHOUSE", str(settings.warehouse_path))

dbt_project = DbtProject(
    project_dir=settings.dbt_project_dir, profiles_dir=settings.dbt_project_dir
)
if not dbt_project.manifest_path.exists():
    # `dagster dev` would do this via prepare_if_dev(); doing it unconditionally keeps
    # `dagster definitions validate`, tests and deployments working from a clean checkout.
    run_dbt(settings, "parse", "--quiet")

# Prefer the dbt installed next to this interpreter (works without an activated venv).
_venv_dbt = Path(sys.executable).with_name("dbt")
DBT_EXECUTABLE = str(_venv_dbt) if _venv_dbt.exists() else (shutil.which("dbt") or "dbt")

IO_RETRY = RetryPolicy(max_retries=3, delay=5, backoff=Backoff.EXPONENTIAL, jitter=Jitter.FULL)
COMPUTE_RETRY = RetryPolicy(max_retries=2, delay=10, jitter=Jitter.PLUS_MINUS)

RAW_TABLES = ("registry_companies", "api_companies", "directory_listings", "load_manifest")
RESOLVED_TABLES = ("entity_membership", "pair_scores", "golden_records")


@multi_asset(
    name="ingest_providers",
    group_name="ingest",
    specs=[
        AssetSpec(AssetKey(["raw", t]), description=f"Raw provider data: raw.{t}", kinds={"duckdb"})
        for t in RAW_TABLES
    ],
    retry_policy=IO_RETRY,
)
def ingest_providers(context: AssetExecutionContext):
    """Fetch all providers, land untouched payloads in object storage, load idempotently."""
    report = run_ingest(get_settings())
    context.log.info(report.summary())
    for t in RAW_TABLES:
        source = next((s for s, r in report.results.items() if t.startswith(s)), None)
        meta = {}
        if source:
            r = report.results[source]
            meta = {
                "records_loaded": r.records_loaded,
                "objects_skipped": r.objects_skipped,
                "retries": report.retries.get(source, 0),
            }
        yield MaterializeResult(asset_key=AssetKey(["raw", t]), metadata=meta)


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    select=" ".join(UPSTREAM_SELECT),
    name="dbt_upstream",
    retry_policy=COMPUTE_RETRY,
)
def dbt_upstream(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build", *INDIRECT_SELECTION], context=context).stream()


@multi_asset(
    name="resolve_entities",
    group_name="resolve",
    specs=[
        AssetSpec(
            AssetKey(["resolved", t]),
            deps=[get_asset_key_for_model([dbt_upstream], "int_company_records")],
            kinds={"python", "duckdb"},
        )
        for t in RESOLVED_TABLES
    ],
    retry_policy=COMPUTE_RETRY,
)
def resolve_entities(context: AssetExecutionContext):
    """Block, score, cluster and survive; replace the resolved.* tables atomically."""
    with duckdb.connect(str(get_settings().warehouse_path)) as con:
        res = run_resolve(con)
    summary = res.summary()
    context.log.info(str(summary))
    for t in RESOLVED_TABLES:
        yield MaterializeResult(asset_key=AssetKey(["resolved", t]), metadata=summary)


@dbt_assets(
    manifest=dbt_project.manifest_path,
    project=dbt_project,
    select=" ".join(MARTS_SELECT),
    name="dbt_marts",
    retry_policy=COMPUTE_RETRY,
)
def dbt_marts(context: AssetExecutionContext, dbt: DbtCliResource):
    yield from dbt.cli(["build", *INDIRECT_SELECTION], context=context).stream()


daily_refresh = define_asset_job("daily_refresh", selection=AssetSelection.all())

daily_schedule = ScheduleDefinition(
    job=daily_refresh,
    cron_schedule="0 5 * * *",
    execution_timezone="UTC",
    default_status=DefaultScheduleStatus.RUNNING,
)

defs = Definitions(
    assets=[ingest_providers, dbt_upstream, resolve_entities, dbt_marts],
    jobs=[daily_refresh],
    schedules=[daily_schedule],
    resources={"dbt": DbtCliResource(project_dir=dbt_project, dbt_executable=DBT_EXECUTABLE)},
)
