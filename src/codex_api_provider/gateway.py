from __future__ import annotations

import json
import secrets
from typing import Any, AsyncIterator

import httpx

from .config import AppConfig
from .providers.base import BaseProvider, ProviderError
from .state import StateStore, UsageDelta
from .translation import (
    chat_to_response,
    chat_tool_call_items,
    merge_chat_tool_call_deltas,
    responses_to_chat,
    sse_event,
)


class ModelReferenceError(ValueError):
    pass


def split_model_reference(
    model: str,
    providers: dict[str, BaseProvider],
    default_provider: str,
) -> tuple[str, str]:
    if not model:
        raise ModelReferenceError("model must not be empty")
    head, sep, tail = model.partition("/")
    if sep and head in providers and tail:
        return head, tail
    if default_provider not in providers:
        raise ModelReferenceError(f"default provider is not enabled: {default_provider}")
    return default_provider, model


def usage_from_response(payload: Any) -> UsageDelta:
    if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
        return UsageDelta()
    usage = payload["usage"]
    if "input_tokens" in usage or "output_tokens" in usage:
        return UsageDelta(
            int(usage.get("input_tokens") or 0),
            int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0),
            int(usage.get("output_tokens") or 0),
            int((usage.get("output_tokens_details") or {}).get("reasoning_tokens") or 0),
        )
    return UsageDelta(
        int(usage.get("prompt_tokens") or 0),
        int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
    )


def _forward_headers(headers: httpx.Headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower().startswith("x-ratelimit-")
        or key.lower().startswith("anthropic-ratelimit-")
        or key.lower() == "retry-after"
    }


