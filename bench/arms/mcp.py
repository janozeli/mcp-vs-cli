"""The MCP format: every operation becomes a tool with a JSON Schema.

*When* those schemas enter the context is a separate question, and not one MCP settles. A client can
declare them all on connect, or list only the tool names and load a schema when the model asks for
it — which is what deferred tool loading does in current agents. Both are emitted here, so that
format and timing can be varied independently instead of being confounded in one "MCP" arm.
"""

from __future__ import annotations

from typing import Any

from bench.arms import OBJECTIVE, Disclosure
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


def tool_definition(op: Operation, *, prefix: str = "", filtering: bool = False) -> dict[str, Any]:
    """One operation as an OpenAI-style function tool, the wire format OpenRouter expects."""
    properties = {p.name: _property_schema(p) for p in op.params}
    required = [p.name for p in op.params if p.required]
    if filtering:
        # What a server designed for agents would offer: project the response before returning it.
        # It costs schema tokens on every tool, which is the honest price of the capability.
        properties["_jq"] = {
            "type": "string",
            "description": (
                "Optional jq expression applied to the response before it is returned, "
                "e.g. '.dados|length'. Use it to avoid returning fields you do not need."
            ),
        }
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


def tool_definitions(
    registry: Registry, *, prefix: str = "", filtering: bool = False
) -> list[dict[str, Any]]:
    """The full tools array for the MCP arm.

    `prefix` reproduces the namespacing MCP clients apply to avoid collisions between connected
    servers (`camara__list_deputados`). It is a real, and rarely counted, part of the bill.
    """
    return [tool_definition(op, prefix=prefix, filtering=filtering) for op in registry]


def search_tool_definition() -> dict[str, Any]:
    """The meta-tool a deferred client exposes so the model can pull schemas in when it needs them.

    Two forms, because that is what real deferred loading does and because collapsing them into one
    is unfair to this format: a keyword query browses and returns names, while an explicit `select:`
    loads schemas. A search that always returned full definitions would charge the model a schema
    for every guess it made, which measures the search's design rather than the format's cost.
    """
    return {
        "type": "function",
        "function": {
            "name": "tool_search",
            "description": (
                "Find and load tools whose definitions are not yet available. "
                "Two forms: a keyword query (e.g. 'deputy expenses') returns matching tool names "
                "with a one-line summary each; `select:name1,name2` loads those tools' full "
                "definitions, after which they can be called."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Keywords to browse by, or `select:` followed by a comma-separated "
                            "list of exact tool names to load."
                        ),
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
    """The shared objective, plus the catalogue when this cell hands one over up front.

    No instructions. How to reach a tool is described by the tools themselves.
    """
    if disclosure != "indexed":
        return OBJECTIVE
    return f"{OBJECTIVE}\n\nTools:\n\n{tool_index(registry, prefix=prefix)}"


def tools_for(
    registry: Registry, *, disclosure: Disclosure = "eager", prefix: str = "", filtering: bool = False
) -> list[dict[str, Any]]:
    """The tools array actually sent, at each level of disclosure."""
    if disclosure == "eager":
        return tool_definitions(registry, prefix=prefix, filtering=filtering)
    return [search_tool_definition()]
