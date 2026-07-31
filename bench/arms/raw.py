"""The raw format: an HTTP verb, a base URL, and nothing else.

This is the floor of the triad. The model is told which API it is pointing at and given a way to GET
from it; there are no schemas, no help text and no catalogue. Whatever it learns, it learns by
probing — which makes this arm the price tag on documentation itself. Every number the other two
formats produce is only meaningful next to what it costs to have no documentation at all.

It is also the contamination check that comes for free: a model that answers correctly here, without
ever being told a route or a parameter, knew the API before it started.
"""

from __future__ import annotations

from typing import Any

from bench.arms import OBJECTIVE, Disclosure
from bench.spec import Registry


def tool_definition(base_url: str, title: str, *, filtering: bool = False) -> dict[str, Any]:
    """The single affordance this format has.

    The base URL lives here rather than in the system prompt: it is mechanism, and mechanism belongs
    to the tools. Naming the API is not a hint — you always know which service you are pointing at.
    """
    description = (
        f"Perform an HTTP GET against the {title} API, whose base URL is {base_url}, "
        "and return the response body. Pass an absolute URL or a path relative to the base."
    )
    properties: dict[str, Any] = {
        "url": {
            "type": "string",
            "description": f"The URL to fetch, e.g. `{base_url}/some/path?param=value`.",
        }
    }
    if filtering:
        properties["_jq"] = {
            "type": "string",
            "description": (
                "Optional jq expression applied to the response before it is returned, e.g. '.dados|length'."
            ),
        }
    return {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": ["url"]},
        },
    }


def tools_for(
    registry: Registry, *, disclosure: Disclosure = "lazy", filtering: bool = False
) -> list[dict[str, Any]]:
    """One tool, always. There is no disclosure level here — that is the whole point of the arm."""
    del disclosure
    return [tool_definition(registry.base_url, registry.title, filtering=filtering)]


def system_prompt(registry: Registry, *, disclosure: Disclosure = "lazy") -> str:
    """The same objective as every other cell. Nothing is explained."""
    del registry, disclosure
    return OBJECTIVE
