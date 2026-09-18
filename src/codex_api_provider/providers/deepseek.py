from __future__ import annotations

import httpx

from .base import BaseProvider, _float_or_none
from ..models import CreditBalance, ProviderCapacity


class DeepSeekProvider(BaseProvider):
    async def capacity(self) -> ProviderCapacity:
        if not self.config.api_key:
            return ProviderCapacity(provider=self.name, available=False, source="deepseek:/user/balance", note=f"Set {self.config.api_key_env} to enable DeepSeek.")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.config.base_url}/user/balance", headers=self.auth_headers())
            response.raise_for_status(); data = response.json()
        except Exception as exc:
            return ProviderCapacity(provider=self.name, state="error", source="deepseek:/user/balance", error=str(exc))
        balances = tuple(CreditBalance(str(x.get("currency", "UNKNOWN")), _float_or_none(x.get("total_balance")), accuracy="exact") for x in data.get("balance_infos", []) if isinstance(x, dict))
        available = bool(data.get("is_available"))
        return ProviderCapacity(provider=self.name, state="available" if available else "exhausted", available=available, credits=balances, source="deepseek:/user/balance")
