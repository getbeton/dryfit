from __future__ import annotations

from typing import Any

from beton_forge.models import EventRecord
from beton_forge.scenarios.base import BaseScenario, EntityMap
from beton_forge.engine.timing import bounded_datetime, random_jitter_seconds


class TelegramChatScenario(BaseScenario):
    scenario_name = "telegram_chat"
    source_system = "telegram"
    success_event_name = "event_signup"
    primary_entity_type = "user"
    allowed_event_vocabulary = {
        "message_sent",
        "reply_sent",
        "reply_received",
        "reaction_given",
        "reaction_received",
        "event_signup",
        "leave_group",
    }
    allowed_signal_entity_types = {"user", "group"}
    cohort_weights = {
        "high_intent": 18,
        "medium_intent": 28,
        "low_intent": 22,
        "lurker": 20,
        "noisy_bot_like": 6,
        "power_user": 6,
    }

    def build_population(self, rng) -> EntityMap:
        scale = self.config.scale
        user_count = scale.users or 700
        group_count = scale.groups or max(10, user_count // 12)
        groups: list[dict[str, Any]] = []
        users: list[dict[str, Any]] = []

        for group_index in range(1, group_count + 1):
            groups.append(
                {
                    "id": f"group_{group_index:04d}",
                    "entity_type": "group",
                    "topic": self.fake.bs().replace(" ", "-"),
                }
            )

        for user_index in range(1, user_count + 1):
            cohort = rng.choices(
                list(self.cohort_weights),
                weights=list(self.cohort_weights.values()),
                k=1,
            )[0]
            joined_group_count = max(1, min(len(groups), int(rng.gauss(3, 1))))
            joined_groups = rng.sample(groups, k=joined_group_count)
            users.append(
                {
                    "id": f"user_{user_index:05d}",
                    "entity_type": "user",
                    "cohort": cohort,
                    "username": self.fake.user_name(),
                    "display_name": self.fake.name(),
                    "group_ids": [group["id"] for group in joined_groups],
                }
            )

        return {"user": users, "group": groups}

    def generate_background_events(self, entities, rng, id_factory, duration_days) -> list[EventRecord]:
        events: list[EventRecord] = []
        groups_by_id = {group["id"]: group for group in entities["group"]}
        event_weights = {
            "message_sent": 32,
            "reply_sent": 18,
            "reply_received": 16,
            "reaction_given": 14,
            "reaction_received": 12,
            "event_signup": 2,
            "leave_group": 6,
        }
        for user in entities["user"]:
            cohort_multiplier = {
                "high_intent": 1.4,
                "medium_intent": 1.0,
                "low_intent": 0.7,
                "lurker": 0.35,
                "noisy_bot_like": 1.6,
                "power_user": 1.8,
            }[user["cohort"]]
            event_count = max(3, int(rng.gauss((self.config.scale.messages_per_user_mean or 14) * cohort_multiplier, 3)))
            for _ in range(event_count):
                group_id = rng.choice(user["group_ids"])
                group = groups_by_id[group_id]
                event_name = rng.choices(
                    list(event_weights),
                    weights=list(event_weights.values()),
                    k=1,
                )[0]
                props = self.enrich_event_props(
                    event_name,
                    user,
                    {("group", group["id"]): group},
                    rng,
                )
                events.append(
                    EventRecord(
                        event_id=id_factory.next_event_id(),
                        ts=bounded_datetime(rng, duration_days),
                        scenario=self.scenario_name,
                        source_system=self.source_system,
                        entity_id=user["id"],
                        entity_type="user",
                        actor_id=user["id"],
                        account_id=None,
                        session_id=None,
                        event_name=event_name,
                        event_props=props | {"group_id": group_id},
                    )
                )
        return events

    def enrich_event_props(self, event_name, bound_entity, entity_lookup, rng) -> dict[str, Any]:
        group = next((entity for entity in entity_lookup.values() if "topic" in entity), None)
        props: dict[str, Any] = {
            "username": bound_entity.get("username"),
            "topic": group.get("topic") if group else None,
            "language": rng.choice(["en", "en-GB", "en-US", "de", "fr"]),
            "jitter_seconds": random_jitter_seconds(rng),
        }
        if event_name in {"message_sent", "reply_sent"}:
            props["message_preview"] = self.fake.sentence(nb_words=8)
        if event_name in {"reaction_given", "reaction_received"}:
            props["emoji"] = rng.choice(["thumbs_up", "fire", "rocket", "eyes", "party"])
        if event_name == "event_signup":
            props["signup_type"] = rng.choice(["webinar", "ama", "cohort", "community_event"])
        if event_name == "leave_group":
            props["leave_reason"] = rng.choice(["muted", "inactive", "too_noisy", "temporary"])
        return props
