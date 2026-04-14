from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class BackendConfig(BaseModel):
    kind: Literal["postgres"]
    dsn: str


ScenarioKind = Literal[
    "posthog_web",
    "telegram_chat",
    "posthog_seat_based",
    "posthog_usage_based",
    "posthog_transaction_volume",
    "posthog_storage_based",
    "posthog_contact_record",
    "posthog_feature_gated",
    "posthog_marketplace",
    "posthog_revenue_share",
    "posthog_credits_token",
    "posthog_hybrid_seat_usage",
    "posthog_freemium_to_paid",
    "posthog_event_volume",
    "posthog_business_models_combined",
]


class ScenarioConfig(BaseModel):
    kind: ScenarioKind


class ScaleConfig(BaseModel):
    duration_days: int = Field(default=30, ge=1)
    accounts: int | None = Field(default=None, ge=1)
    users: int | None = Field(default=None, ge=1)
    groups: int | None = Field(default=None, ge=0)
    users_per_account_mean: int | None = Field(default=None, ge=1)
    sessions_per_user_mean: int | None = Field(default=None, ge=1)
    messages_per_user_mean: int | None = Field(default=None, ge=1)


class SuccessConfig(BaseModel):
    event_name: str
    entity_type: str


class SignalTemplateConfig(BaseModel):
    id: str = Field(min_length=1)
    path: list[str] = Field(min_length=1)
    count: int = Field(ge=1)
    entity_type: str | None = None
    cohort_filters: list[str] = Field(default_factory=list)
    property_constraints: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class SignalsConfig(BaseModel):
    positive: list[SignalTemplateConfig] = Field(default_factory=list)
    negative: list[SignalTemplateConfig] = Field(default_factory=list)


class NoiseConfig(BaseModel):
    missing_event_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_event_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    out_of_order_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    null_property_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    anonymous_actor_probability: float = Field(default=0.02, ge=0.0, le=1.0)
    weird_property_probability: float = Field(default=0.01, ge=0.0, le=1.0)


class FakerConfig(BaseModel):
    locales: list[str] = Field(default_factory=lambda: ["en_US"])
    use_company_names: bool = True
    use_emails: bool = True


class ForgeConfig(BaseModel):
    dataset_id: str = Field(min_length=1)
    seed: int = Field(default=42)
    backend: BackendConfig
    scenario: ScenarioConfig
    scale: ScaleConfig
    success: SuccessConfig
    signals: SignalsConfig
    noise: NoiseConfig = Field(default_factory=NoiseConfig)
    faker: FakerConfig = Field(default_factory=FakerConfig)

    @model_validator(mode="after")
    def validate_signal_ids(self) -> "ForgeConfig":
        ids = [template.id for template in self.signals.positive + self.signals.negative]
        if len(ids) != len(set(ids)):
            raise ValueError("signal template ids must be unique across positive and negative templates")
        return self


def load_config(path: str | Path) -> ForgeConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return ForgeConfig.model_validate(data)