class Gateway:
    def __init__(
        self,
        config: AppConfig,
        providers: dict[str, BaseProvider],
        state: StateStore,
    ):
        self.config = config
        self.providers = providers
        self.state = state

    def resolve(self, model: str) -> tuple[BaseProvider, str]:
        provider_name, upstream = split_model_reference(
            model,
            self.providers,
            self.config.default_provider,
        )
        return self.providers[provider_name], upstream

    async def request_nonstream(
        self,
        body: dict[str, Any],
    ) -> tuple[int, dict[str, str], Any]:
        provider, model = self.resolve(str(body.get("model", "")))
        upstream_body = dict(body)
        upstream_body["model"] = model
        upstream_body["stream"] = False
        if provider.config.wire_api == "responses":
            path = "/responses"
            wire_body = upstream_body
        elif provider.config.wire_api == "chat":
            path = "/chat/completions"
            wire_body = responses_to_chat(
                upstream_body,
                include_reasoning=provider.config.supports_reasoning,
            )
        else:
            raise ProviderError(f"unsupported wire_api: {provider.config.wire_api}")
        headers = provider.auth_headers()
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(
            timeout=self.config.server.request_timeout_seconds
        ) as client:
            response = await client.post(
                f"{provider.config.base_url}{path}",
                headers=headers,
                json=wire_body,
            )
        provider.state.observe_headers(provider.name, dict(response.headers))
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {
                "error": {
                    "message": response.text or f"upstream HTTP {response.status_code}"
                }
            }
        if response.status_code < 400 and provider.config.wire_api == "chat":
            payload = chat_to_response(payload, requested_model=model)
        if response.status_code < 400:
            provider.state.add_usage(
                provider.name,
                model,
                usage_from_response(payload),
            )
            if isinstance(payload, dict):
                payload["model"] = f"{provider.name}/{model}"
        return response.status_code, _forward_headers(response.headers), payload

    async def request_stream(
        self,
        body: dict[str, Any],
    ) -> tuple[int, dict[str, str], AsyncIterator[bytes]]:
        provider, model = self.resolve(str(body.get("model", "")))
        upstream_body = dict(body)
        upstream_body["model"] = model
        upstream_body["stream"] = True
        headers = provider.auth_headers()
        headers["Content-Type"] = "application/json"
        client = httpx.AsyncClient(timeout=self.config.server.request_timeout_seconds)

        if provider.config.wire_api == "responses":
            request = client.build_request(
                "POST",
                f"{provider.config.base_url}/responses",
                headers=headers,
                json=upstream_body,
            )
            upstream = await client.send(request, stream=True)
            provider.state.observe_headers(provider.name, dict(upstream.headers))

            async def direct() -> AsyncIterator[bytes]:
                usage = UsageDelta()
                try:
                    async for line in upstream.aiter_lines():
                        if line.startswith("data:"):
                            raw = line[5:].strip()
                            if raw and raw != "[DONE]":
                                try:
                                    event = json.loads(raw)
                                except json.JSONDecodeError:
                                    event = None
                                if (
                                    isinstance(event, dict)
                                    and event.get("type") == "response.completed"
                                    and isinstance(event.get("response"), dict)
                                ):
                                    usage = usage_from_response(event["response"])
                        yield f"{line}\n".encode()
                finally:
                    provider.state.add_usage(provider.name, model, usage)
                    await upstream.aclose()
                    await client.aclose()

            forwarded = _forward_headers(upstream.headers)
            forwarded["content-type"] = upstream.headers.get(
                "content-type",
                "text/event-stream",
            )
            return upstream.status_code, forwarded, direct()

        if provider.config.wire_api != "chat":
            await client.aclose()
            raise ProviderError(f"unsupported wire_api: {provider.config.wire_api}")

        wire_body = responses_to_chat(
            upstream_body,
            include_reasoning=provider.config.supports_reasoning,
        )
        request = client.build_request(
            "POST",
            f"{provider.config.base_url}/chat/completions",
            headers=headers,
            json=wire_body,
        )
        upstream = await client.send(request, stream=True)
        provider.state.observe_headers(provider.name, dict(upstream.headers))

        if upstream.status_code >= 400:
            async def raw_error() -> AsyncIterator[bytes]:
                try:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            forwarded = _forward_headers(upstream.headers)
            forwarded["content-type"] = upstream.headers.get(
                "content-type",
                "application/json",
            )
            return upstream.status_code, forwarded, raw_error()

        response_id = f"resp_{secrets.token_hex(12)}"

        async def translated() -> AsyncIterator[bytes]:
            seq = 0
            message_id = f"msg_{secrets.token_hex(10)}"
            started = False
            full = ""
            usage = UsageDelta()
            tool_state: dict[int, dict[str, str]] = {}

            yield sse_event(
                "response.created",
                {
                    "sequence_number": seq,
                    "response": {
                        "id": response_id,
                        "object": "response",
                        "status": "in_progress",
                        "model": f"{provider.name}/{model}",
                        "output": [],
                    },
                },
            )
            seq += 1

            try:
                async for line in upstream.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if isinstance(event.get("usage"), dict):
                        usage = usage_from_response({"usage": event["usage"]})
                    choices = event.get("choices") or []
                    if not choices or not isinstance(choices[0], dict):
                        continue
                    delta = choices[0].get("delta") or {}
                    if not isinstance(delta, dict):
                        continue

                    merge_chat_tool_call_deltas(
                        tool_state,
                        delta.get("tool_calls"),
                    )

                    content = delta.get("content")
                    if content:
                        if not started:
                            started = True
                            yield sse_event(
                                "response.output_item.added",
                                {
                                    "sequence_number": seq,
                                    "output_index": 0,
                                    "item": {
                                        "id": message_id,
                                        "type": "message",
                                        "status": "in_progress",
                                        "role": "assistant",
                                        "content": [],
                                    },
                                },
                            )
                            seq += 1
                            yield sse_event(
                                "response.content_part.added",
                                {
                                    "sequence_number": seq,
                                    "item_id": message_id,
                                    "output_index": 0,
                                    "content_index": 0,
                                    "part": {
                                        "type": "output_text",
                                        "text": "",
                                        "annotations": [],
                                    },
                                },
                            )
                            seq += 1
                        full += str(content)
                        yield sse_event(
                            "response.output_text.delta",
                            {
                                "sequence_number": seq,
                                "item_id": message_id,
                                "output_index": 0,
                                "content_index": 0,
                                "delta": str(content),
                            },
                        )
                        seq += 1
            except Exception as exc:
                yield sse_event(
                    "response.failed",
                    {
                        "sequence_number": seq,
                        "response": {
                            "id": response_id,
                            "object": "response",
                            "status": "failed",
                            "error": {
                                "type": "server_error",
                                "code": "upstream_stream_error",
                                "message": str(exc),
                            },
                        },
                    },
                )
                return
            finally:
                await upstream.aclose()
                await client.aclose()

            output: list[dict[str, Any]] = []
            if started:
                message_item = {
                    "id": message_id,
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": full,
                            "annotations": [],
                        }
                    ],
                }
                output.append(message_item)
                yield sse_event(
                    "response.output_text.done",
                    {
                        "sequence_number": seq,
                        "item_id": message_id,
                        "output_index": 0,
                        "content_index": 0,
                        "text": full,
                    },
                )
                seq += 1
                yield sse_event(
                    "response.output_item.done",
                    {
                        "sequence_number": seq,
                        "output_index": 0,
                        "item": message_item,
                    },
                )
                seq += 1

            for item in chat_tool_call_items(tool_state):
                output_index = len(output)
                output.append(item)
                yield sse_event(
                    "response.output_item.done",
                    {
                        "sequence_number": seq,
                        "output_index": output_index,
                        "item": item,
                    },
                )
                seq += 1

            provider.state.add_usage(provider.name, model, usage)
            yield sse_event(
                "response.completed",
                {
                    "sequence_number": seq,
                    "response": {
                        "id": response_id,
                        "object": "response",
                        "status": "completed",
                        "model": f"{provider.name}/{model}",
                        "output": output,
                        "usage": {
                            "input_tokens": usage.input_tokens,
                            "input_tokens_details": {
                                "cached_tokens": usage.cached_input_tokens
                            },
                            "output_tokens": usage.output_tokens,
                            "output_tokens_details": {
                                "reasoning_tokens": usage.reasoning_tokens
                            },
                            "total_tokens": usage.input_tokens + usage.output_tokens,
                        },
                    },
                },
            )

        forwarded = _forward_headers(upstream.headers)
        forwarded["content-type"] = "text/event-stream"
        return upstream.status_code, forwarded, translated()
