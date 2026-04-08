from pathlib import Path

from beton_forge.engine.generator import generate_dataset


def test_generation_is_deterministic_for_dry_run() -> None:
    first = generate_dataset(Path("configs/posthog_mvp.yaml"), dry_run=True, skip_db_write=True)
    second = generate_dataset(Path("configs/posthog_mvp.yaml"), dry_run=True, skip_db_write=True)

    assert first.manifest.row_count == second.manifest.row_count
    assert first.manifest.signal_instance_count == second.manifest.signal_instance_count
    assert first.truth.to_dict() == second.truth.to_dict()
    assert [event.event_id for event in first.events[:20]] == [event.event_id for event in second.events[:20]]
