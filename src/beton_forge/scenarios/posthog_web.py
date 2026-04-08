from __future__ import annotations

from typing import Any

from beton_forge.models import EventRecord
from beton_forge.scenarios.base import BaseScenario, EntityMap
from beton_forge.engine.timing import bounded_datetime, random_jitter_seconds


class PostHogWebScenario(BaseScenario):
    scenario_name = "posthog_web"
    source_system = "posthog"
    success_event_name = "purchase"
    primary_entity_type = "account"
    allowed_event_vocabulary = {
        "page_home",
        "page_pricing",
        "page_billing",
        "page_contacts",
        "invite_teammate",
        "api_key_created",
        "integration_connected",
        "support_ticket_opened",
        "purchase",
    }
    allowed_signal_entity_types = {"account", "user", "session"}
    cohort_weights = {
        "high_intent": 22,
        "medium_intent": 28,
        "low_intent": 22,
        "lurker": 16,
        "noisy_bot_like": 4,
        "power_user": 8,
    }

    def build_population(self, rng) -> EntityMap:
        scale = self.config.scale
        account_count = scale.accounts or 100
        users_per_account_mean = scale.users_per_account_mean or 4
        sessions_per_user_mean = scale.sessions_per_user_mean or 10

        accounts: list[dict[str, Any]] = []
        users: list[dict[str, Any]] = []
        sessions: list[dict[str, Any]] = []

        for account_index in range(1, account_count + 1):
            account_id = f"acct_{account_index:05d}"
            cohort = rng.choices(
                list(self.cohort_weights),
                weights=list(self.cohort_weights.values()),
                k=1,
            )[0]
            plan = rng.choices(["free", "team", "growth", "enterprise"], weights=[40, 30, 20, 10], k=1)[0]
            account = {
                "id": account_id,
                "entity_type": "account",
                "cohort": cohort,
                "name": self.fake.company(),
                "plan": plan,
                "domain": self.fake.domain_name(),
            }
            accounts.append(account)

            user_count = max(1, int(rng.gauss(users_per_account_mean, 1.0)))
            for _ in range(user_count):
                user_id = f"user_{len(users) + 1:05d}"
                role = rng.choice(["admin", "builder", "analyst", "operator"])
                user = {
                    "id": user_id,
                    "entity_type": "user",
                    "account_id": account_id,
                    "cohort": cohort,
                    "name": self.fake.name(),
                    "email": self.fake.email() if self.config.faker.use_emails else None,
                    "role": role,
                }
                users.append(user)

                session_count = max(1, int(rng.gauss(sessions_per_user_mean, 2.0)))
                for _ in range(session_count):
                    session_id = f"sess_{len(sessions) + 1:06d}"
                    sessions.append(
                        {
                            "id": session_id,
                            "entity_type": "session",
                            "account_id": account_id,
                            "user_id": user_id,
                            "cohort": cohort,
                            "device": rng.choice(["desktop", "mobile_web", "tablet"]),
                            "region": self.fake.country_code(),
                        }
                    )

        return {"account": accounts, "user": users, "session": sessions}

    def generate_background_events(self, entities, rng, id_factory, duration_days) -> list[EventRecord]:
        events: list[EventRecord] = []
        accounts = entities["account"]
        users_by_account: dict[str, list[dict[str, Any]]] = {}
        sessions_by_user: dict[str, list[dict[str, Any]]] = {}
        for user in entities["user"]:
            users_by_account.setdefault(user["account_id"], []).append(user)
        for session in entities["session"]:
            sessions_by_user.setdefault(session["user_id"], []).append(session)

        page_weights = {
            "page_home": 34,
            "page_pricing": 18,
            "page_billing": 10,
            "page_contacts": 8,
            "invite_teammate": 5,
            "api_key_created": 4,
            "integration_connected": 4,
            "support_ticket_opened": 3,
            "purchase": 1,
        }

        for account in accounts:
            user_choices = users_by_account.get(account["id"], [])
            cohort_multiplier = {
                "high_intent": 1.5,
                "medium_intent": 1.1,
                "low_intent": 0.8,
                "lurker": 0.5,
                "noisy_bot_like": 1.2,
                "power_user": 1.7,
            }[account["cohort"]]
            event_count = max(4, int(rng.gauss(24 * cohort_multiplier, 5)))
            for _ in range(event_count):
                user = rng.choice(user_choices)
                session = rng.choice(sessions_by_user[user["id"]])
                event_name = rng.choices(
                    list(page_weights),
                    weights=list(page_weights.values()),
                    k=1,
                )[0]
                ts = bounded_datetime(rng, duration_days)
                props = self.enrich_event_props(
                    event_name,
                    account,
                    {
                        ("account", account["id"]): account,
                        ("user", user["id"]): user,
                        ("session", session["id"]): session,
                    },
                    rng,
                )
                events.append(
                    EventRecord(
                        event_id=id_factory.next_event_id(),
                        ts=ts,
                        scenario=self.scenario_name,
                        source_system=self.source_system,
                        entity_id=account["id"],
                        entity_type="account",
                        actor_id=user["id"],
                        account_id=account["id"],
                        session_id=session["id"],
                        event_name=event_name,
                        event_props=props,
                    )
                )
        return events

    def enrich_event_props(self, event_name, bound_entity, entity_lookup, rng) -> dict[str, Any]:
        account = entity_lookup.get(("account", bound_entity["id"]), bound_entity)
        page_title_map = {
            "page_home": "Homepage",
            "page_pricing": "Pricing",
            "page_billing": "Billing",
            "page_contacts": "Contacts",
        }
        props: dict[str, Any] = {
            "plan": account.get("plan"),
            "account_name": account.get("name"),
            "utm_campaign": rng.choice(["launch", "retargeting", "organic", "community"]),
        }
        if event_name.startswith("page_"):
            props["page_title"] = page_title_map.get(event_name, event_name.replace("_", " ").title())
        if event_name == "invite_teammate":
            props["invite_role"] = rng.choice(["admin", "member", "viewer"])
        if event_name == "api_key_created":
            props["key_scope"] = rng.choice(["server", "read_only", "warehouse"])
        if event_name == "integration_connected":
            props["integration"] = rng.choice(["slack", "github", "salesforce", "hubspot"])
        if event_name == "support_ticket_opened":
            props["ticket_priority"] = rng.choice(["low", "medium", "high"])
        if event_name == "purchase":
            props["purchase_value"] = round(rng.uniform(49, 2999), 2)
            props["billing_cycle"] = rng.choice(["monthly", "annual"])
        props["engagement_score"] = round(rng.uniform(0.05, 0.99), 3)
        props["jitter_seconds"] = random_jitter_seconds(rng)
        return props
