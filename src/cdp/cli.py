"""`cdp` command-line interface."""

from __future__ import annotations

import typer

from cdp import __version__

app = typer.Typer(help="company-data-platform pipeline CLI", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
