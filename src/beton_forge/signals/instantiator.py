from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from beton_forge.engine.timing import bounded_datetime
from beton_forge.models import EventRecord, SignalInstance, SignalTemplate


class SignalInstantiator:
    def __init__(self, scenario, rng, id_factory):
        self.scenario = scenario
        self.rng = rng
        self.id_factory = id_factory

    def instantiate(
        self,
        templates: list[SignalTemplate],
        entities: dict[str, list[dict[str, Any]]],
        duration_days: int,
    ) -> tuple[list[EventRecord], list[SignalInstance]]:
        events: list[EventRecord] = []
        truth: list[SignalInstance] = []
        session_pool_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for session in entities.get("session", []):
            session_pool_by_user[session["user_id"]].append(session)

        for template in templates:
            candidates = self._eligible_entities(entities.get(template.entity_type, []), template)
            if not candidates:
                raise ValueError(f"no eligible entities available for template {template.template_id}")
            for _ in range(template.count):
                bound_entity = self.rng.choice(candidates)
                account_id = bound_entity["id"] if template.entity_type == "account" else bound_entity.get("account_id")
                actor_id = bound_entity["id"] if template.entity_type == "user" else None
                session_id = None
                if template.entity_type == "session":
                    session_id = bound_entity["id"]
                    actor_id = bound_entity.get("user_id")
                    account_id = bound_entity.get("account_id")
                elif actor_id and actor_id in session_pool_by_user:
                    session_id = self.rng.choice(session_pool_by_user[actor_id])["id"]

                start_ts = bounded_datetime(self.rng, duration_days)
                event_ids: list[str] = []
                event_names: list[str] = []
                for step, event_name in enumerate(template.path):
                    event_id = self.id_factory.next_event_id()
                    event_ids.append(event_id)
                    event_names.append(event_name)
                    event_lookup = {(template.entity_type, bound_entity["id"]): bound_entity}
                    props = self.scenario.enrich_event_props(event_name, bound_entity, event_lookup, self.rng)
                    props["template_id"] = template.template_id
                    event = EventRecord(
                        event_id=event_id,
                        ts=start_ts + timedelta(minutes=step * self.rng.randint(5, 180)),
                        scenario=self.scenario.scenario_name,
                        source_system=self.scenario.source_system,
                        entity_id=bound_entity["id"],
                        entity_type=template.entity_type,
                        actor_id=actor_id,
                        account_id=account_id,
                        session_id=session_id,
                        event_name=event_name,
                        event_props=props,
                        protected=True,
                    )
                    events.append(event)

                truth.append(
                    SignalInstance(
                        signal_instance_id=self.id_factory.next_signal_instance_id(),
                        template_id=template.template_id,
                        kind=template.kind,
                        entity_type=template.entity_type,
                        entity_id=bound_entity["id"],
                        event_ids=event_ids,
                        event_names=event_names,
                    )
                )

        return events, truth

    def _eligible_entities(
        self,
        entities: list[dict[str, Any]],
        template: SignalTemplate,
    ) -> list[dict[str, Any]]:
        if not template.cohort_filters:
            return entities
        return [entity for entity in entities if entity.get("cohort") in template.cohort_filters]
