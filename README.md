# codex-api-provider

A quota-aware multi-provider gateway for Codex. It exposes a local OpenAI Responses-compatible endpoint for external model providers and a machine-readable capacity contract for `codex-auto-router`.

Official GPT/Codex entitlement routing can stay on the normal Codex path. External providers use this gateway.

## v0.1

- `POST /v1/responses`
- Native Responses passthrough for Responses-compatible providers such as OpenRouter/xAI
- Responses ↔ Chat Completions translation for OpenAI-compatible providers
- Streaming text bridge for Chat Completions backends
- `GET /v1/models`
- `GET /router/providers`
- `GET /router/models`
- `GET /router/capacity`
- Exact OpenRouter key-limit reporting
- Exact DeepSeek account balance reporting
- Observed rate-limit token/request reporting for Groq/Anthropic-compatible headers
- Persistent local input/cached/output/reasoning token accounting
- Built-in presets for OpenRouter, DeepSeek, Groq, Anthropic, Gemini, xAI, Mistral, Cerebras, Together, Fireworks, NVIDIA NIM, SiliconFlow, DashScope and Ollama

The gateway never fabricates a single `remaining_tokens` value when a provider does not expose one. Capacity records label data as `exact`, `observed`, `estimated`, or `unknown`.

## Install

```bash
pipx install git+https://github.com/darrenintr/codex-api-provider.git@feat/v0.1-provider-gateway
codex-api-provider init
```

Set the keys you actually use:

```bash
export OPENROUTER_API_KEY='...'
export DEEPSEEK_API_KEY='...'
export GROQ_API_KEY='...'
export GEMINI_API_KEY='...'
export ANTHROPIC_API_KEY='...'
```

Run:

```bash
codex-api-provider serve
```

Default base URL:

```text
http://127.0.0.1:8765/v1
```

## Codex

Add to `~/.codex/config.toml`:

```toml
[model_providers.external]
name = "codex-api-provider"
base_url = "http://127.0.0.1:8765/v1"
wire_api = "responses"
```

Then select provider-prefixed model IDs:

```bash
codex -c 'model_provider="external"' -c 'model="openrouter/qwen/qwen3-coder:free"'
codex -c 'model_provider="external"' -c 'model="groq/openai/gpt-oss-120b"'
```

If the prefix is omitted, `[gateway].default_provider` is used.

## Capacity API

```bash
codex-api-provider capacity --json
```

or:

```bash
curl http://127.0.0.1:8765/router/capacity
```

Example shape:

```json
{
  "schema_version": 1,
  "providers": [
    {
      "provider": "groq",
      "state": "available",
      "token": {
        "remaining": 17997,
        "limit": 18000,
        "window": "TPM",
        "accuracy": "observed"
      },
      "requests": {
        "remaining": 14370,
        "limit": 14400,
        "window": "RPD",
        "accuracy": "observed"
      },
      "credits": []
    }
  ]
}
```

This is the contract intended for `codex-auto-router`: Auto Router decides **required capability**, while this project reports **available models/providers/capacity**.

## Generic provider

Any OpenAI-compatible service can be added without changing Python code:

```toml
[providers.example]
type = "generic"
base_url = "https://example.com/v1"
api_key_env = "EXAMPLE_API_KEY"
wire_api = "chat" # or "responses"
quota_kind = "rate_headers"
```

Use it as `example/<model-id>`.

## Security

- Secrets are environment variables, not config values.
- The server binds to `127.0.0.1` by default.
- Do not expose it publicly without authentication/TLS in front of it.

## Development

```bash
pip install -e '.[dev]'
python -m compileall -q src tests
pytest
```

## License

MIT
