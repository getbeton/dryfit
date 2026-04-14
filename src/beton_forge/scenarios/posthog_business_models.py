from __future__ import annotations

from typing import Any

from beton_forge.engine.timing import bounded_datetime, random_jitter_seconds
from beton_forge.models import EventRecord
from beton_forge.scenarios.base import BaseScenario, EntityMap


SEAT_BASED_EVENTS = {
    "invite_sent",
    "user_signed_up",
    "$identify",
    "role_assigned",
    "seat_activated",
    "seat_deactivated",
}
USAGE_BASED_EVENTS = {
    "api_request",
    "job_completed",
    "message_sent",
    "compute_hours_used",
}
TRANSACTION_VOLUME_EVENTS = {
    "payment_completed",
    "order_created",
    "invoice_generated",
    "refund_issued",
}
STORAGE_BASED_EVENTS = {
    "file_uploaded",
    "record_created",
    "storage_warning_shown",
}
CONTACT_RECORD_EVENTS = {
    "contact_created",
    "list_imported",
    "enrichment_completed",
    "segment_created",
}
FEATURE_GATED_EVENTS = {
    "feature_gate_shown",
    "upgrade_clicked",
    "advanced_feature_attempted",
    "downgrade",
}
MARKETPLACE_EVENTS = {
    "listing_published",
    "storefront_activated",
    "account_connected",
    "integration_enabled",
}
REVENUE_SHARE_EVENTS = {
    "booking_completed",
    "payout_processed",
    "commission_calculated",
}
CREDITS_TOKEN_EVENTS = {
    "credits_purchased",
    "credits_used",
    "low_balance_warning",
    "auto_refill_triggered",
}
FREEMIUM_TO_PAID_EVENTS = {
    "limit_reached",
    "upgrade_modal_shown",
    "feature_blocked",
    "trial_started",
}
EVENT_VOLUME_EVENTS = {
    "$pageview",
    "$autocapture",
    "custom_event_tracked",
    "source_connected",
    "schema_changed",
}

COMBINED_BUSINESS_MODEL_EVENTS = (
    SEAT_BASED_EVENTS
    | USAGE_BASED_EVENTS
    | TRANSACTION_VOLUME_EVENTS
    | STORAGE_BASED_EVENTS
    | CONTACT_RECORD_EVENTS
    | FEATURE_GATED_EVENTS
    | MARKETPLACE_EVENTS
    | REVENUE_SHARE_EVENTS
    | CREDITS_TOKEN_EVENTS
    | FREEMIUM_TO_PAID_EVENTS
    | EVENT_VOLUME_EVENTS
)

DEFAULT_COHORT_WEIGHTS = {
    "high_intent": 22,
    "medium_intent": 28,
    "low_intent": 22,
    "lurker": 16,
    "noisy_bot_like": 4,
    "power_user": 8,
}


