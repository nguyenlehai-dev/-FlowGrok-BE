from __future__ import annotations

from app.worker.providers.base import ProviderAutomation, ProviderExecutionContext
from app.worker.providers.dreamina import DreaminaAutomationProvider
from app.worker.providers.flow import FlowAutomationProvider
from app.worker.providers.grok import GrokAutomationProvider


def get_provider_automation(context: ProviderExecutionContext) -> ProviderAutomation:
    provider_map: dict[str, type[ProviderAutomation]] = {
        "grok": GrokAutomationProvider,
        "flow": FlowAutomationProvider,
        "dreamina": DreaminaAutomationProvider,
    }
    provider_class = provider_map.get(context.provider, GrokAutomationProvider)
    return provider_class(context)
