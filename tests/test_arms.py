"""The arms must differ in exposure and in nothing else.

If an operation or a parameter can reach one arm without reaching the other, the benchmark stops
measuring MCP against CLI and starts measuring one generator's bugs against the other's. These
tests are the guard on that, so they check equivalence rather than formatting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench import spec
from bench.arms import cli, mcp

SPEC = Path(__file__).resolve().parents[1] / "data" / "specs" / "camara-dados-abertos-v2.json"


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


def test_same_operations_reach_both_arms(registry: spec.Registry) -> None:
    from_mcp = {t["function"]["name"] for t in mcp.tool_definitions(registry)}
    help_text = cli.root_help(registry)
    from_cli = {
        op.name for op in registry if f"    {op.name} " in help_text or f"    {op.name}\n" in help_text
    }
    assert from_mcp == {op.name for op in registry}
    assert from_cli == from_mcp


def test_same_parameters_reach_both_arms(registry: spec.Registry) -> None:
    tools = {t["function"]["name"]: t for t in mcp.tool_definitions(registry)}
    for op in registry:
        schema = tools[op.name]["function"]["parameters"]
        in_mcp = set(schema["properties"])
        assert in_mcp == {p.name for p in op.params}

        text = cli.command_help(op)
        for p in op.params:
            token = f"<{p.name}>" if p.location == "path" else f"--{p.name} "
            assert token in text, f"{op.name}: {p.name} is exposed by MCP but not by the CLI"


def test_required_parameters_agree(registry: spec.Registry) -> None:
    tools = {t["function"]["name"]: t for t in mcp.tool_definitions(registry)}
    for op in registry:
        schema = tools[op.name]["function"]["parameters"]
        required_mcp = set(schema.get("required", []))
        assert required_mcp == {p.name for p in op.required_params}

        text = cli.command_help(op)
        for p in op.params:
            if p.location == "path":
                continue  # positional arguments are required by construction in the usage line
            line = next(line for line in text.splitlines() if line.strip().startswith(f"--{p.name} "))
            assert ("(required)" in line) == p.required


def test_prefix_is_applied_to_every_tool(registry: spec.Registry) -> None:
    tools = mcp.tool_definitions(registry, prefix="camara__")
    assert all(t["function"]["name"].startswith("camara__") for t in tools)


def test_cli_arm_exposes_exactly_one_tool_at_any_n(registry: spec.Registry) -> None:
    # The whole premise of the arm: its upfront cost does not grow with the number of operations.
    assert cli.tool_definition()["function"]["name"] == "run_cli"
    small, large = registry.sample(5, seed=0), registry
    assert cli.system_prompt(small) == cli.system_prompt(large)


def test_rendering_is_byte_stable(registry: spec.Registry) -> None:
    # Token counts are only comparable if the same registry always renders identically.
    op = registry.by_name("list_proposicoes")
    assert cli.command_help(op) == cli.command_help(op)
    assert cli.root_help(registry) == cli.root_help(registry)
    assert cli.full_help(registry).startswith(cli.root_help(registry))


def test_help_stays_within_the_declared_width(registry: spec.Registry) -> None:
    for line in cli.full_help(registry).splitlines():
        assert len(line) <= 200, "help lines must not blow up; long descriptions are wrapped"
