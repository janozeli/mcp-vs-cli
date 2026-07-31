"""The MCP format: every operation becomes a tool with a JSON Schema.

*When* those schemas enter the context is a separate question, and not one MCP settles. A client can
declare them all on connect, or list only the tool names and load a schema when the model asks for
it — which is what deferred tool loading does in current agents. Both are emitted here, so that
format and timing can be varied independently instead of being confounded in one "MCP" arm.
"""

from __future__ import annotations

from typing import Any

from bench.arms import Disclosure
from bench.spec import Operation, Param, Registry

_JSON_TYPES = {"integer": "integer", "number": "number", "boolean": "boolean", "string": "string"}


def _property_schema(param: Param) -> dict[str, Any]:
    schema: dict[str, Any] = {}
    if param.is_array:
        item = param.type[len("array[") : -1]
        schema["type"] = "array"
        schema["items"] = {"type": _JSON_TYPES.get(item, "string")}
        if param.enum:
            schema["items"]["enum"] = list(param.enum)
    else:
        schema["type"] = _JSON_TYPES.get(param.type, "string")
        if param.enum:
            schema["enum"] = list(param.enum)
    if param.description:
        schema["description"] = param.description
    if param.default is not None:
        schema["default"] = param.default
    return schema


def _description(op: Operation) -> str:
    parts = [p for p in (op.summary, op.description) if p]
    return "\n\n".join(dict.fromkeys(parts))


def tool_definition(op: Operation, *, prefix: str = "") -> dict[str, Any]:
    """One operation as an OpenAI-style function tool, the wire format OpenRouter expects."""
    properties = {p.name: _property_schema(p) for p in op.params}
    required = [p.name for p in op.params if p.required]
    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return {
        "type": "function",
        "function": {
            "name": f"{prefix}{op.name}",
            "description": _description(op),
            "parameters": parameters,
        },
    }


def tool_definitions(registry: Registry, *, prefix: str = "") -> list[dict[str, Any]]:
    """The full tools array for the MCP arm.

    `prefix` reproduces the namespacing MCP clients apply to avoid collisions between connected
    servers (`camara__list_deputados`). It is a real, and rarely counted, part of the bill.
    """
    return [tool_definition(op, prefix=prefix) for op in registry]


def search_tool_definition() -> dict[str, Any]:
    """The meta-tool a deferred client exposes so the model can pull schemas in when it needs them."""
    return {
        "type": "function",
        "function": {
            "name": "tool_search",
            "description": (
                "Load the full definitions of tools whose schemas are not yet available. "
                "Returns the schema of each matching tool, after which it can be called."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords, or a comma-separated list of exact tool names.",
                    }
                },
                "required": ["query"],
            },
        },
    }


def tool_index(registry: Registry, *, prefix: str = "") -> str:
    """The catalogue a deferred client shows: names and one line each, no schemas."""
    lines = []
    for group, ops in registry.groups().items():
        lines.append(f"{group}:")
        for op in ops:
            summary = _first_line(op.summary or op.description)
            lines.append(f"  {prefix}{op.name} — {summary}".rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def system_prompt(registry: Registry, *, disclosure: Disclosure = "eager", prefix: str = "") -> str:
    """Prose for the MCP format, at each level of disclosure.

    With every schema declared up front there is nothing to say — the schemas already said it. A
    deferred client has to explain that more tools exist than are loaded, and either lists their
    names or leaves the model to search blind.
    """
    base = (
        f"You have tools backed by the {registry.title} API. "
        "Use them to answer the user's question. Answer with the final value only."
    )
    if disclosure == "eager":
        return base
    if disclosure == "indexed":
        return (
            f"{base} The tools below are available but not loaded: calling one requires loading its"
            f" definition with `tool_search` first.\n\nAvailable tools:\n\n"
            f"{tool_index(registry, prefix=prefix)}"
        )
    return f"{base} No tools are loaded yet. Use `tool_search` to find and load the ones you need."


def tools_for(
    registry: Registry, *, disclosure: Disclosure = "eager", prefix: str = ""
) -> list[dict[str, Any]]:
    """The tools array actually sent, at each level of disclosure."""
    if disclosure == "eager":
        return tool_definitions(registry, prefix=prefix)
    return [search_tool_definition()]
