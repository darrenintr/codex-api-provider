from __future__ import annotations

from typing import Any
import httpx

from ..config import ProviderConfig
from ..models import ModelInfo, ProviderCapacity, ProviderInfo
from ..state import StateStore


class ProviderError(RuntimeError):
    pass


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class BaseProvider:
    def __init__(self, config: ProviderConfig, state: StateStore, timeout: float = 180.0):
        self.config = config
        self.state = state
        self.timeout = timeout

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def configured(self) -> bool:
        return self.config.api_key is not None or self.config.api_key_env is None

    def auth_headers(self, *, management: bool = False) -> dict[str, str]:
        headers = dict(self.config.headers)
        key = self.config.management_key if management else self.config.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def info(self) -> ProviderInfo:
        return ProviderInfo(self.name, self.config.type, self.config.enabled, self.configured, self.config.base_url, self.config.wire_api, self.config.wire_api == "responses", self.config.quota_kind, self.config.api_key_env)

    async def list_models(self) -> list[ModelInfo]:
        if self.config.models:
            return [ModelInfo(f"{self.name}/{m}", m, self.name, name=m, supports_responses=self.config.wire_api == "responses") for m in self.config.models]
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.config.base_url}/models", headers=self.auth_headers())
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            raise ProviderError(f"{self.name} model discovery failed: {exc}") from exc
        result: list[ModelInfo] = []
        for item in payload.get("data", []) if isinstance(payload, dict) else []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model_id = str(item["id"])
            result.append(ModelInfo(f"{self.name}/{model_id}", model_id, self.name, name=str(item.get("name") or model_id), context_window=_int_or_none(item.get("context_length") or item.get("context_window")), supports_responses=self.config.wire_api == "responses", raw=item))
        return result

    async def capacity(self) -> ProviderCapacity:
        local = self.config.quota_kind == "unlimited_local"
        return ProviderCapacity(provider=self.name, state="available" if local else "unknown", available=True if local else self.configured, source="local" if local else None, note="Local provider; no remote token quota." if local else None)
