from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import AppConfig, load_config
from .gateway import Gateway, ModelReferenceError
from .providers import build_providers
from .providers.base import ProviderError
from .state import StateStore


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or load_config()
    state = StateStore(config.state_path)
    providers = build_providers(config, state)
    gateway = Gateway(config, providers, state)
    app = FastAPI(title="codex-api-provider", version="0.1.0")
    app.state.config = config
    app.state.providers = providers
    app.state.provider_state = state
    app.state.gateway = gateway

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "providers": list(providers)}

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        data: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        async def one(name: str):
            provider = providers[name]
            if not provider.configured:
                return name, [], None
            try:
                return name, await provider.list_models(), None
            except Exception as exc:
                return name, [], str(exc)
        for name, found, error in await asyncio.gather(*(one(n) for n in providers)):
            if error:
                errors[name] = error
            data.extend(model.to_dict() for model in found)
        return {"object": "list", "data": data, "errors": errors}

    @app.post("/v1/responses")
    async def responses(request: Request):
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="request body must be an object")
        try:
            if body.get("stream"):
                status, headers, iterator = await gateway.request_stream(body)
                media_type = headers.pop("content-type", "text/event-stream")
                return StreamingResponse(iterator, status_code=status, headers=headers, media_type=media_type)
            status, headers, payload = await gateway.request_nonstream(body)
            return JSONResponse(payload, status_code=status, headers=headers)
        except ModelReferenceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/router/providers")
    async def router_providers() -> dict[str, Any]:
        return {"schema_version": 1, "providers": [p.info().to_dict() for p in providers.values()]}

    @app.get("/router/capacity")
    async def router_capacity() -> dict[str, Any]:
        async def one(name: str):
            try:
                return await providers[name].capacity()
            except Exception as exc:
                from .models import ProviderCapacity
                return ProviderCapacity(provider=name, state="error", error=str(exc))
        values = await asyncio.gather(*(one(name) for name in providers))
        return {"schema_version": 1, "providers": [v.to_dict() for v in values], "local_usage": state.snapshot().get("providers", {})}

    @app.get("/router/models")
    async def router_models() -> dict[str, Any]:
        response = await models()
        return {"schema_version": 1, **response}

    return app


app = create_app()
