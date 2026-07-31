"""Every format must produce the same request and hand back the same bytes.

This is the last place the arms could drift apart without anyone noticing: the schemas could match
perfectly and the comparison still be spoiled if one path pretty-printed its JSON and the other did
not, or if one sent `100` where another sent `"100"`.

The API here is a hand-written stub — see conftest. Nothing recorded from the live service is kept
anywhere in this repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench import execute, spec
from bench.api import Api

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


@pytest.mark.parametrize(
    ("tool_name", "arguments", "command"),
    [
        ("list_deputados", {"siglaUf": "AC", "itens": 100}, "api list_deputados --siglaUf AC --itens 100"),
        ("get_deputados", {"id": 204554}, "api get_deputados 204554"),
        ("list_votacoes_votos", {"id": "2400758-37"}, "api list_votacoes_votos 2400758-37"),
    ],
)
def test_both_formats_return_identical_bytes(
    registry: spec.Registry,
    api: Api,
    tool_name: str,
    arguments: dict,
    command: str,
) -> None:
    from_mcp = execute.call_operation(registry, api, tool_name, arguments)
    from_cli = execute.run_command(registry, api, command)
    assert from_mcp.text == from_cli.text
    assert from_mcp.operation == from_cli.operation == tool_name
    assert from_mcp.ok == from_cli.ok


def test_typed_and_textual_arguments_produce_the_same_request(registry: spec.Registry, api: Api) -> None:
    typed = execute.call_operation(registry, api, "list_deputados", {"siglaUf": "AC", "itens": 100})
    textual = execute.call_operation(registry, api, "list_deputados", {"siglaUf": "AC", "itens": "100"})
    assert typed.text == textual.text


def test_server_prefix_is_stripped(registry: spec.Registry, api: Api) -> None:
    result = execute.call_operation(registry, api, "camara__get_deputados", {"id": 204554}, prefix="camara__")
    assert result.ok
    assert "SANTOS" in result.text


def test_api_errors_reach_the_agent_intact(registry: spec.Registry, api: Api) -> None:
    # The votes endpoint rejects `itens` with a 400. That obstacle is part of the task, so it must
    # arrive as a real error the agent can read and recover from.
    result = execute.call_operation(registry, api, "list_votacoes_votos", {"id": "2400758-37", "itens": 600})
    assert not result.ok
    assert result.http_status == 400
    assert "invál" in result.text.lower() or "400" in result.text


def test_help_is_reachable_at_both_levels(registry: spec.Registry, api: Api) -> None:
    root = execute.run_command(registry, api, "api --help")
    assert "list_deputados" in root.text and root.ok

    detail = execute.run_command(registry, api, "api list_deputados --help")
    assert "--siglaUf" in detail.text
    assert "Options:" in detail.text


def test_bare_program_name_prints_usage(registry: spec.Registry, api: Api) -> None:
    assert execute.run_command(registry, api, "api").text.startswith("api ")


def test_unknown_command_says_how_to_recover(registry: spec.Registry, api: Api) -> None:
    result = execute.run_command(registry, api, "api list_senadores")
    assert not result.ok
    assert "--help" in result.text


def test_unknown_option_names_the_command_to_ask(registry: spec.Registry, api: Api) -> None:
    result = execute.run_command(registry, api, "api list_deputados --estado SP")
    assert not result.ok
    assert "--estado" in result.text
    assert "list_deputados --help" in result.text


def test_missing_required_argument_is_refused(registry: spec.Registry, api: Api) -> None:
    result = execute.run_command(registry, api, "api get_deputados")
    assert not result.ok
    assert "requires" in result.text or "missing" in result.text


def test_inline_flag_values_work(registry: spec.Registry, api: Api) -> None:
    inline = execute.run_command(registry, api, "api list_deputados --siglaUf=AC --itens=100")
    spaced = execute.run_command(registry, api, "api list_deputados --siglaUf AC --itens 100")
    assert inline.text == spaced.text


def test_unknown_tool_name_is_an_error_not_a_crash(registry: spec.Registry, api: Api) -> None:
    result = execute.call_operation(registry, api, "list_senadores", {})
    assert not result.ok
    assert "no such tool" in result.text
