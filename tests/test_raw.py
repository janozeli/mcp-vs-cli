"""The baseline arm has to reach the same endpoints as the other two, or it is not a baseline.

A blind probe and a tool call that mean the same request must become the same request, or the arms
are asking different questions and the comparison is worthless.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench import execute, spec, triad
from bench.api import Api
from bench.arms import OBJECTIVE
from bench.arms import raw as raw_arm

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"
BASE = "https://api.example.test/v2"


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


@pytest.mark.parametrize(
    "url",
    [
        f"{BASE}/deputados/204554",
        "/deputados/204554",
        "deputados/204554",
    ],
)
def test_absolute_and_relative_urls_reach_the_same_endpoint(
    registry: spec.Registry, api: Api, url: str
) -> None:
    result = execute.fetch_url(api, url)
    assert result.ok
    assert "SANTOS" in result.text


def test_a_probe_becomes_the_same_request_as_a_tool_call(registry: spec.Registry, api: Api) -> None:
    probed = execute.fetch_url(api, f"{BASE}/deputados?siglaUf=AC&itens=100")
    called = execute.call_operation(registry, api, "list_deputados", {"siglaUf": "AC", "itens": 100})
    assert probed.text == called.text


def test_query_order_does_not_change_the_request(registry: spec.Registry, api: Api) -> None:
    a = execute.fetch_url(api, f"{BASE}/deputados?siglaUf=AC&itens=100")
    b = execute.fetch_url(api, f"{BASE}/deputados?itens=100&siglaUf=AC")
    assert a.text == b.text


def test_the_api_teaches_through_its_errors(registry: spec.Registry, api: Api) -> None:
    # Blind discovery is only viable because this API names the offending parameter back.
    result = execute.fetch_url(api, f"{BASE}/votacoes/2400758-37/votos?itens=600")
    assert not result.ok
    assert result.http_status == 400
    assert "itens" in result.text


def test_the_tool_will_not_leave_the_api(registry: spec.Registry, api: Api) -> None:
    result = execute.fetch_url(api, "https://example.com/anything")
    assert not result.ok
    assert "only reaches" in result.text


def test_the_baseline_is_told_where_to_start_and_nothing_else(registry: spec.Registry) -> None:
    tools = raw_arm.tools_for(registry)
    assert len(tools) == 1
    description = tools[0]["function"]["description"]
    assert registry.base_url in description
    # No routes, no parameters, no catalogue: that is the whole point of the arm.
    for leak in ("deputados", "proposicoes", "siglaUf", "--help"):
        assert leak not in description

    assert raw_arm.system_prompt(registry) == OBJECTIVE


def test_filtering_is_opt_in_for_the_baseline_too(registry: spec.Registry) -> None:
    plain = raw_arm.tools_for(registry)[0]["function"]["parameters"]["properties"]
    filtered = raw_arm.tools_for(registry, filtering=True)[0]["function"]["parameters"]["properties"]
    assert "_jq" not in plain
    assert "_jq" in filtered


def test_the_triad_is_the_unoptimised_default_of_each_format() -> None:
    keys = [arm.key for arm in triad.TRIAD]
    assert keys == ["baseline", "mcp", "cli"]

    assert triad.by_key("mcp").disclosure == "eager", "the off-the-shelf server declares everything"
    assert triad.by_key("cli").disclosure == "lazy", "nobody preloads a manual unprompted"
    assert all(arm.handling == "whole" for arm in triad.TRIAD), "level zero does not filter"

    # Blind discovery needs room, or the number measures the ceiling instead of the arm.
    assert triad.by_key("baseline").max_turns > triad.by_key("cli").max_turns