class BasePostHogBusinessModelScenario(BaseScenario):
    source_system = "posthog"
    primary_entity_type = "account"
    allowed_signal_entity_types = {"account", "user", "session"}
    cohort_weights = DEFAULT_COHORT_WEIGHTS
    background_event_weights: dict[str, int] = {}
    background_event_count_mean = 24

    def build_population(self, rng) -> EntityMap:
        scale = self.config.scale
        account_count = scale.accounts or 200
        users_per_account_mean = scale.users_per_account_mean or 4
        sessions_per_user_mean = scale.sessions_per_user_mean or 8

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
            plan = rng.choices(["free", "team", "growth", "enterprise"], weights=[35, 35, 20, 10], k=1)[0]
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

        seeded_names = sorted(self.allowed_event_vocabulary)
        for index, event_name in enumerate(seeded_names):
            account = accounts[index % len(accounts)]
            user = users_by_account[account["id"]][0]
            session = sessions_by_user[user["id"]][0]
            events.append(self._build_event(event_name, account, user, session, rng, id_factory, duration_days))

        for account in accounts:
            user_choices = users_by_account[account["id"]]
            cohort_multiplier = {
                "high_intent": 1.5,
                "medium_intent": 1.1,
                "low_intent": 0.8,
                "lurker": 0.5,
                "noisy_bot_like": 1.2,
                "power_user": 1.7,
            }[account["cohort"]]
            event_count = max(4, int(rng.gauss(self.background_event_count_mean * cohort_multiplier, 5)))

            for _ in range(event_count):
                user = rng.choice(user_choices)
                session = rng.choice(sessions_by_user[user["id"]])
                event_name = rng.choices(
                    list(self.background_event_weights),
                    weights=list(self.background_event_weights.values()),
                    k=1,
                )[0]
                events.append(self._build_event(event_name, account, user, session, rng, id_factory, duration_days))

        return events

    def _build_event(
        self,
        event_name: str,
        account: dict[str, Any],
        user: dict[str, Any],
        session: dict[str, Any],
        rng,
        id_factory,
        duration_days: int,
    ) -> EventRecord:
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
        return EventRecord(
            event_id=id_factory.next_event_id(),
            ts=bounded_datetime(rng, duration_days),
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

    def enrich_event_props(
        self,
        event_name: str,
        bound_entity: dict[str, Any],
        entity_lookup: dict[tuple[str, str], dict[str, Any]],
        rng,
    ) -> dict[str, Any]:
        account_id = bound_entity.get("account_id", bound_entity["id"])
        account = entity_lookup.get(("account", account_id), bound_entity)
        user = entity_lookup.get(("user", bound_entity.get("user_id", bound_entity.get("id", ""))), bound_entity)
        session = entity_lookup.get(("session", bound_entity.get("id", "")))

        props: dict[str, Any] = {
            "plan": account.get("plan"),
            "account_name": account.get("name"),
            "utm_campaign": rng.choice(["launch", "retargeting", "organic", "community"]),
            "engagement_score": round(rng.uniform(0.05, 0.99), 3),
            "jitter_seconds": random_jitter_seconds(rng),
        }

        if event_name == "invite_sent":
            props["invite_role"] = rng.choice(["admin", "member", "viewer"])
        if event_name == "user_signed_up":
            props["signup_source"] = rng.choice(["email", "workspace_invite", "organic", "sales_assist"])
        if event_name == "$identify":
            props["identified_team"] = account.get("domain")
        if event_name == "role_assigned":
            props["assigned_role"] = rng.choice(["admin", "builder", "analyst", "operator"])
        if event_name == "seat_activated":
            props["seat_plan"] = account.get("plan")
        if event_name == "seat_deactivated":
            props["deactivation_reason"] = rng.choice(["inactive", "cost_reduction", "consolidation"])

        if event_name == "api_request":
            props["endpoint"] = rng.choice(["/v1/events", "/v1/query", "/v1/batch", "/v1/stream"])
        if event_name == "job_completed":
            props["job_type"] = rng.choice(["sync", "transform", "export", "backfill"])
        if event_name == "message_sent":
            props["message_channel"] = rng.choice(["email", "in_app", "slack", "webhook"])
        if event_name == "compute_hours_used":
            props["compute_hours"] = round(rng.uniform(0.1, 6.0), 2)

        if event_name == "payment_completed":
            props["payment_amount"] = round(rng.uniform(100, 5000), 2)
        if event_name == "order_created":
            props["order_value"] = round(rng.uniform(50, 2500), 2)
        if event_name == "invoice_generated":
            props["invoice_total"] = round(rng.uniform(50, 2500), 2)
        if event_name == "refund_issued":
            props["refund_reason"] = rng.choice(["fraud_review", "customer_request", "duplicate_charge"])

        if event_name == "file_uploaded":
            props["file_size_mb"] = round(rng.uniform(0.2, 240.0), 2)
        if event_name == "record_created":
            props["record_type"] = rng.choice(["profile", "document", "transaction", "audit_log"])
        if event_name == "storage_warning_shown":
            props["percent_capacity_used"] = rng.randint(80, 99)

        if event_name == "contact_created":
            props["contact_source"] = rng.choice(["manual", "form", "import", "sync"])
        if event_name == "list_imported":
            props["imported_contacts"] = rng.randint(25, 2500)
        if event_name == "enrichment_completed":
            props["enrichment_provider"] = rng.choice(["clearbit", "apollo", "internal"])
        if event_name == "segment_created":
            props["segment_type"] = rng.choice(["behavioral", "firmographic", "lifecycle"])

        if event_name == "feature_gate_shown":
            props["gated_feature"] = rng.choice(["sso", "rbac", "audit_logs", "data_retention"])
        if event_name == "upgrade_clicked":
            props["target_plan"] = rng.choice(["team", "growth", "enterprise"])
        if event_name == "advanced_feature_attempted":
            props["attempted_feature"] = rng.choice(["custom_roles", "warehouse_export", "sandbox_env"])
        if event_name == "downgrade":
            props["downgrade_reason"] = rng.choice(["budget", "unused_features", "seasonal"])

        if event_name == "listing_published":
            props["listing_category"] = rng.choice(["services", "inventory", "jobs", "digital_goods"])
        if event_name == "storefront_activated":
            props["storefront_theme"] = rng.choice(["classic", "modern", "minimal"])
        if event_name == "account_connected":
            props["connected_account_type"] = rng.choice(["stripe", "bank", "erp", "ads"])
        if event_name == "integration_enabled":
            props["integration"] = rng.choice(["slack", "github", "salesforce", "hubspot"])

        if event_name == "booking_completed":
            props["booking_value"] = round(rng.uniform(120, 6400), 2)
        if event_name == "payout_processed":
            props["payout_amount"] = round(rng.uniform(100, 5000), 2)
        if event_name == "commission_calculated":
            props["commission_amount"] = round(rng.uniform(10, 500), 2)

        if event_name == "credits_purchased":
            props["credit_pack"] = rng.choice(["starter_credits", "growth_credits", "auto_refill_bundle"])
        if event_name == "credits_used":
            props["credits_spent"] = rng.randint(1, 500)
        if event_name == "low_balance_warning":
            props["credits_remaining"] = rng.randint(1, 50)
        if event_name == "auto_refill_triggered":
            props["auto_refill_amount"] = rng.randint(100, 2000)

        if event_name == "limit_reached":
            props["limit_name"] = rng.choice(["events", "seats", "projects", "exports"])
        if event_name == "upgrade_modal_shown":
            props["modal_source"] = rng.choice(["billing_page", "feature_gate", "usage_banner"])
        if event_name == "feature_blocked":
            props["blocked_feature"] = rng.choice(["exports", "api_access", "advanced_dashboards"])
        if event_name == "trial_started":
            props["trial_length_days"] = rng.choice([7, 14, 30])

        if event_name == "$pageview":
            props["page_title"] = rng.choice(["Home", "Docs", "Settings", "Pricing"])
        if event_name == "$autocapture":
            props["dom_element"] = rng.choice(["button", "input", "link", "dropdown"])
        if event_name == "custom_event_tracked":
            props["custom_event_name"] = rng.choice(["pipeline_run", "lead_scored", "rule_executed"])
        if event_name == "source_connected":
            props["source_type"] = rng.choice(["sdk", "warehouse", "webhook", "s3"])
        if event_name == "schema_changed":
            props["schema_change_type"] = rng.choice(["property_added", "type_changed", "event_renamed"])

        if session:
            props["device"] = session.get("device")
            props["region"] = session.get("region")
        if user:
            props["user_role"] = user.get("role")

        return props


class SeatBasedPostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_seat_based"
    success_event_name = "seat_activated"
    allowed_event_vocabulary = SEAT_BASED_EVENTS
    background_event_weights = {
        "invite_sent": 18,
        "user_signed_up": 15,
        "$identify": 10,
        "role_assigned": 12,
        "seat_activated": 9,
        "seat_deactivated": 3,
    }


class UsageBasedPostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_usage_based"
    success_event_name = "job_completed"
    allowed_event_vocabulary = USAGE_BASED_EVENTS
    background_event_weights = {
        "api_request": 26,
        "job_completed": 12,
        "message_sent": 14,
        "compute_hours_used": 10,
    }


class TransactionVolumePostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_transaction_volume"
    success_event_name = "payment_completed"
    allowed_event_vocabulary = TRANSACTION_VOLUME_EVENTS
    background_event_weights = {
        "order_created": 18,
        "invoice_generated": 12,
        "payment_completed": 10,
        "refund_issued": 2,
    }


class StorageBasedPostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_storage_based"
    success_event_name = "file_uploaded"
    allowed_event_vocabulary = STORAGE_BASED_EVENTS
    background_event_weights = {
        "file_uploaded": 20,
        "record_created": 15,
        "storage_warning_shown": 3,
    }


class ContactRecordPostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_contact_record"
    success_event_name = "contact_created"
    allowed_event_vocabulary = CONTACT_RECORD_EVENTS
    background_event_weights = {
        "contact_created": 16,
        "list_imported": 8,
        "enrichment_completed": 10,
        "segment_created": 7,
    }


class FeatureGatedPostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_feature_gated"
    success_event_name = "upgrade_clicked"
    allowed_event_vocabulary = FEATURE_GATED_EVENTS
    background_event_weights = {
        "advanced_feature_attempted": 12,
        "feature_gate_shown": 14,
        "upgrade_clicked": 5,
        "downgrade": 2,
    }


class MarketplacePostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_marketplace"
    success_event_name = "listing_published"
    allowed_event_vocabulary = MARKETPLACE_EVENTS
    background_event_weights = {
        "account_connected": 15,
        "integration_enabled": 10,
        "storefront_activated": 8,
        "listing_published": 10,
    }


class RevenueSharePostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_revenue_share"
    success_event_name = "commission_calculated"
    allowed_event_vocabulary = REVENUE_SHARE_EVENTS
    background_event_weights = {
        "booking_completed": 18,
        "payout_processed": 8,
        "commission_calculated": 10,
    }


class CreditsTokenPostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_credits_token"
    success_event_name = "credits_purchased"
    allowed_event_vocabulary = CREDITS_TOKEN_EVENTS
    background_event_weights = {
        "credits_used": 20,
        "low_balance_warning": 8,
        "credits_purchased": 6,
        "auto_refill_triggered": 4,
    }


class HybridSeatUsagePostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_hybrid_seat_usage"
    success_event_name = "compute_hours_used"
    allowed_event_vocabulary = SEAT_BASED_EVENTS | {"api_request", "job_completed", "compute_hours_used"}
    background_event_weights = {
        "invite_sent": 10,
        "user_signed_up": 8,
        "$identify": 6,
        "role_assigned": 8,
        "seat_activated": 7,
        "seat_deactivated": 2,
        "api_request": 20,
        "job_completed": 10,
        "compute_hours_used": 9,
    }


class FreemiumToPaidPostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_freemium_to_paid"
    success_event_name = "trial_started"
    allowed_event_vocabulary = FREEMIUM_TO_PAID_EVENTS
    background_event_weights = {
        "limit_reached": 12,
        "upgrade_modal_shown": 10,
        "feature_blocked": 9,
        "trial_started": 5,
    }


class EventVolumePostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_event_volume"
    success_event_name = "custom_event_tracked"
    allowed_event_vocabulary = EVENT_VOLUME_EVENTS
    background_event_weights = {
        "$pageview": 20,
        "$autocapture": 16,
        "source_connected": 8,
        "schema_changed": 5,
        "custom_event_tracked": 10,
    }


class BusinessModelsCombinedPostHogScenario(BasePostHogBusinessModelScenario):
    scenario_name = "posthog_business_models_combined"
    success_event_name = "upgrade_clicked"
    allowed_event_vocabulary = COMBINED_BUSINESS_MODEL_EVENTS
    background_event_weights = {event_name: 3 for event_name in COMBINED_BUSINESS_MODEL_EVENTS} | {
        "api_request": 12,
        "$pageview": 10,
        "credits_used": 8,
        "invite_sent": 8,
        "order_created": 8,
        "file_uploaded": 8,
        "feature_gate_shown": 8,
        "upgrade_clicked": 5,
    }
    background_event_count_mean = 36
