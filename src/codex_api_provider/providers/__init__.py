from __future__ import annotations

from ..config import AppConfig, ProviderConfig
from ..state import StateStore
from .base import BaseProvider
from .deepseek import DeepSeekProvider
from .openrouter import OpenRouterProvider
from .rate_headers import RateHeaderProvider


def build_provider(config: ProviderConfig, state: StateStore, timeout: float) -> BaseProvider:
    if config.type == "openrouter":
        return OpenRouterProvider(config, state, timeout)
    if config.type == "deepseek":
        return DeepSeekProvider(config, state, timeout)
    if config.quota_kind == "rate_headers" or config.type == "groq":
        return RateHeaderProvider(config, state, timeout)
    return BaseProvider(config, state, timeout)


def build_providers(config: AppConfig, state: StateStore) -> dict[str, BaseProvider]:
    return {name: build_provider(provider_config, state, config.server.request_timeout_seconds) for name, provider_config in config.providers.items() if provider_config.enabled}
