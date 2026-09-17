from pathlib import Path

from codex_api_provider.config import AppConfig, ProviderConfig, ServerConfig, load_config
from codex_api_provider.gateway import ModelReferenceError, split_model_reference
from codex_api_provider.providers import build_providers
from codex_api_provider.providers.rate_headers import RateHeaderProvider
from codex_api_provider.state import StateStore, UsageDelta
from codex_api_provider.translation import chat_to_response, responses_to_chat


def _providers(tmp_path: Path):
    config = AppConfig(
        server=ServerConfig(),
        state_path=tmp_path / "state.json",
        default_provider="openrouter",
        providers={
            "openrouter": ProviderConfig(name="openrouter", base_url="https://example.test", api_key_env=None),
            "groq": ProviderConfig(name="groq", base_url="https://example.test", api_key_env=None, wire_api="chat"),
        },
    )
    return config, build_providers(config, StateStore(config.state_path))


def test_defaults_include_mainstream_providers(tmp_path: Path):
    config = load_config(tmp_path / "missing.toml")
    assert {"openrouter", "deepseek", "groq", "anthropic", "gemini", "xai", "mistral", "ollama"} <= set(config.providers)


def test_model_prefix_and_default(tmp_path: Path):
    config, providers = _providers(tmp_path)
    assert split_model_reference("openrouter/qwen/qwen3", providers, config.default_provider) == ("openrouter", "qwen/qwen3")
    assert split_model_reference("qwen/qwen3", providers, config.default_provider) == ("openrouter", "qwen/qwen3")
    try:
        split_model_reference("model", providers, "missing")
    except ModelReferenceError:
        pass
    else:
        raise AssertionError("missing default provider must fail")


def test_translation_maps_text_tools_and_usage():
    request = {
        "model": "demo",
        "instructions": "You are coding.",
        "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "fix it"}]}],
        "tools": [{"type": "function", "name": "shell", "description": "run shell", "parameters": {"type": "object", "properties": {}}}],
        "reasoning": {"effort": "low"},
    }
    chat = responses_to_chat(request)
    assert chat["messages"][0]["role"] == "system"
    assert chat["messages"][1]["content"] == "fix it"
    assert chat["tools"][0]["function"]["name"] == "shell"
    assert chat["reasoning_effort"] == "low"

    response = chat_to_response({
        "id": "chat_1",
        "model": "demo",
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "prompt_tokens_details": {"cached_tokens": 3}, "completion_tokens_details": {"reasoning_tokens": 2}},
    })
    assert response["output"][0]["content"][0]["text"] == "hello"
    assert response["usage"]["input_tokens_details"]["cached_tokens"] == 3


def test_state_tracks_usage_and_rate_headers(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.add_usage("groq", "model", UsageDelta(input_tokens=10, output_tokens=4))
    store.observe_headers("groq", {"X-RateLimit-Limit-Tokens": "18000", "X-RateLimit-Remaining-Tokens": "17997", "X-RateLimit-Limit-Requests": "14400", "X-RateLimit-Remaining-Requests": "14370"})
    state = store.provider("groq")
    assert state["usage"]["total"]["input_tokens"] == 10
    assert state["rate_headers"]["x-ratelimit-remaining-tokens"] == "17997"


async def test_observed_capacity(tmp_path: Path):
    store = StateStore(tmp_path / "state.json")
    store.observe_headers("groq", {"X-RateLimit-Limit-Tokens": "18000", "X-RateLimit-Remaining-Tokens": "17997", "X-RateLimit-Limit-Requests": "14400", "X-RateLimit-Remaining-Requests": "14370"})
    provider = RateHeaderProvider(ProviderConfig(name="groq", type="groq", base_url="https://example.test", api_key_env=None), store)
    capacity = await provider.capacity()
    assert capacity.token.remaining == 17997
    assert capacity.token.accuracy == "observed"
    assert capacity.requests.remaining == 14370
