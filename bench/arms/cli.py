"""The CLI arm: every operation becomes a subcommand behind a single tool.

The agent is given one tool, `run_cli`, and has to find out what the CLI can do the way a person
would — by running `--help`. That trades context for turns, which is exactly the trade the
benchmark is trying to price.

Help text is rendered here rather than by argparse so that the output is byte-stable across Python
versions and terminal widths. Token counts must not depend on where the harness happens to run.
"""

from __future__ import annotations

import textwrap
from typing import Any

from bench.arms import OBJECTIVE, Disclosure
from bench.spec import Operation, Param, Registry

PROGRAM = "api"
_WIDTH = 96
_INDENT = 4


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _flag(param: Param) -> str:
    if param.location == "path":
        return f"<{param.name}>"
    return f"--{param.name} <{param.type}>"


def _wrap(text: str, indent: int) -> list[str]:
    pad = " " * indent
    out: list[str] = []
    for block in text.split("\n"):
        stripped = block.strip()
        if not stripped:
            continue
        out.extend(textwrap.wrap(stripped, width=_WIDTH - indent, initial_indent=pad, subsequent_indent=pad))
    return out


def command_help(op: Operation) -> str:
    """`api <command> --help` — the full contract for one operation, fetched on demand."""
    positional = " ".join(f"<{p.name}>" for p in op.params if p.location == "path")
    usage = f"usage: {PROGRAM} {op.name}"
    if positional:
        usage += f" {positional}"
    if any(p.location != "path" for p in op.params):
        usage += " [options]"

    lines = [usage, ""]
    body = "\n".join(t for t in (op.summary, op.description) if t)
    if body:
        lines.extend(_wrap(body, 0))
        lines.append("")

    options = [p for p in op.params if p.location != "path"]
    if positional:
        lines.append("Arguments:")
        for p in (q for q in op.params if q.location == "path"):
            lines.append(f"{' ' * _INDENT}{p.name}")
            lines.extend(_wrap(p.description, _INDENT * 2))
        lines.append("")
    if options:
        lines.append("Options:")
        for p in options:
            head = f"{' ' * _INDENT}{_flag(p)}"
            if p.required:
                head += "  (required)"
            if p.default is not None:
                head += f"  [default: {p.default}]"
            if p.enum:
                head += f"  {{{','.join(p.enum)}}}"
            lines.append(head)
            lines.extend(_wrap(p.description, _INDENT * 2))
    return "\n".join(lines).rstrip() + "\n"


def root_help(registry: Registry) -> str:
    """`api --help` — one line per command, which is the whole point of the arm."""
    groups = registry.groups()
    lines = [
        f"{PROGRAM} — {registry.title}",
        "",
        f"usage: {PROGRAM} <command> [options]",
        "",
        f"Run `{PROGRAM} <command> --help` to see the options of a command.",
        "",
    ]
    width = max((len(op.name) for op in registry), default=0)
    for group, ops in groups.items():
        lines.append(f"{group}:")
        for op in ops:
            summary = _first_line(op.summary or op.description)
            lines.append(f"{' ' * _INDENT}{op.name.ljust(width)}  {summary}".rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def full_help(registry: Registry) -> str:
    """Root help plus every command's help — what the preloaded-CLI arm is handed up front."""
    parts = [root_help(registry)]
    parts.extend(command_help(op) for op in registry)
    return "\n".join(parts)


def tool_definition() -> dict[str, Any]:
    """The single tool the CLI arm exposes, whatever N is."""
    return {
        "type": "function",
        "function": {
            "name": "run_cli",
            "description": (
                f"Run the `{PROGRAM}` command-line tool and return its stdout. "
                f"`{PROGRAM} --help` lists the available commands; "
                f"`{PROGRAM} <command> --help` describes one command's arguments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": f"The full command line to run, e.g. `{PROGRAM} --help`.",
                    }
                },
                "required": ["command"],
            },
        },
    }


def system_prompt(registry: Registry, *, disclosure: Disclosure = "lazy") -> str:
    """The shared objective, plus the documentation this cell hands over up front.

    No instructions. How to reach a command is described by the tool itself.
    """
    if disclosure == "eager":
        return f"{OBJECTIVE}\n\n{full_help(registry)}"
    if disclosure == "indexed":
        return f"{OBJECTIVE}\n\n{root_help(registry)}"
    return OBJECTIVE


def tools_for(registry: Registry, *, disclosure: Disclosure = "lazy") -> list[dict[str, Any]]:
    """One tool, at every level of disclosure and every N. That is the point of the format."""
    del registry, disclosure
    return [tool_definition()]
