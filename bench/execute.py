"""Executing what the agent asked for, identically in both formats.

An MCP tool call and the equivalent CLI invocation must reach the same recorded response and return
the same bytes. If one format pretty-printed and the other did not, the comparison would be partly a
comparison of `json.dumps` arguments — so serialisation happens in one place, here.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Any

from bench.arms import cli as cli_arm
from bench.replay import Cassette
from bench.spec import Operation, Registry


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What comes back to the model, and what it cost to put there."""

    text: str
    ok: bool = True
    http_status: int | None = None
    operation: str | None = None


def _serialise(body: Any) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def _coerce(value: str) -> Any:
    """CLI flags arrive as text; tool calls arrive typed. Normalise so both hit the same cache key."""
    return value


def call_operation(
    registry: Registry,
    cassette: Cassette,
    name: str,
    arguments: dict[str, Any],
    *,
    prefix: str = "",
) -> ToolResult:
    """Run one operation by name, as the MCP format would."""
    bare = name[len(prefix) :] if prefix and name.startswith(prefix) else name
    try:
        operation = registry.by_name(bare)
    except KeyError:
        return ToolResult(text=f"error: no such tool {name!r}", ok=False)

    return _invoke(operation, cassette, arguments)


def _invoke(operation: Operation, cassette: Cassette, arguments: dict[str, Any]) -> ToolResult:
    path_values = {
        p.name: arguments[p.name] for p in operation.params if p.location == "path" and p.name in arguments
    }
    try:
        path = operation.render_path(path_values)
    except KeyError as exc:
        return ToolResult(text=f"error: {exc}", ok=False, operation=operation.name)

    query = {
        name: value
        for name, value in arguments.items()
        if name not in path_values and value is not None and value != ""
    }
    query = {k: ",".join(str(x) for x in v) if isinstance(v, list) else v for k, v in query.items()}

    recorded = cassette.get(path, query)
    return ToolResult(
        text=_serialise(recorded.body),
        ok=200 <= recorded.status < 300,
        http_status=recorded.status,
        operation=operation.name,
    )


def run_command(registry: Registry, cassette: Cassette, command: str) -> ToolResult:
    """Run one `api ...` command line, as the CLI format would.

    Supports exactly what the help text promises: `--help` at either level, positional path
    arguments, and `--flag value` options. Anything else is a usage error, which is what a real CLI
    would say too.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return ToolResult(text=f"error: could not parse command line: {exc}", ok=False)

    if tokens and tokens[0] == cli_arm.PROGRAM:
        tokens = tokens[1:]

    if not tokens or tokens[0] in {"--help", "-h", "help"}:
        return ToolResult(text=cli_arm.root_help(registry))

    name, rest = tokens[0], tokens[1:]
    try:
        operation = registry.by_name(name)
    except KeyError:
        return ToolResult(
            text=f"error: unknown command {name!r}. Run `{cli_arm.PROGRAM} --help` to list commands.",
            ok=False,
        )

    if any(token in {"--help", "-h"} for token in rest):
        return ToolResult(text=cli_arm.command_help(operation), operation=operation.name)

    arguments, error = _parse_arguments(operation, rest)
    if error is not None:
        return ToolResult(text=error, ok=False, operation=operation.name)

    return _invoke(operation, cassette, arguments)


def _parse_arguments(operation: Operation, tokens: list[str]) -> tuple[dict[str, Any], str | None]:
    known = {p.name for p in operation.params}
    positional_slots = [p.name for p in operation.params if p.location == "path"]
    arguments: dict[str, Any] = {}
    positionals: list[str] = []

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("--"):
            flag, _, inline = token[2:].partition("=")
            if flag not in known:
                return {}, (
                    f"error: unknown option --{flag} for {operation.name}. "
                    f"Run `{cli_arm.PROGRAM} {operation.name} --help` for the accepted options."
                )
            if inline:
                arguments[flag] = _coerce(inline)
                index += 1
                continue
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                return {}, f"error: option --{flag} expects a value"
            arguments[flag] = _coerce(tokens[index + 1])
            index += 2
            continue
        positionals.append(token)
        index += 1

    if len(positionals) > len(positional_slots):
        return {}, (
            f"error: {operation.name} takes {len(positional_slots)} positional argument(s), "
            f"got {len(positionals)}"
        )
    arguments.update(dict(zip(positional_slots, positionals, strict=False)))

    missing = [p.name for p in operation.params if p.required and p.name not in arguments]
    if missing:
        return {}, f"error: {operation.name} requires {', '.join(missing)}"
    return arguments, None
