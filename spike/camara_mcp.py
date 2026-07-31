# /// script
# requires-python = ">=3.12"
# dependencies = ["mcp>=2.0", "httpx>=0.28", "pydantic>=2"]
# ///
"""A real MCP server generated from the registry — what the MCP arm would install.

Spike, kept because it decided an architecture. See SPIKE.md.

The point is that `bench/spec.py` can emit a server a stock harness accepts, so the MCP arm becomes
"the user installed an extension" instead of a code path inside a loop we wrote. Signatures are
synthesised per operation so the SDK derives the JSON Schema itself: the schema the harness sees is
still generated from the registry, which is what keeps invariant 1 alive across the move.

    uv run --script spike/camara_mcp.py                 # every operation, over stdio
    N_OPERATIONS=5 uv run --script spike/camara_mcp.py  # a slice, for cheap tests
    SHOW_SCHEMAS=1 uv run --script spike/camara_mcp.py  # print what the harness would see
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import httpx
from mcp.server.mcpserver import MCPServer
from pydantic import Field

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bench import spec  # noqa: E402

PYTHON_TYPES: dict[str, Any] = {
    "integer": int,
    "number": float,
    "boolean": bool,
    "string": str,
    "array[string]": list[str],
    "array[integer]": list[int],
}

registry = spec.load(REPO / "data" / "specs" / "camara-dados-abertos-v2.json")
if limit := os.environ.get("N_OPERATIONS"):
    registry = registry.sample(int(limit), seed=0)

server = MCPServer("camara")
client = httpx.AsyncClient(
    timeout=60, headers={"Accept": "application/json"}, base_url=registry.base_url
)


def _annotation(param: spec.Param) -> Any:
    base = PYTHON_TYPES.get(param.type, str)
    if not param.required:
        base = base | None
    return Annotated[base, Field(description=param.description or param.name)]


def _register(operation: spec.Operation) -> None:
    """Give the SDK a function whose signature *is* the operation, so it derives the schema."""

    async def call(**arguments: Any) -> str:
        path_values = {
            p.name: arguments.pop(p.name) for p in operation.params if p.location == "path"
        }
        query = {k: v for k, v in arguments.items() if v is not None and v != ""}
        query = {
            k: ",".join(str(x) for x in v) if isinstance(v, list) else v for k, v in query.items()
        }
        response = await client.get(operation.render_path(path_values), params=query)
        return response.text

    parameters = [
        inspect.Parameter(
            p.name,
            inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if p.required else None,
            annotation=_annotation(p),
        )
        for p in operation.params
    ]
    call.__signature__ = inspect.Signature(parameters, return_annotation=str)  # type: ignore[attr-defined]
    call.__annotations__ = {p.name: _annotation(p) for p in operation.params} | {"return": str}
    call.__name__ = operation.name

    description = "\n\n".join(
        dict.fromkeys(t for t in (operation.summary, operation.description) if t)
    )
    server.add_tool(call, name=operation.name, description=description)


for op in registry:
    _register(op)


if __name__ == "__main__":
    if os.environ.get("SHOW_SCHEMAS"):
        tools = asyncio.run(server.list_tools())
        print(
            json.dumps([t.model_dump(exclude_none=True) for t in tools], ensure_ascii=False, indent=2)
        )
        sys.exit(0)
    print(f"camara: {len(registry)} operations", file=sys.stderr)
    server.run(transport="stdio")
