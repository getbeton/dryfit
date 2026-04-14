from __future__ import annotations

from pathlib import Path

import typer

from dryfit.engine.generator import generate_dataset

app = typer.Typer(help="Generate synthetic benchmark datasets for product analytics agents.")


@app.command()
def generate(
    config: Path = typer.Option(..., "--config", "-c", exists=True, readable=True),
    output_dir: Path | None = typer.Option(None, "--output-dir"),
    dsn: str | None = typer.Option(
        None,
        "--dsn",
        help="Override the PostgreSQL DSN for this run without editing the config file.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    skip_db_write: bool = typer.Option(False, "--skip-db-write"),
    print_summary: bool = typer.Option(False, "--print-summary"),
) -> None:
    result = generate_dataset(
        config,
        output_dir=output_dir,
        dsn=dsn,
        dry_run=dry_run,
        skip_db_write=skip_db_write,
    )
    if print_summary or dry_run:
        typer.echo(f"dataset_id: {result.manifest.dataset_id}")
        typer.echo(f"scenario: {result.manifest.scenario}")
        typer.echo(f"rows: {result.manifest.row_count}")
        typer.echo(f"signal_instances: {result.manifest.signal_instance_count}")
        typer.echo(f"output_dir: {result.output_dir}")
