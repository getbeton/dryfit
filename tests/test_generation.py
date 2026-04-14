from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from typer.testing import CliRunner

from beton_forge.cli import app
from beton_forge.engine.generator import generate_dataset


def test_generation_is_deterministic_for_dry_run() -> None:
    first = generate_dataset(Path("configs/posthog_mvp.yaml"), dry_run=True, skip_db_write=True)
    second = generate_dataset(Path("configs/posthog_mvp.yaml"), dry_run=True, skip_db_write=True)

    assert first.manifest.row_count == second.manifest.row_count
    assert first.manifest.signal_instance_count == second.manifest.signal_instance_count
    assert first.truth.to_dict() == second.truth.to_dict()
    assert [event.event_id for event in first.events[:20]] == [event.event_id for event in second.events[:20]]


def test_generate_dataset_uses_dsn_override_for_db_writes() -> None:
    with TemporaryDirectory() as tmpdir:
        with (
            patch("beton_forge.engine.generator.write_events") as write_events,
            patch("beton_forge.engine.generator.write_ground_truth"),
            patch("beton_forge.engine.generator.write_manifest"),
        ):
            generate_dataset(
                Path("configs/posthog_mvp.yaml"),
                output_dir=tmpdir,
                dsn="postgresql://override-host/beton_forge",
            )

    write_events.assert_called_once()
    assert write_events.call_args.args[0] == "postgresql://override-host/beton_forge"


def test_cli_passes_dsn_override_to_generator() -> None:
    runner = CliRunner()

    with patch("beton_forge.cli.generate_dataset") as generate:
        result = runner.invoke(
            app,
            [
                "-c",
                "configs/posthog_mvp.yaml",
                "--dry-run",
                "--dsn",
                "postgresql://override-host/beton_forge",
            ],
        )

    assert result.exit_code == 0
    generate.assert_called_once()
    assert generate.call_args.kwargs["dsn"] == "postgresql://override-host/beton_forge"
