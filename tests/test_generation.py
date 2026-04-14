from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from typer.testing import CliRunner

from dryfit.cli import app
from dryfit.engine.generator import generate_dataset
from dryfit.scenarios.posthog_business_models import COMBINED_BUSINESS_MODEL_EVENTS

BUSINESS_MODEL_CONFIGS = [
    Path("configs/posthog_seat_based_mvp.yaml"),
    Path("configs/posthog_usage_based_mvp.yaml"),
    Path("configs/posthog_transaction_volume_mvp.yaml"),
    Path("configs/posthog_storage_based_mvp.yaml"),
    Path("configs/posthog_contact_record_mvp.yaml"),
    Path("configs/posthog_feature_gated_mvp.yaml"),
    Path("configs/posthog_marketplace_mvp.yaml"),
    Path("configs/posthog_revenue_share_mvp.yaml"),
    Path("configs/posthog_credits_token_mvp.yaml"),
    Path("configs/posthog_hybrid_seat_usage_mvp.yaml"),
    Path("configs/posthog_freemium_to_paid_mvp.yaml"),
    Path("configs/posthog_event_volume_mvp.yaml"),
    Path("configs/posthog_business_models_combined_mvp.yaml"),
]


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
            patch("dryfit.engine.generator.write_events") as write_events,
            patch("dryfit.engine.generator.write_ground_truth"),
            patch("dryfit.engine.generator.write_manifest"),
        ):
            generate_dataset(
                Path("configs/posthog_mvp.yaml"),
                output_dir=tmpdir,
                dsn="postgresql://override-host/dryfit",
            )

    write_events.assert_called_once()
    assert write_events.call_args.args[0] == "postgresql://override-host/dryfit"


def test_cli_passes_dsn_override_to_generator() -> None:
    runner = CliRunner()

    with patch("dryfit.cli.generate_dataset") as generate:
        result = runner.invoke(
            app,
            [
                "-c",
                "configs/posthog_mvp.yaml",
                "--dry-run",
                "--dsn",
                "postgresql://override-host/dryfit",
            ],
        )

    assert result.exit_code == 0
    generate.assert_called_once()
    assert generate.call_args.kwargs["dsn"] == "postgresql://override-host/dryfit"


def test_business_model_configs_generate_non_empty_dry_runs() -> None:
    for config_path in BUSINESS_MODEL_CONFIGS:
        result = generate_dataset(config_path, dry_run=True, skip_db_write=True)
        assert result.manifest.row_count > 0, config_path


def test_combined_business_model_config_covers_all_researched_events() -> None:
    result = generate_dataset(Path("configs/posthog_business_models_combined_mvp.yaml"), dry_run=True, skip_db_write=True)
    generated_events = {event.event_name for event in result.events}

    assert COMBINED_BUSINESS_MODEL_EVENTS.issubset(generated_events)
