from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
import json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class UsageDelta:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = RLock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "providers": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "providers": {}}
        if not isinstance(value, dict):
            return {"schema_version": 1, "providers": {}}
        value.setdefault("schema_version", 1)
        value.setdefault("providers", {})
        return value

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._load()

    def provider(self, name: str) -> dict[str, Any]:
        with self._lock:
            value = self._load().get("providers", {}).get(name, {})
            return dict(value) if isinstance(value, dict) else {}

    def observe_headers(self, provider: str, headers: dict[str, str]) -> None:
        interesting = {
            k.lower(): v for k, v in headers.items()
            if k.lower().startswith("x-ratelimit-") or k.lower().startswith("anthropic-ratelimit-") or k.lower() == "retry-after"
        }
        if not interesting:
            return
        with self._lock:
            state = self._load()
            entry = state.setdefault("providers", {}).setdefault(provider, {})
            entry["rate_headers"] = interesting
            entry["rate_observed_at"] = _now()
            self._save(state)

    def add_usage(self, provider: str, model: str, delta: UsageDelta) -> None:
        if not any((delta.input_tokens, delta.cached_input_tokens, delta.output_tokens, delta.reasoning_tokens)):
            return
        with self._lock:
            state = self._load()
            entry = state.setdefault("providers", {}).setdefault(provider, {})
            usage = entry.setdefault("usage", {})
            model_usage = usage.setdefault("models", {}).setdefault(model, {})
            totals = usage.setdefault("total", {})
            values = {
                "input_tokens": delta.input_tokens,
                "cached_input_tokens": delta.cached_input_tokens,
                "output_tokens": delta.output_tokens,
                "reasoning_tokens": delta.reasoning_tokens,
            }
            for key, value in values.items():
                model_usage[key] = int(model_usage.get(key, 0)) + int(value)
                totals[key] = int(totals.get(key, 0)) + int(value)
            usage["updated_at"] = _now()
            self._save(state)
