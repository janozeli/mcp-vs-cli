"""The experimental design: format crossed with disclosure, and what each cell costs in context.

Two independent factors, fully crossed:

- **format** — how a capability is described: a JSON Schema (`mcp`) or a page of help text (`cli`).
- **disclosure** — when that description enters the context: `eager`, `indexed`, or `lazy`.

Costs are split into what an arm occupies before the task is read, and what it pays later. Later is
not free: a catalogue or a schema fetched mid-run arrives as a tool result and occupies the window
exactly like anything else. `readiness` is the honest total — everything an arm must hold in context
to be in a position to call `k` operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from bench import tokens
from bench.arms import DISCLOSURES, Disclosure
from bench.arms import cli as cli_arm
from bench.arms import mcp as mcp_arm
from bench.spec import Registry

FORMATS = ("mcp", "cli")


@dataclass(frozen=True, slots=True)
class Arm:
    """One cell of the design, priced."""

    fmt: str
    disclosure: Disclosure
    upfront_tools: int
    upfront_system: int
    catalogue_on_demand: int
    detail_on_demand: tuple[int, ...]

    @property
    def key(self) -> str:
        return f"{self.fmt}/{self.disclosure}"

    @property
    def upfront(self) -> int:
        """What the arm occupies before the model has read the task."""
        return self.upfront_tools + self.upfront_system

    @property
    def detail_median(self) -> int:
        if not self.detail_on_demand:
            return 0
        return sorted(self.detail_on_demand)[len(self.detail_on_demand) // 2]

    def readiness(self, k: int) -> int:
        """Context held to be ready to call `k` operations, including what was fetched to get there."""
        return self.upfront + self.catalogue_on_demand + k * self.detail_median


def _mcp_arm(registry: Registry, disclosure: Disclosure, prefix: str) -> Arm:
    tools = mcp_arm.tools_for(registry, disclosure=disclosure, prefix=prefix)
    system = mcp_arm.system_prompt(registry, disclosure=disclosure, prefix=prefix)
    detail = (
        ()
        if disclosure == "eager"
        else tuple(tokens.count_json(mcp_arm.tool_definition(op, prefix=prefix)) for op in registry)
    )
    return Arm(
        fmt="mcp",
        disclosure=disclosure,
        upfront_tools=tokens.count_json(tools),
        upfront_system=tokens.count_text(system),
        catalogue_on_demand=(
            tokens.count_text(mcp_arm.tool_index(registry, prefix=prefix)) if disclosure == "lazy" else 0
        ),
        detail_on_demand=detail,
    )


def _cli_arm(registry: Registry, disclosure: Disclosure) -> Arm:
    tools = cli_arm.tools_for(registry, disclosure=disclosure)
    system = cli_arm.system_prompt(registry, disclosure=disclosure)
    detail = (
        () if disclosure == "eager" else tuple(tokens.count_text(cli_arm.command_help(op)) for op in registry)
    )
    return Arm(
        fmt="cli",
        disclosure=disclosure,
        upfront_tools=tokens.count_json(tools),
        upfront_system=tokens.count_text(system),
        catalogue_on_demand=(tokens.count_text(cli_arm.root_help(registry)) if disclosure == "lazy" else 0),
        detail_on_demand=detail,
    )


def arms(registry: Registry, *, prefix: str = "") -> list[Arm]:
    """All six cells, in a stable order."""
    return [
        _mcp_arm(registry, d, prefix) if fmt == "mcp" else _cli_arm(registry, d)
        for fmt in FORMATS
        for d in DISCLOSURES
    ]
