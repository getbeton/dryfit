from pathlib import Path

import pytest

from beton_forge.config import load_config
from beton_forge.faker_utils import build_faker
from beton_forge.scenarios import SCENARIO_REGISTRY

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


@pytest.mark.parametrize("config_path", BUSINESS_MODEL_CONFIGS)
def test_business_model_configs_validate_against_scenarios(config_path: Path) -> None:
    config = load_config(config_path)
    scenario = SCENARIO_REGISTRY[config.scenario.kind](config, build_faker(config.faker.locales, config.seed))
    scenario.validate_config()
