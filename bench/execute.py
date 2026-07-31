"""Executing what the agent asked for, identically in every format.

An MCP tool call, the equivalent CLI invocation and the equivalent raw URL must produce the same
request and return the same bytes. If one format pretty-printed and the other did not, the
comparison would be partly a comparison of `json.dumps` arguments — so serialisation happens in one
place, here.

Nothing is stored between calls. Two arms that ask the same question ask it twice, and whether they
got the same answer is checked afterwards from the traces rather than guaranteed by a freezer.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import jq

from bench.api import Api, canonical_request
from bench.arms import cli as cli_arm
from bench.spec import Operation, Registry

FILTER_ARGUMENT = "_jq"
"""The projection parameter the filtered MCP cell adds to every tool.

Same language as the CLI's pipe, so the comparison is about where the filtering happens rather than
about which syntax the model happens to know.
"""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What comes back to the model, and what it cost to put there."""

    text: str
    ok: bool = True
    http_status: int | None = None
    operation: str | None = None

    request: str | None = None
    """The resolved request, in the canonical form every format reduces to.

    The three formats spell the same call differently — a tool call, a command line, a URL — so this
    is what makes them comparable after the fact. Without it, checking whether two arms saw the same
    bytes would compare spellings and always find nothing.
    """


def _serialise(body: Any) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def apply_filter(body: Any, expression: str) -> tuple[str, bool]:
    """Run a jq expression over a response, returning the text and whether it worked.

    A bad expression comes back as an error the model can read and correct, exactly as a failed
    pipe would. Silently returning the unfiltered body instead would hide the cost of getting it
    wrong, which is part of what filtering actually costs.
    """
    try:
        outputs = jq.compile(expression).input_value(body).all()
    except ValueError as exc:
        return f"jq: error: {exc}", False
    except Exception as exc:  # a runtime failure inside the expression
        return f"jq: error: {type(exc).__name__}: {exc}", False
    return "\n".join(_serialise(item) for item in outputs), True


def _coerce(value: str) -> Any:
    """CLI flags arrive as text and tool calls arrive typed; the wire takes both as text."""
    return value


def call_operation(
    registry: Registry,
    api: Api,
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

    arguments = dict(arguments)
    expression = arguments.pop(FILTER_ARGUMENT, None)
    return _invoke(operation, api, arguments, jq_expression=expression)


def _invoke(
    operation: Operation,
    api: Api,
    arguments: dict[str, Any],
    *,
    jq_expression: str | None = None,
) -> ToolResult:
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

    response = api.get(path, query)
    request = canonical_request("GET", path, query)
    ok = response.ok
    if jq_expression and ok:
        text, filtered_ok = apply_filter(response.body, jq_expression)
        return ToolResult(
            text=text,
            ok=filtered_ok,
            http_status=response.status,
            operation=operation.name,
            request=request,
        )
    return ToolResult(
        text=_serialise(response.body),
        ok=ok,
        http_status=response.status,
        operation=operation.name,
        request=request,
    )


def fetch_url(api: Api, url: str, *, jq_expression: str | None = None) -> ToolResult:
    """Run one GET, as the raw format would.

    The URL is reduced to the same path and parameters the other formats produce, so a probe and a
    tool call that mean the same request become the same request. A URL outside the API is refused:
    the arm is meant to explore this API, not the internet.
    """
    parsed = urlsplit(url.strip())
    base = urlsplit(api.base_url)
    if parsed.scheme or parsed.netloc:
        if (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            return ToolResult(text=f"error: this tool only reaches {api.base_url}, not {url!r}.", ok=False)
        path = parsed.path
    else:
        path = parsed.path if parsed.path.startswith("/") else f"/{parsed.path}"

    if path.startswith(base.path):
        path = path[len(base.path) :] or "/"
    params = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=False)}

    response = api.get(path, params)
    request = canonical_request("GET", path, params)
    ok = response.ok
    if jq_expression and ok:
        text, filtered_ok = apply_filter(response.body, jq_expression)
        return ToolResult(text=text, ok=filtered_ok, http_status=response.status, request=request)
    return ToolResult(text=_serialise(response.body), ok=ok, http_status=response.status, request=request)


def run_command(registry: Registry, api: Api, command: str, *, allow_pipe: bool = False) -> ToolResult:
    """Run one `api ...` command line, as the CLI format would.

    Supports exactly what the help text promises: `--help` at either level, positional path
    arguments, and `--flag value` options. Anything else is a usage error, which is what a real CLI
    would say too.

    With `allow_pipe`, a single `| jq '<expr>'` may follow, and only jq — the point is to give the
    agent a way to reduce a response before it reaches the context, not to build a shell.
    """
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return ToolResult(text=f"error: could not parse command line: {exc}", ok=False)

    tokens, expression, pipe_error = _split_pipe(tokens, allow_pipe=allow_pipe)
    if pipe_error is not None:
        return ToolResult(text=pipe_error, ok=False)

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

    return _invoke(operation, api, arguments, jq_expression=expression)


def _split_pipe(tokens: list[str], *, allow_pipe: bool) -> tuple[list[str], str | None, str | None]:
    """Separate `cmd | jq 'expr'` into its two halves."""
    if "|" not in tokens:
        return tokens, None, None
    if not allow_pipe:
        return tokens, None, "error: this tool runs a single command; pipes are not available."

    index = tokens.index("|")
    left, right = tokens[:index], tokens[index + 1 :]
    if "|" in right:
        return tokens, None, "error: only one pipe is supported, and it must be to jq."
    if not right or right[0] != "jq":
        target = right[0] if right else "nothing"
        return tokens, None, f"error: can only pipe to jq, not to {target!r}."
    if len(right) != 2:
        return tokens, None, "error: jq takes exactly one filter expression, quoted."
    return left, right[1], None


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
