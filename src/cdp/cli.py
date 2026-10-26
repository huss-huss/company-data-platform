"""`cdp` command-line interface: ingest | transform | resolve | eval | run."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from cdp import __version__
from cdp.config import get_settings

app = typer.Typer(
    help="company-data-platform: multi-source company entity resolution.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def ingest(
    source: Annotated[list[str] | None, typer.Option("--source", "-s")] = None,
    fail_every: Annotated[int, typer.Option(help="Inject a 429/503 every N requests.")] = 4,
) -> None:
    """Fetch all providers (offline fixtures), land raw payloads, load idempotently."""
    from cdp.ingest.pipeline import run_ingest

    report = run_ingest(get_settings(), sources=source, fail_every=fail_every)
    typer.echo(report.summary())


@app.command()
def transform(
    stage: Annotated[str, typer.Option(help="upstream | marts | all")] = "upstream",
) -> None:
    """dbt build. 'upstream' = seeds, staging, intermediate (inputs to resolve)."""
    from cdp.transform import build

    if stage not in ("upstream", "marts", "all"):
        raise typer.BadParameter("stage must be upstream, marts or all")
    build(get_settings(), stage)  # type: ignore[arg-type]


@app.command()
def resolve(
    publish: Annotated[bool, typer.Option(help="Build the dbt marts afterwards.")] = True,
) -> None:
    """Block, score, cluster and survive; write resolved.* (and build marts)."""
    from cdp.resolve.engine import run_resolve
    from cdp.transform import build

    settings = get_settings()
    with duckdb.connect(str(settings.warehouse_path)) as con:
        res = run_resolve(con)
    typer.echo(json.dumps(res.summary()))
    if publish:
        build(settings, "marts")


@app.command("eval")
def evaluate_cmd(
    truth: Annotated[Path | None, typer.Option(help="Ground-truth CSV.")] = None,
    output: Annotated[Path | None, typer.Option("--json", help="Write metrics JSON here.")] = None,
) -> None:
    """Score the current resolution against labelled ground truth."""
    from cdp.resolve.engine import resolve_records
    from cdp.resolve.evaluate import baseline_metrics, evaluate, load_ground_truth
    from cdp.resolve.records import load_records

    settings = get_settings()
    truth = truth or settings.fixtures_dir / "ground_truth.csv"
    with duckdb.connect(str(settings.warehouse_path)) as con:
        res = resolve_records(load_records(con))
    labels = load_ground_truth(truth)
    metrics = evaluate(res, labels).as_dict()
    metrics["baseline_exact_name_country"] = baseline_metrics(res, labels)
    width = max(map(len, metrics))
    for key, value in metrics.items():
        typer.echo(f"{key:<{width}}  {value}")
    if output:
        output.write_text(json.dumps(metrics, indent=2) + "\n")


@app.command()
def run(fail_every: Annotated[int, typer.Option()] = 4) -> None:
    """Full pipeline: ingest -> dbt upstream -> resolve -> dbt marts."""
    ingest(source=None, fail_every=fail_every)
    transform(stage="upstream")
    resolve(publish=True)


if __name__ == "__main__":
    app()
