"""Filtering is where the two formats stop being interchangeable, so it is tested on both sides.

The mechanism is deliberately the same language in both cells. If the CLI could pipe to jq while the
tools offered some bespoke field selector, the result would partly measure which syntax the model
knows better — and it knows jq.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench import execute, spec, tokens
from bench.api import Api
from bench.arms import cli as cli_arm
from bench.arms import mcp as mcp_arm

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"

VOTES = "2400758-37"
COUNT_SP_YES = '[.dados[]|select(.tipoVoto=="Sim" and .deputado_.siglaUf=="SP")]|length'


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


def test_both_formats_filter_to_the_same_answer(registry: spec.Registry, api: Api) -> None:
    from_mcp = execute.call_operation(
        registry, api, "list_votacoes_votos", {"id": VOTES, "_jq": COUNT_SP_YES}
    )
    from_cli = execute.run_command(
        registry, api, f"api list_votacoes_votos {VOTES} | jq '{COUNT_SP_YES}'", allow_pipe=True
    )
    assert from_mcp.text == from_cli.text == "2"


def test_filtering_is_what_makes_the_payload_affordable(registry: spec.Registry, api: Api) -> None:
    whole = execute.call_operation(registry, api, "list_votacoes_votos", {"id": VOTES})
    filtered = execute.call_operation(
        registry, api, "list_votacoes_votos", {"id": VOTES, "_jq": COUNT_SP_YES}
    )
    # The point of the axis: the same answer, at a fraction of the context.
    assert tokens.count_text(whole.text) > 20 * tokens.count_text(filtered.text)


def test_a_bad_expression_comes_back_as_an_error(registry: spec.Registry, api: Api) -> None:
    result = execute.call_operation(
        registry, api, "list_votacoes_votos", {"id": VOTES, "_jq": "this is not jq"}
    )
    assert not result.ok
    assert result.text.startswith("jq: error")
    # Falling back to the unfiltered body would hide what getting it wrong costs.
    assert len(result.text) < 500


def test_pipes_are_refused_when_the_cell_does_not_have_them(registry: spec.Registry, api: Api) -> None:
    result = execute.run_command(registry, api, f"api list_votacoes_votos {VOTES} | jq '.'")
    assert not result.ok
    assert "pipes are not available" in result.text


def test_only_jq_may_follow_the_pipe(registry: spec.Registry, api: Api) -> None:
    for command, expected in (
        (f"api list_votacoes_votos {VOTES} | grep Sim", "can only pipe to jq"),
        (f"api list_votacoes_votos {VOTES} | jq '.' | jq '.'", "only one pipe"),
        (f"api list_votacoes_votos {VOTES} | jq", "exactly one filter expression"),
    ):
        result = execute.run_command(registry, api, command, allow_pipe=True)
        assert not result.ok, command
        assert expected in result.text, command


def test_help_still_works_through_a_filtering_cell(registry: spec.Registry, api: Api) -> None:
    result = execute.run_command(registry, api, "api --help", allow_pipe=True)
    assert result.ok and "list_deputados" in result.text


def test_the_capability_is_advertised_and_paid_for(registry: spec.Registry) -> None:
    plain = cli_arm.tool_definition()["function"]["description"]
    piped = cli_arm.tool_definition(filtering=True)["function"]["description"]
    assert "jq" not in plain and "jq" in piped

    operation = registry.by_name("list_votacoes_votos")
    without = mcp_arm.tool_definition(operation)
    with_filter = mcp_arm.tool_definition(operation, filtering=True)
    assert "_jq" not in without["function"]["parameters"]["properties"]
    assert "_jq" in with_filter["function"]["parameters"]["properties"]
    # A server that offers projection pays for saying so, on every tool.
    assert tokens.count_json(with_filter) > tokens.count_json(without)


def test_the_filter_parameter_never_reaches_the_api(registry: spec.Registry, api: Api) -> None:
    # `_jq` is applied after the response arrives; sending it upstream would change the request.
    result = execute.call_operation(
        registry, api, "list_deputados", {"siglaUf": "AC", "itens": 100, "_jq": ".dados|length"}
    )
    assert result.text == "3"
