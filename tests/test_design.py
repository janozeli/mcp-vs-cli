"""Structural properties of the design.

These pin what makes a cell *that* cell — a lazy arm's cost must not grow with N, an eager arm must
have nothing left to fetch — and deliberately do not pin the measured numbers. The findings are
allowed to move when the vendored spec is refreshed; the design is not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench import design, spec
from bench.arms import cli, mcp

SPEC = Path(__file__).resolve().parents[1] / "data" / "specs" / "camara-dados-abertos-v2.json"


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


def test_design_is_fully_crossed(registry: spec.Registry) -> None:
    keys = [arm.key for arm in design.arms(registry)]
    assert keys == [
        "mcp/eager",
        "mcp/indexed",
        "mcp/lazy",
        "cli/eager",
        "cli/indexed",
        "cli/lazy",
    ]


def test_lazy_arms_do_not_grow_with_n(registry: spec.Registry) -> None:
    # The defining property of the cell: whatever the API's size, the agent starts from the same place.
    small = {a.key: a for a in design.arms(registry.sample(5, seed=0))}
    large = {a.key: a for a in design.arms(registry)}
    for key in ("mcp/lazy", "cli/lazy"):
        assert small[key].upfront == large[key].upfront


def test_eager_arms_grow_with_n(registry: spec.Registry) -> None:
    small = {a.key: a for a in design.arms(registry.sample(5, seed=0))}
    large = {a.key: a for a in design.arms(registry)}
    for key in ("mcp/eager", "cli/eager"):
        assert large[key].upfront > 5 * small[key].upfront


def test_disclosure_orders_upfront_cost(registry: spec.Registry) -> None:
    by_key = {a.key: a for a in design.arms(registry)}
    for fmt in design.FORMATS:
        eager, indexed, lazy = (by_key[f"{fmt}/{d}"] for d in ("eager", "indexed", "lazy"))
        assert eager.upfront > indexed.upfront > lazy.upfront


def test_eager_arms_have_nothing_left_to_fetch(registry: spec.Registry) -> None:
    for arm in design.arms(registry):
        if arm.disclosure == "eager":
            assert arm.detail_on_demand == ()
            assert arm.catalogue_on_demand == 0
            assert arm.readiness(5) == arm.upfront


def test_indexed_arms_pay_for_detail_but_not_for_the_catalogue(registry: spec.Registry) -> None:
    for arm in design.arms(registry):
        if arm.disclosure == "indexed":
            assert arm.catalogue_on_demand == 0
            assert len(arm.detail_on_demand) == len(registry)
            assert arm.readiness(2) > arm.upfront


def test_lazy_arms_pay_for_both(registry: spec.Registry) -> None:
    for arm in design.arms(registry):
        if arm.disclosure == "lazy":
            assert arm.catalogue_on_demand > 0
            assert len(arm.detail_on_demand) == len(registry)


def test_every_operation_is_reachable_in_every_cell(registry: spec.Registry) -> None:
    """Deferring a description must never hide a capability."""
    index = mcp.tool_index(registry, prefix="camara__")
    manual = cli.full_help(registry)
    root = cli.root_help(registry)
    schemas = {t["function"]["name"] for t in mcp.tool_definitions(registry, prefix="camara__")}
    for op in registry:
        assert f"camara__{op.name}" in index
        assert f"camara__{op.name}" in schemas
        assert op.name in root
        assert op.name in manual


def test_lazy_arms_still_carry_a_way_in(registry: spec.Registry) -> None:
    assert mcp.tools_for(registry, disclosure="lazy")[0]["function"]["name"] == "tool_search"
    assert cli.tools_for(registry, disclosure="lazy")[0]["function"]["name"] == "run_cli"
    assert len(mcp.tools_for(registry, disclosure="lazy")) == 1
    assert len(mcp.tools_for(registry, disclosure="eager")) == len(registry)
