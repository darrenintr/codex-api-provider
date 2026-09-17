from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

CapacityAccuracy = Literal["exact", "observed", "estimated", "unknown"]
CapacityState = Literal["available", "limited", "exhausted", "unknown", "error"]


@dataclass(frozen=True)
class TokenWindow:
    remaining: int | None = None
    limit: int | None = None
    window: str | None = None
    reset_at: str | None = None
    reset_after: str | None = None
    accuracy: CapacityAccuracy = "unknown"


@dataclass(frozen=True)
class RequestWindow:
    remaining: int | None = None
    limit: int | None = None
    window: str | None = None
    reset_at: str | None = None
    reset_after: str | None = None
    accuracy: CapacityAccuracy = "unknown"


@dataclass(frozen=True)
class CreditBalance:
    currency: str
    remaining: float | None = None
    limit: float | None = None
    used: float | None = None
    reset: str | None = None
    accuracy: CapacityAccuracy = "unknown"


@dataclass(frozen=True)
class EstimatedTokens:
    value: int | None = None
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"
    basis: str | None = None


@dataclass(frozen=True)
class ProviderCapacity:
    provider: str
    state: CapacityState = "unknown"
    available: bool | None = None
    token: TokenWindow = field(default_factory=TokenWindow)
    requests: RequestWindow = field(default_factory=RequestWindow)
    credits: tuple[CreditBalance, ...] = ()
    estimated_tokens: EstimatedTokens = field(default_factory=EstimatedTokens)
    observed_at: str | None = None
    source: str | None = None
    note: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelInfo:
    id: str
    upstream_id: str
    provider: str
    name: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    supports_tools: bool | None = None
    supports_reasoning: bool | None = None
    supports_responses: bool = True
    free: bool | None = None
    input_cost_per_token: float | None = None
    output_cost_per_token: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("raw", None)
        return value


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    type: str
    enabled: bool
    configured: bool
    base_url: str
    wire_api: str
    supports_responses: bool
    quota_kind: str
    api_key_env: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
