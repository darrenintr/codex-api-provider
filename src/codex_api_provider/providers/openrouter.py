from __future__ import annotations

import httpx

from .base import BaseProvider, ProviderError, _float_or_none, _int_or_none
from ..models import CreditBalance, ModelInfo, ProviderCapacity


class OpenRouterProvider(BaseProvider):
    async def list_models(self) -> list[ModelInfo]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.config.base_url}/models", headers=self.auth_headers())
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise ProviderError(f"openrouter model discovery failed: {exc}") from exc
        result = []
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model_id = str(item["id"])
            pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
            inp = _float_or_none(pricing.get("prompt")); out = _float_or_none(pricing.get("completion"))
            supported = set(str(v) for v in item.get("supported_parameters", []))
            result.append(ModelInfo(f"openrouter/{model_id}", model_id, self.name, name=str(item.get("name") or model_id), context_window=_int_or_none(item.get("context_length")), max_output_tokens=_int_or_none((item.get("top_provider") or {}).get("max_completion_tokens")), supports_tools="tools" in supported or "tool_choice" in supported, supports_reasoning="reasoning" in supported, free=(inp == 0.0 and out == 0.0) if inp is not None and out is not None else None, input_cost_per_token=inp, output_cost_per_token=out, raw=item))
        return result

    async def capacity(self) -> ProviderCapacity:
        if not self.config.api_key:
            return ProviderCapacity(provider=self.name, available=False, source="openrouter:/key", note=f"Set {self.config.api_key_env} to enable OpenRouter.")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.config.base_url}/key", headers=self.auth_headers())
            response.raise_for_status(); data = response.json().get("data", {})
        except Exception as exc:
            return ProviderCapacity(provider=self.name, state="error", source="openrouter:/key", error=str(exc))
        credits = []
        remaining = _float_or_none(data.get("limit_remaining")); limit = _float_or_none(data.get("limit")); used = _float_or_none(data.get("usage"))
        if remaining is not None or limit is not None:
            credits.append(CreditBalance("USD", remaining, limit, used, str(data.get("limit_reset")) if data.get("limit_reset") else None, "exact"))
        exhausted = bool(credits and credits[0].limit is not None and credits[0].remaining is not None and credits[0].remaining <= 0)
        return ProviderCapacity(provider=self.name, state="exhausted" if exhausted else "available", available=not exhausted, credits=tuple(credits), source="openrouter:/key", note="OpenRouter free tier." if data.get("is_free_tier") else None)
