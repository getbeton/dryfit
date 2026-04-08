from beton_forge.scenarios.posthog_web import PostHogWebScenario
from beton_forge.scenarios.telegram_chat import TelegramChatScenario

SCENARIO_REGISTRY = {
    "posthog_web": PostHogWebScenario,
    "telegram_chat": TelegramChatScenario,
}
