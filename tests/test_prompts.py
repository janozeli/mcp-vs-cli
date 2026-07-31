"""The system prompt states the objective and nothing else.

A prompt that also taught the model *how* to reach its tools would stop being a constant of the
experiment and become part of the treatment. Telling one cell to run `--help` first while telling
another only that tools can be searched is not the same amount of help, and the difference would
show up in the results as if it were a property of the format.

So: the objective is byte-identical everywhere, mechanism lives in the tool descriptions, and
anything else in the prompt has to be data — a catalogue or a manual, which is what is being priced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench import spec
from bench.arms import DISCLOSURES, OBJECTIVE
from bench.arms import cli as cli_arm
from bench.arms import mcp as mcp_arm

SPEC = Path(__file__).resolve().parents[1] / "data" / "specs" / "camara-dados-abertos-v2.json"

# Words that would be teaching a procedure rather than stating a goal.
INSTRUCTIONAL = ("first", "start with", "use `", "you should", "then call", "remember to")


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


def _prompts(registry: spec.Registry) -> dict[str, str]:
    out = {}
    for disclosure in DISCLOSURES:
        out[f"mcp/{disclosure}"] = mcp_arm.system_prompt(registry, disclosure=disclosure, prefix="camara__")
        out[f"cli/{disclosure}"] = cli_arm.system_prompt(registry, disclosure=disclosure)
    return out


def test_every_prompt_opens_with_the_same_objective(registry: spec.Registry) -> None:
    for arm, prompt in _prompts(registry).items():
        assert prompt.startswith(OBJECTIVE), arm


def test_the_objective_names_no_mechanism() -> None:
    lowered = OBJECTIVE.lower()
    for word in ("cli", "command", "--help", "tool_search", "search", "api`", "load"):
        assert word not in lowered, f"the objective mentions {word!r}"


def test_no_prompt_teaches_a_procedure(registry: spec.Registry) -> None:
    for arm, prompt in _prompts(registry).items():
        # Only the objective line is prose; the rest must be catalogue or manual.
        preamble = prompt[: len(OBJECTIVE)]
        assert not any(marker in preamble.lower() for marker in INSTRUCTIONAL), arm


def test_cells_without_a_catalogue_get_nothing_but_the_objective(registry: spec.Registry) -> None:
    prompts = _prompts(registry)
    assert prompts["mcp/eager"] == OBJECTIVE
    assert prompts["mcp/lazy"] == OBJECTIVE
    assert prompts["cli/lazy"] == OBJECTIVE


def test_the_prompt_difference_is_only_data(registry: spec.Registry) -> None:
    prompts = _prompts(registry)
    assert prompts["mcp/indexed"].removeprefix(OBJECTIVE).strip().startswith("Tools:")
    assert prompts["cli/indexed"].removeprefix(OBJECTIVE).strip().startswith(cli_arm.PROGRAM)
    assert prompts["cli/eager"].removeprefix(OBJECTIVE).strip().startswith(cli_arm.PROGRAM)


def test_mechanism_lives_in_the_tool_descriptions() -> None:
    # What a cell needs to know to act is an affordance of its tools, and is counted in their tokens.
    run_cli = cli_arm.tool_definition()["function"]["description"]
    assert "--help" in run_cli

    search = mcp_arm.search_tool_definition()["function"]["description"]
    assert "select:" in search
