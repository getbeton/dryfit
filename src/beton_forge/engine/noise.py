from __future__ import annotations

from datetime import timedelta

from beton_forge.models import EventRecord


class NoiseInjector:
    def __init__(self, noise_config, rng, id_factory):
        self.config = noise_config
        self.rng = rng
        self.id_factory = id_factory

    def apply(self, events: list[EventRecord]) -> list[EventRecord]:
        final_events: list[EventRecord] = []
        duplicates: list[EventRecord] = []
        for event in events:
            if event.protected:
                final_events.append(event)
                continue

            if self.rng.random() < self.config.missing_event_probability:
                continue

            mutated = EventRecord(
                event_id=event.event_id,
                ts=event.ts,
                scenario=event.scenario,
                source_system=event.source_system,
                entity_id=event.entity_id,
                entity_type=event.entity_type,
                actor_id=event.actor_id,
                account_id=event.account_id,
                session_id=event.session_id,
                event_name=event.event_name,
                event_props=dict(event.event_props),
                protected=False,
            )

            if self.rng.random() < self.config.out_of_order_probability:
                mutated.ts = mutated.ts - timedelta(minutes=self.rng.randint(1, 120))
            if self.rng.random() < self.config.null_property_probability:
                mutated.event_props = {}
            if self.rng.random() < self.config.anonymous_actor_probability:
                mutated.actor_id = None
            if self.rng.random() < self.config.weird_property_probability:
                mutated.event_props["weird_value"] = self.rng.choice(
                    ["NaN-ish", "", "0000", -1, 999999, "unexpected_enum"]
                )

            final_events.append(mutated)

            if self.rng.random() < self.config.duplicate_event_probability:
                duplicate = EventRecord(
                    event_id=self.id_factory.next_event_id(),
                    ts=mutated.ts + timedelta(seconds=self.rng.randint(1, 90)),
                    scenario=mutated.scenario,
                    source_system=mutated.source_system,
                    entity_id=mutated.entity_id,
                    entity_type=mutated.entity_type,
                    actor_id=mutated.actor_id,
                    account_id=mutated.account_id,
                    session_id=mutated.session_id,
                    event_name=mutated.event_name,
                    event_props=dict(mutated.event_props) | {"duplicate_of": mutated.event_id},
                    protected=False,
                )
                duplicates.append(duplicate)

        final_events.extend(duplicates)
        final_events.sort(key=lambda event: (event.ts, event.event_id))
        return final_events
