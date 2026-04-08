from pathlib import Path

import pytest

from beton_forge.config import load_config
from beton_forge.faker_utils import build_faker
from beton_forge.scenarios import SCENARIO_REGISTRY


def test_posthog_config_validates_against_scenario() -> None:
    config = load_config(Path("configs/posthog_mvp.yaml"))
    scenario = SCENARIO_REGISTRY[config.scenario.kind](config, build_faker(config.faker.locales, config.seed))
    scenario.validate_config()


def test_negative_paths_cannot_end_in_success() -> None:
    config = load_config(Path("configs/posthog_mvp.yaml"))
    config.signals.negative[0].path = ["page_billing", "purchase"]
    scenario = SCENARIO_REGISTRY[config.scenario.kind](config, build_faker(config.faker.locales, config.seed))
    with pytest.raises(ValueError):
        scenario.validate_config()
