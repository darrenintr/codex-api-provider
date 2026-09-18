from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

import uvicorn

from .config import DEFAULT_CONFIG_PATH, load_config, write_default_config
from .providers import build_providers
from .state import StateStore


def _print_json(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codex-api-provider")
    parser.add_argument("--config", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    for name in ("providers", "models", "capacity", "doctor"):
        command = sub.add_parser(name)
        command.add_argument("--json", action="store_true")
    init = sub.add_parser("init")
    init.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "init":
        path = args.config or DEFAULT_CONFIG_PATH
        try:
            print(write_default_config(path, overwrite=args.force)); return 0
        except FileExistsError:
            print(f"config already exists: {path}", file=sys.stderr); return 2

    config = load_config(args.config)
    state = StateStore(config.state_path)
    providers = build_providers(config, state)

    if args.command == "serve":
        if args.config:
            os.environ["CODEX_API_PROVIDER_CONFIG"] = str(args.config.expanduser().resolve())
        uvicorn.run("codex_api_provider.server:app", host=args.host or config.server.host, port=args.port or config.server.port)
        return 0

    if args.command == "providers":
        values = [p.info().to_dict() for p in providers.values()]
        if args.json:
            _print_json({"schema_version": 1, "providers": values})
        else:
            print(f"{'PROVIDER':16} {'WIRE':10} {'CONFIGURED':10} BASE URL")
            for item in values:
                print(f"{item['name']:16} {item['wire_api']:10} {str(item['configured']):10} {item['base_url']}")
        return 0

    if args.command == "capacity":
        async def run_capacity():
            return await asyncio.gather(*(p.capacity() for p in providers.values()))
        values = asyncio.run(run_capacity())
        if args.json:
            _print_json({"schema_version": 1, "providers": [v.to_dict() for v in values]})
        else:
            print(f"{'PROVIDER':16} {'STATE':11} CAPACITY")
            for value in values:
                parts = []
                if value.token.remaining is not None:
                    parts.append(f"tokens={value.token.remaining} ({value.token.accuracy})")
                if value.requests.remaining is not None:
                    parts.append(f"requests={value.requests.remaining} ({value.requests.accuracy})")
                for credit in value.credits:
                    if credit.remaining is not None:
                        parts.append(f"{credit.currency}={credit.remaining:g} ({credit.accuracy})")
                print(f"{value.provider:16} {value.state:11} {'; '.join(parts) or value.note or value.error or 'unknown'}")
        return 0

    if args.command == "models":
        async def run_models():
            rows = []; errors = {}
            for p in providers.values():
                if not p.configured: continue
                try: rows.extend(await p.list_models())
                except Exception as exc: errors[p.name] = str(exc)
            return rows, errors
        rows, errors = asyncio.run(run_models())
        if args.json:
            _print_json({"schema_version": 1, "models": [m.to_dict() for m in rows], "errors": errors})
        else:
            for model in rows: print(model.id)
            for name, error in errors.items(): print(f"warning: {name}: {error}", file=sys.stderr)
        return 0

    if args.command == "doctor":
        result = {"config": str(args.config or os.environ.get("CODEX_API_PROVIDER_CONFIG") or DEFAULT_CONFIG_PATH), "state": str(config.state_path), "default_provider": config.default_provider, "providers": [{"provider": p.name, "configured": p.configured, "api_key_env": p.config.api_key_env, "wire_api": p.config.wire_api, "base_url": p.config.base_url} for p in providers.values()]}
        if args.json: _print_json(result)
        else:
            print(f"config: {result['config']}"); print(f"state: {result['state']}"); print(f"default provider: {config.default_provider}")
            for p in result["providers"]: print(f"- {p['provider']}: {'ready' if p['configured'] else 'missing ' + str(p['api_key_env'])} ({p['wire_api']})")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
