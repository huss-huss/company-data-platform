"""End-to-end: fixtures -> raw -> dbt upstream -> resolve -> dbt marts, in a temp warehouse."""

from __future__ import annotations

import json

import duckdb
import pytest
from typer.testing import CliRunner

from cdp.cli import app
from cdp.ingest.pipeline import run_ingest
from cdp.resolve.engine import run_resolve
from cdp.resolve.evaluate import evaluate, load_ground_truth
from cdp.transform import build

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    data = tmp_path_factory.mktemp("e2e") / "data"
    mp.setenv("CDP_DATA_DIR", str(data))
    mp.delenv("CDP_WAREHOUSE", raising=False)
    mp.delenv("CDP_FIXTURES_DIR", raising=False)
    from cdp.config import Settings

    settings = Settings()
    ingest_report = run_ingest(settings)
    build(settings, "upstream")
    with duckdb.connect(str(settings.warehouse_path)) as con:
        resolution = run_resolve(con)
    build(settings, "marts")
    yield settings, ingest_report, resolution
    mp.undo()


def q(settings, sql):
    with duckdb.connect(str(settings.warehouse_path)) as con:
        return con.execute(sql).fetchall()


def test_raw_layer_loaded_all_records(pipeline):
    settings, report, _ = pipeline
    assert {s: r.records_loaded for s, r in report.results.items()} == {
        "registry": 176,
        "api": 175,
        "directory": 164,
    }
    assert q(settings, "select count(*) from raw.load_manifest") == [(6,)]


def test_marts_are_consistent(pipeline):
    settings, _, res = pipeline
    [(entities,)] = q(settings, "select count(*) from marts.dim_company")
    [(xref,)] = q(settings, "select count(*) from marts.company_source_xref")
    assert entities == res.n_entities
    assert xref == 515
    # dedup actually happened: far fewer entities than records
    assert entities < xref * 0.5
    [(multi,)] = q(settings, "select count(*) from marts.dim_company where source_count = 3")
    assert multi > 50


def test_golden_record_provenance_points_at_member_records(pipeline):
    settings, _, _ = pipeline
    rows = q(
        settings,
        """
        select d.entity_id, d.field_provenance from marts.dim_company d
        where d.source_count = 3 limit 20""",
    )
    for entity_id, provenance in rows:
        members = {
            r
            for (r,) in q(
                settings,
                f"""select record_id from marts.company_source_xref
                                                 where entity_id = '{entity_id}'""",
            )
        }
        assert set(json.loads(provenance).values()) <= members
        assert json.loads(provenance)["company_name"].startswith("registry:")


def test_quality_against_ground_truth(pipeline):
    settings, _, res = pipeline
    m = evaluate(res, load_ground_truth(settings.fixtures_dir / "ground_truth.csv"))
    assert m.precision >= 0.97
    assert m.recall >= 0.95
    assert m.blocking_recall >= 0.98
    assert m.uncertain_pairs > 0  # hard negatives are routed to review, not merged
    [(queue,)] = q(settings, "select count(*) from marts.match_review_queue")
    assert queue == m.uncertain_pairs


def test_rerun_is_idempotent_and_ids_are_stable(pipeline):
    settings, _, first = pipeline
    second_ingest = run_ingest(settings)
    assert sum(r.records_loaded for r in second_ingest.results.values()) == 0
    with duckdb.connect(str(settings.warehouse_path)) as con:
        second = run_resolve(con)
    assert second.membership == first.membership


def test_full_dbt_build_passes_and_cli_eval_reports(pipeline, tmp_path):
    settings, _, _ = pipeline
    build(settings, "all")  # every model + every test, including contracts
    out = tmp_path / "metrics.json"
    result = CliRunner().invoke(app, ["eval", "--json", str(out)])
    assert result.exit_code == 0, result.output
    assert "precision" in result.output
    assert json.loads(out.read_text())["records"] == 515
