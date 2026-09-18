from __future__ import annotations

import json
import secrets
import time
from typing import Any


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content) if content is not None else ""
    out = []
    for part in content:
        if isinstance(part, str):
            out.append(part)
        elif isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"}:
            out.append(str(part.get("text", "")))
    return "\n".join(v for v in out if v)


def _chat_tool_choice(value: Any) -> Any:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None
    if value.get("type") == "function" and value.get("name"):
        return {"type": "function", "function": {"name": str(value["name"])}}
    return None


def responses_to_chat(payload: dict[str, Any], *, include_reasoning: bool = True) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    if isinstance(payload.get("instructions"), str) and payload["instructions"]:
        messages.append({"role": "system", "content": payload["instructions"]})
    raw = payload.get("input")
    if isinstance(raw, str):
        messages.append({"role": "user", "content": raw})
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            kind = item.get("type")
            if kind == "message" or (kind is None and item.get("role")):
                role = "system" if item.get("role") == "developer" else str(item.get("role", "user"))
                messages.append({"role": role, "content": _text(item.get("content"))})
            elif kind == "function_call_output":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(item.get("call_id") or item.get("id") or ""),
                        "content": _text(item.get("output")),
                    }
                )
            elif kind == "function_call":
                messages.append(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": str(item.get("call_id") or item.get("id") or "call_unknown"),
                                "type": "function",
                                "function": {
                                    "name": str(item.get("name", "")),
                                    "arguments": str(item.get("arguments", "{}")),
                                },
                            }
                        ],
                    }
                )
    result: dict[str, Any] = {
        "model": payload.get("model"),
        "messages": messages,
        "stream": bool(payload.get("stream", False)),
    }
    if result["stream"]:
        result["stream_options"] = {"include_usage": True}
    if payload.get("max_output_tokens") is not None:
        result["max_completion_tokens"] = payload["max_output_tokens"]
    for key in ("temperature", "top_p"):
        if payload.get(key) is not None:
            result[key] = payload[key]
    tools = []
    for tool in payload.get("tools") or []:
        if isinstance(tool, dict) and tool.get("type") == "function":
            fn = {"name": tool.get("name", ""), "parameters": tool.get("parameters") or {}}
            if tool.get("description") is not None:
                fn["description"] = tool["description"]
            if tool.get("strict") is not None:
                fn["strict"] = tool["strict"]
            tools.append({"type": "function", "function": fn})
    if tools:
        result["tools"] = tools
    tool_choice = _chat_tool_choice(payload.get("tool_choice"))
    if tool_choice is not None:
        result["tool_choice"] = tool_choice
    if payload.get("parallel_tool_calls") is not None:
        result["parallel_tool_calls"] = bool(payload["parallel_tool_calls"])
    reasoning = payload.get("reasoning")
    if include_reasoning and isinstance(reasoning, dict) and reasoning.get("effort"):
        result["reasoning_effort"] = reasoning["effort"]
    return result


def merge_chat_tool_call_deltas(
    state: dict[int, dict[str, str]],
    deltas: Any,
) -> None:
    """Accumulate OpenAI Chat Completions streaming tool-call deltas by index."""
    if not isinstance(deltas, list):
        return
    for position, call in enumerate(deltas):
        if not isinstance(call, dict):
            continue
        raw_index = call.get("index", position)
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = position
        current = state.setdefault(
            index,
            {
                "item_id": f"fc_{secrets.token_hex(10)}",
                "call_id": "",
                "name": "",
                "arguments": "",
            },
        )
        if call.get("id"):
            current["call_id"] = str(call["id"])
        function = call.get("function")
        if not isinstance(function, dict):
            continue
        if function.get("name"):
            current["name"] += str(function["name"])
        if function.get("arguments"):
            current["arguments"] += str(function["arguments"])


def chat_tool_call_items(state: dict[int, dict[str, str]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index in sorted(state):
        value = state[index]
        item_id = value.get("item_id") or f"fc_{secrets.token_hex(10)}"
        call_id = value.get("call_id") or f"call_{secrets.token_hex(8)}"
        items.append(
            {
                "id": item_id,
                "type": "function_call",
                "status": "completed",
                "call_id": call_id,
                "name": value.get("name", ""),
                "arguments": value.get("arguments", ""),
            }
        )
    return items


def chat_to_response(payload: dict[str, Any], *, requested_model: str | None = None) -> dict[str, Any]:
    output = []
    choices = payload.get("choices") or []
    message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
    if message.get("content"):
        output.append(
            {
                "id": f"msg_{secrets.token_hex(10)}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": str(message["content"]),
                        "annotations": [],
                    }
                ],
            }
        )
    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        output.append(
            {
                "id": f"fc_{secrets.token_hex(10)}",
                "type": "function_call",
                "status": "completed",
                "call_id": str(call.get("id") or f"call_{secrets.token_hex(8)}"),
                "name": str(fn.get("name", "")),
                "arguments": str(fn.get("arguments", "{}")),
            }
        )
    usage = payload.get("usage") or {}
    inp = int(usage.get("prompt_tokens") or 0)
    out = int(usage.get("completion_tokens") or 0)
    cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    return {
        "id": str(payload.get("id") or f"resp_{secrets.token_hex(12)}"),
        "object": "response",
        "created_at": int(payload.get("created") or time.time()),
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "model": payload.get("model") or requested_model,
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": inp,
            "input_tokens_details": {"cached_tokens": cached},
            "output_tokens": out,
            "output_tokens_details": {"reasoning_tokens": reasoning},
            "total_tokens": int(usage.get("total_tokens") or inp + out),
        },
    }


def sse_event(event_type: str, data: dict[str, Any]) -> bytes:
    payload = dict(data)
    payload.setdefault("type", event_type)
    return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
