from __future__ import annotations

from dryfit.config import DryfitConfig
from dryfit.models import SignalTemplate


def build_templates(config: DryfitConfig) -> list[SignalTemplate]:
    templates: list[SignalTemplate] = []
    for raw in config.signals.positive:
        templates.append(
            SignalTemplate(
                template_id=raw.id,
                kind="positive_path",
                path=list(raw.path),
                count=raw.count,
                entity_type=raw.entity_type or config.success.entity_type,
                cohort_filters=list(raw.cohort_filters),
                property_constraints=dict(raw.property_constraints),
            )
        )
    for raw in config.signals.negative:
        templates.append(
            SignalTemplate(
                template_id=raw.id,
                kind="negative_path",
                path=list(raw.path),
                count=raw.count,
                entity_type=raw.entity_type or config.success.entity_type,
                cohort_filters=list(raw.cohort_filters),
                property_constraints=dict(raw.property_constraints),
            )
        )
    return templates
