from __future__ import annotations

import random
from pathlib import Path

from beton_forge.config import ForgeConfig, load_config
from beton_forge.faker_utils import build_faker
from beton_forge.models import GenerationResult, GroundTruthDocument, ManifestDocument
from beton_forge.postgres import write_events
from beton_forge.scenarios import SCENARIO_REGISTRY
from beton_forge.signals.instantiator import SignalInstantiator
from beton_forge.signals.models import build_templates
from beton_forge.engine.ids import IdFactory
from beton_forge.engine.noise import NoiseInjector
from beton_forge.truth import write_ground_truth, write_manifest


def generate_dataset(
    config_path: str | Path,
    output_dir: str | Path | None = None,
    *,
    dsn: str | None = None,
    skip_db_write: bool = False,
    dry_run: bool = False,
) -> GenerationResult:
    config = load_config(config_path) if not isinstance(config_path, ForgeConfig) else config_path
    return generate_from_config(
        config,
        output_dir=output_dir,
        dsn=dsn,
        skip_db_write=skip_db_write,
        dry_run=dry_run,
    )


def generate_from_config(
    config: ForgeConfig,
    output_dir: str | Path | None = None,
    *,
    dsn: str | None = None,
    skip_db_write: bool = False,
    dry_run: bool = False,
) -> GenerationResult:
    rng = random.Random(config.seed)
    fake = build_faker(config.faker.locales, config.seed)
    scenario_cls = SCENARIO_REGISTRY[config.scenario.kind]
    scenario = scenario_cls(config, fake)
    scenario.validate_config()

    id_factory = IdFactory()
    entities = scenario.build_population(rng)
    raw_templates = build_templates(config)

    signal_events, truth_signals = SignalInstantiator(scenario, rng, id_factory).instantiate(
        raw_templates,
        entities,
        config.scale.duration_days,
    )
    background_events = scenario.generate_background_events(
        entities,
        rng,
        id_factory,
        config.scale.duration_days,
    )
    final_events = NoiseInjector(config.noise, rng, id_factory).apply(signal_events + background_events)

    artifact_dir = Path(output_dir or Path("artifacts") / config.dataset_id)
    truth_path = artifact_dir / "ground_truth.json"
    manifest_path = artifact_dir / "manifest.json"

    time_range = {
        "min_ts": final_events[0].ts.isoformat().replace("+00:00", "Z") if final_events else None,
        "max_ts": final_events[-1].ts.isoformat().replace("+00:00", "Z") if final_events else None,
    }
    manifest = ManifestDocument(
        dataset_id=config.dataset_id,
        scenario=config.scenario.kind,
        seed=config.seed,
        row_count=len(final_events),
        signal_instance_count=len(truth_signals),
        time_range=time_range,
        outputs={
            "ground_truth": str(truth_path.relative_to(artifact_dir)),
            "manifest": str(manifest_path.relative_to(artifact_dir)),
        },
    )
    truth = GroundTruthDocument(
        dataset_id=config.dataset_id,
        scenario=config.scenario.kind,
        success_event=config.success.event_name,
        seed=config.seed,
        signals=truth_signals,
    )

    if not dry_run:
        write_ground_truth(truth, truth_path)
        write_manifest(manifest, manifest_path)
        if not skip_db_write:
            write_events(dsn or config.backend.dsn, final_events)

    return GenerationResult(
        events=final_events,
        truth=truth,
        manifest=manifest,
        output_dir=artifact_dir,
    )
