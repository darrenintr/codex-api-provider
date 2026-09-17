from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import tomllib
from typing import Any

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "codex-api-provider" / "config.toml"
DEFAULT_STATE_PATH = Path.home() / ".local" / "state" / "codex-api-provider" / "state.json"


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    request_timeout_seconds: float = 180.0


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    type: str = "generic"
    enabled: bool = True
    base_url: str = ""
    api_key_env: str | None = None
    management_key_env: str | None = None
    wire_api: str = "responses"
    quota_kind: str = "auto"
    supports_reasoning: bool = True
    models: tuple[str, ...] = ()
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) if self.api_key_env else None

    @property
    def management_key(self) -> str | None:
        return os.environ.get(self.management_key_env) if self.management_key_env else None


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    state_path: Path = DEFAULT_STATE_PATH
    default_provider: str = "openrouter"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)


BUILTIN_PROVIDERS: dict[str, ProviderConfig] = {
    "openrouter": ProviderConfig("openrouter", "openrouter", True, "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "OPENROUTER_MANAGEMENT_API_KEY", "responses", "openrouter", True, (), {"HTTP-Referer": "https://github.com/darrenintr/codex-api-provider", "X-Title": "codex-api-provider"}),
    "deepseek": ProviderConfig("deepseek", "deepseek", True, "https://api.deepseek.com", "DEEPSEEK_API_KEY", None, "responses", "deepseek"),
    "groq": ProviderConfig("groq", "groq", True, "https://api.groq.com/openai/v1", "GROQ_API_KEY", None, "chat", "rate_headers"),
    "anthropic": ProviderConfig("anthropic", "generic", True, "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", None, "chat", "rate_headers"),
    "gemini": ProviderConfig("gemini", "generic", True, "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", None, "chat", "unknown"),
    "xai": ProviderConfig("xai", "generic", True, "https://api.x.ai/v1", "XAI_API_KEY", "XAI_MANAGEMENT_API_KEY", "responses", "unknown"),
    "mistral": ProviderConfig("mistral", "generic", True, "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "MISTRAL_ADMIN_API_KEY", "chat", "unknown"),
    "cerebras": ProviderConfig("cerebras", "generic", True, "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", None, "chat", "rate_headers"),
    "together": ProviderConfig("together", "generic", True, "https://api.together.xyz/v1", "TOGETHER_API_KEY", None, "chat", "unknown"),
    "fireworks": ProviderConfig("fireworks", "generic", True, "https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY", None, "chat", "unknown"),
    "nvidia": ProviderConfig("nvidia", "generic", True, "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", None, "chat", "unknown"),
    "siliconflow": ProviderConfig("siliconflow", "generic", True, "https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY", None, "chat", "unknown"),
    "dashscope": ProviderConfig("dashscope", "generic", True, "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY", None, "chat", "unknown"),
    "ollama": ProviderConfig("ollama", "generic", True, "http://127.0.0.1:11434/v1", None, None, "chat", "unlimited_local", False),
}

DEFAULT_CONFIG_TEXT = '''[server]
host = "127.0.0.1"
port = 8765
request_timeout_seconds = 180

[gateway]
default_provider = "openrouter"

[providers.openrouter]
type = "openrouter"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
management_key_env = "OPENROUTER_MANAGEMENT_API_KEY"
wire_api = "responses"
quota_kind = "openrouter"

[providers.deepseek]
type = "deepseek"
base_url = "https://api.deepseek.com"
api_key_env = "DEEPSEEK_API_KEY"
wire_api = "responses"
quota_kind = "deepseek"

[providers.groq]
type = "groq"
base_url = "https://api.groq.com/openai/v1"
api_key_env = "GROQ_API_KEY"
wire_api = "chat"
quota_kind = "rate_headers"

[providers.ollama]
type = "generic"
base_url = "http://127.0.0.1:11434/v1"
wire_api = "chat"
quota_kind = "unlimited_local"
supports_reasoning = false
'''


def _provider(name: str, raw: dict[str, Any]) -> ProviderConfig:
    base = BUILTIN_PROVIDERS.get(name, ProviderConfig(name=name))
    models = raw.get("models", base.models)
    if isinstance(models, str):
        models = [models]
    headers = raw.get("headers", base.headers)
    if not isinstance(headers, dict):
        headers = {}
    return ProviderConfig(
        name=name,
        type=str(raw.get("type", base.type)),
        enabled=bool(raw.get("enabled", base.enabled)),
        base_url=str(raw.get("base_url", base.base_url)).rstrip("/"),
        api_key_env=str(raw["api_key_env"]) if raw.get("api_key_env") else base.api_key_env,
        management_key_env=str(raw["management_key_env"]) if raw.get("management_key_env") else base.management_key_env,
        wire_api=str(raw.get("wire_api", base.wire_api)),
        quota_kind=str(raw.get("quota_kind", base.quota_kind)),
        supports_reasoning=bool(raw.get("supports_reasoning", base.supports_reasoning)),
        models=tuple(str(v) for v in models),
        headers={str(k): str(v) for k, v in headers.items()},
    )


def load_config(path: Path | None = None) -> AppConfig:
    path = path or Path(os.environ.get("CODEX_API_PROVIDER_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    server_raw = raw.get("server", {})
    server = ServerConfig(str(server_raw.get("host", "127.0.0.1")), int(server_raw.get("port", 8765)), float(server_raw.get("request_timeout_seconds", 180.0)))
    gateway = raw.get("gateway", {})
    state_raw = gateway.get("state_path") or os.environ.get("CODEX_API_PROVIDER_STATE")
    providers_raw = raw.get("providers")
    if isinstance(providers_raw, dict):
        providers = {str(name): _provider(str(name), value) for name, value in providers_raw.items() if isinstance(value, dict)}
    else:
        providers = dict(BUILTIN_PROVIDERS)
    return AppConfig(server, Path(state_raw).expanduser() if state_raw else DEFAULT_STATE_PATH, str(gateway.get("default_provider", "openrouter")), providers)


def write_default_config(path: Path | None = None, *, overwrite: bool = False) -> Path:
    path = (path or DEFAULT_CONFIG_PATH).expanduser()
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return path
