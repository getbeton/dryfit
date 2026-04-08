from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from faker import Faker

from beton_forge.config import ForgeConfig
from beton_forge.models import EventRecord


EntityMap = dict[str, list[dict[str, Any]]]


class BaseScenario(ABC):
    scenario_name: str
    source_system: str
    success_event_name: str
    primary_entity_type: str
    allowed_event_vocabulary: set[str]
    allowed_signal_entity_types: set[str]
    cohort_weights: dict[str, int]

    def __init__(self, config: ForgeConfig, fake: Faker):
        self.config = config
        self.fake = fake

    def validate_config(self) -> None:
        if self.config.success.event_name != self.success_event_name:
            raise ValueError(
                f"scenario {self.scenario_name} requires success.event_name={self.success_event_name}"
            )
        if self.config.success.entity_type not in self.allowed_signal_entity_types:
            raise ValueError(
                f"scenario {self.scenario_name} does not support success.entity_type="
                f"{self.config.success.entity_type}"
            )

        for template in self.config.signals.positive:
            self._validate_template(template.id, template.path, positive=True)
            if template.entity_type and template.entity_type not in self.allowed_signal_entity_types:
                raise ValueError(f"unsupported entity_type for template {template.id}")

        for template in self.config.signals.negative:
            self._validate_template(template.id, template.path, positive=False)
            if template.entity_type and template.entity_type not in self.allowed_signal_entity_types:
                raise ValueError(f"unsupported entity_type for template {template.id}")

    def _validate_template(self, template_id: str, path: Sequence[str], *, positive: bool) -> None:
        unknown_events = [event_name for event_name in path if event_name not in self.allowed_event_vocabulary]
        if unknown_events:
            raise ValueError(f"template {template_id} contains unknown events: {unknown_events}")
        if positive and path[-1] != self.success_event_name:
            raise ValueError(
                f"positive template {template_id} must end with {self.success_event_name}"
            )
        if not positive and path[-1] == self.success_event_name:
            raise ValueError(
                f"negative template {template_id} must not end with {self.success_event_name}"
            )

    @abstractmethod
    def build_population(self, rng) -> EntityMap:
        raise NotImplementedError

    @abstractmethod
    def generate_background_events(
        self,
        entities: EntityMap,
        rng,
        id_factory,
        duration_days: int,
    ) -> list[EventRecord]:
        raise NotImplementedError

    @abstractmethod
    def enrich_event_props(
        self,
        event_name: str,
        bound_entity: dict[str, Any],
        entity_lookup: dict[tuple[str, str], dict[str, Any]],
        rng,
    ) -> dict[str, Any]:
        raise NotImplementedError
