from __future__ import annotations

from .base import BaseProvider, _int_or_none
from ..models import ProviderCapacity, RequestWindow, TokenWindow


class RateHeaderProvider(BaseProvider):
    async def capacity(self) -> ProviderCapacity:
        if not self.configured:
            return ProviderCapacity(provider=self.name, available=False, source="observed_response_headers", note=f"Set {self.config.api_key_env} to enable {self.name}.")
        entry = self.state.provider(self.name)
        headers = entry.get("rate_headers") if isinstance(entry.get("rate_headers"), dict) else {}
        if not headers:
            return ProviderCapacity(provider=self.name, available=True, source="observed_response_headers", note="No rate-limit response has been observed yet.")
        anthropic = any(k.startswith("anthropic-ratelimit-") for k in headers)
        if anthropic:
            tr = _int_or_none(headers.get("anthropic-ratelimit-tokens-remaining")); tl = _int_or_none(headers.get("anthropic-ratelimit-tokens-limit"))
            rr = _int_or_none(headers.get("anthropic-ratelimit-requests-remaining")); rl = _int_or_none(headers.get("anthropic-ratelimit-requests-limit"))
            t_reset = headers.get("anthropic-ratelimit-tokens-reset"); r_reset = headers.get("anthropic-ratelimit-requests-reset")
            t_window = r_window = "most_restrictive"
        else:
            tr = _int_or_none(headers.get("x-ratelimit-remaining-tokens")); tl = _int_or_none(headers.get("x-ratelimit-limit-tokens"))
            rr = _int_or_none(headers.get("x-ratelimit-remaining-requests")); rl = _int_or_none(headers.get("x-ratelimit-limit-requests"))
            t_reset = r_reset = None; t_window = "TPM"; r_window = "RPD"
        exhausted = tr == 0 or rr == 0
        return ProviderCapacity(provider=self.name, state="limited" if exhausted else "available", available=not exhausted, token=TokenWindow(tr, tl, t_window, t_reset, headers.get("x-ratelimit-reset-tokens"), "observed"), requests=RequestWindow(rr, rl, r_window, r_reset, headers.get("x-ratelimit-reset-requests"), "observed"), observed_at=entry.get("rate_observed_at"), source="observed_response_headers")
