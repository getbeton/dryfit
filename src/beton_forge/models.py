from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(slots=True)
class EventRecord:
    event_id: str
    ts: datetime
    scenario: str
    source_system: str
    entity_id: str | None
    entity_type: str | None
    actor_id: str | None
    account_id: str | None
    session_id: str | None
    event_name: str
    event_props: dict[str, JsonValue] = field(default_factory=dict)
    protected: bool = False

    def to_db_row(self) -> tuple[Any, ...]:
        return (
            self.event_id,
            self.ts,
            self.scenario,
            self.source_system,
            self.entity_id,
            self.entity_type,
            self.actor_id,
            self.account_id,
            self.session_id,
            self.event_name,
            self.event_props,
        )


@dataclass(slots=True)
class SignalTemplate:
    template_id: str
    kind: str
    path: list[str]
    count: int
    entity_type: str
    cohort_filters: list[str]
    property_constraints: dict[str, JsonValue]


@dataclass(slots=True)
class SignalInstance:
    signal_instance_id: str
    template_id: str
    kind: str
    entity_type: str
    entity_id: str
    event_ids: list[str]
    event_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GroundTruthDocument:
    dataset_id: str
    scenario: str
    success_event: str
    seed: int
    signals: list[SignalInstance]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "scenario": self.scenario,
            "success_event": self.success_event,
            "seed": self.seed,
            "signals": [signal.to_dict() for signal in self.signals],
        }


@dataclass(slots=True)
class ManifestDocument:
    dataset_id: str
    scenario: str
    seed: int
    row_count: int
    signal_instance_count: int
    time_range: dict[str, str | None]
    outputs: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GenerationResult:
    events: list[EventRecord]
    truth: GroundTruthDocument
    manifest: ManifestDocument
    output_dir: Path
