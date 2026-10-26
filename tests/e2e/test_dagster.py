"""Execute the Dagster `daily_refresh` job in-process against a temporary warehouse."""

from __future__ import annotations

import importlib

import duckdb
import pytest

pytest.importorskip("dagster_dbt")
pytestmark = pytest.mark.e2e


def test_daily_refresh_job_materialises_every_asset(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("CDP_DATA_DIR", str(data))
    monkeypatch.setenv("CDP_WAREHOUSE", str(data / "warehouse.duckdb"))
    monkeypatch.delenv("CDP_FIXTURES_DIR", raising=False)
    module = importlib.import_module("cdp.orchestration.definitions")

    defs = module.defs
    job = defs.resolve_job_def("daily_refresh")
    result = job.execute_in_process()

    assert result.success
    materialized = {e.asset_key.to_user_string() for e in result.get_asset_materialization_events()}
    assert {
        "raw/registry_companies",
        "intermediate/int_company_records",
        "resolved/golden_records",
        "marts/dim_company",
        "marts/match_audit",
    } <= materialized
    checks = [
        e.event_specific_data
        for e in result.all_events
        if e.event_type_value == "ASSET_CHECK_EVALUATION"
    ]
    assert checks and all(c.passed for c in checks)

    with duckdb.connect(str(data / "warehouse.duckdb")) as con:
        assert con.execute("select count(*) from marts.company_source_xref").fetchone() == (515,)


def test_schedule_and_retry_policies_are_configured():
    module = importlib.import_module("cdp.orchestration.definitions")
    schedule = module.defs.resolve_schedule_def("daily_refresh_schedule")
    assert schedule.cron_schedule == "0 5 * * *"
    assert module.ingest_providers.op.retry_policy.max_retries == 3
    assert module.resolve_entities.op.retry_policy is not None
