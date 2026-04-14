from beton_forge.scenarios.posthog_business_models import (
    BusinessModelsCombinedPostHogScenario,
    ContactRecordPostHogScenario,
    CreditsTokenPostHogScenario,
    EventVolumePostHogScenario,
    FeatureGatedPostHogScenario,
    FreemiumToPaidPostHogScenario,
    HybridSeatUsagePostHogScenario,
    MarketplacePostHogScenario,
    RevenueSharePostHogScenario,
    SeatBasedPostHogScenario,
    StorageBasedPostHogScenario,
    TransactionVolumePostHogScenario,
    UsageBasedPostHogScenario,
)
from beton_forge.scenarios.posthog_web import PostHogWebScenario
from beton_forge.scenarios.telegram_chat import TelegramChatScenario

SCENARIO_REGISTRY = {
    "posthog_web": PostHogWebScenario,
    "telegram_chat": TelegramChatScenario,
    "posthog_seat_based": SeatBasedPostHogScenario,
    "posthog_usage_based": UsageBasedPostHogScenario,
    "posthog_transaction_volume": TransactionVolumePostHogScenario,
    "posthog_storage_based": StorageBasedPostHogScenario,
    "posthog_contact_record": ContactRecordPostHogScenario,
    "posthog_feature_gated": FeatureGatedPostHogScenario,
    "posthog_marketplace": MarketplacePostHogScenario,
    "posthog_revenue_share": RevenueSharePostHogScenario,
    "posthog_credits_token": CreditsTokenPostHogScenario,
    "posthog_hybrid_seat_usage": HybridSeatUsagePostHogScenario,
    "posthog_freemium_to_paid": FreemiumToPaidPostHogScenario,
    "posthog_event_volume": EventVolumePostHogScenario,
    "posthog_business_models_combined": BusinessModelsCombinedPostHogScenario,
}
