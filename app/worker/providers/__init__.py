from __future__ import annotations

from app.worker.providers.base import ProviderAutomation, ProviderExecutionContext
from app.worker.providers.dreamina import DreaminaAutomationProvider
from app.worker.providers.flow import FlowAutomationProvider
from app.worker.providers.grok_gateway import GrokGatewayProvider
from app.worker.providers.grok import GrokAutomationProvider


def get_provider_automation(context: ProviderExecutionContext) -> ProviderAutomation:
    request_payload = context.request_payload or {}
    provider_mode = str(request_payload.get("provider_mode") or "").strip().lower()
    if provider_mode == "gateway":
        return GrokGatewayProvider(context)

    provider_map: dict[str, type[ProviderAutomation]] = {
        "grok": GrokAutomationProvider,
        "flow": FlowAutomationProvider,
        "dreamina": DreaminaAutomationProvider,
    }
    provider_key = str(context.provider or "").strip().lower()
    provider_class = provider_map.get(provider_key, GrokAutomationProvider)
    return provider_class(context)
