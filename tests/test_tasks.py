"""The suite grades agents, so it has to be graded first.

These tests check the *solvers and the grader*, against the hand-written API in conftest. They
deliberately do not check whether the real answers are still the real answers: that is a question
about the world, it can only be answered by reaching the network, and a suite that fails for
external reasons is a suite people learn to ignore.

The world is checked by `scripts/check_ground_truth.py`, live, where a failure means something.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import FIXTURE_ANSWERS

from bench import spec, tasks
from bench.api import Api

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


@pytest.mark.parametrize("task", tasks.TASKS, ids=lambda t: t.id)
def test_the_solver_computes_what_the_api_told_it(task: tasks.Task, api: Api) -> None:
    """Exercises the solver's logic — its hops, filters and arithmetic — not the world's data."""
    computed = task.solver(api)
    expected = FIXTURE_ANSWERS[task.id]
    if isinstance(expected, float):
        assert abs(float(computed) - expected) <= max(task.tolerance, 0.01)
    else:
        assert computed == expected


@pytest.mark.parametrize("task", tasks.TASKS, ids=lambda t: t.id)
def test_a_solver_makes_only_the_calls_a_correct_agent_would(task: tasks.Task, api: Api) -> None:
    # conftest raises on any request it has no fixture for, so reaching for something unexpected
    # fails loudly rather than silently going to the network.
    task.solver(api)
    assert api.calls > 0


@pytest.mark.parametrize("task", tasks.TASKS, ids=lambda t: t.id)
def test_grading_uses_the_value_solved_this_run(task: tasks.Task, api: Api) -> None:
    """The live answer wins over the recorded reference — that is the whole point of solving live."""
    live = task.solver(api)
    assert task.check(str(live), live)
    # And the stale reference is not silently accepted when the live value disagrees.
    if str(live) != str(task.answer):
        assert not task.check(str(task.answer), live)


@pytest.mark.parametrize("task", tasks.TASKS, ids=lambda t: t.id)
def test_the_reference_still_grades_when_nothing_was_solved(task: tasks.Task) -> None:
    assert task.check(str(task.answer))


def test_check_rejects_wrong_answers() -> None:
    assert not tasks.by_id("t2-acre-headcount").check("There are 9 deputies.")
    assert not tasks.by_id("t5-session-party-no-votes").check("PSD")
    assert not tasks.by_id("t3-march-expenses").check("R$ 46,960.45")


def test_check_tolerates_how_a_model_writes_numbers() -> None:
    task = tasks.by_id("t3-march-expenses")
    for phrasing in ("46960.46", "R$ 46,960.46", "46.960,46 reais", "The total is 46960.46."):
        assert task.check(phrasing), phrasing


def test_check_is_insensitive_to_case_and_accents() -> None:
    task = tasks.by_id("t1-civil-name")
    assert task.check("josé abílio silva de santana")


def test_difficulty_is_a_strict_gradient() -> None:
    assert [t.difficulty for t in tasks.TASKS] == [1, 2, 3, 4, 5]
    assert len({t.id for t in tasks.TASKS}) == len(tasks.TASKS)


def test_every_required_operation_exists(registry: spec.Registry) -> None:
    for name in tasks.required_operations():
        registry.by_name(name)  # raises if the suite depends on something the API does not expose


def test_sampling_can_still_preserve_the_suite(registry: spec.Registry) -> None:
    """N-scaling must not quietly make a task impossible."""
    keep = tasks.required_operations()
    assert len(keep) == 6, "the suite's footprint is the floor for any N level used with tasks"

    kept = registry.sample(10, keep=keep, seed=0)
    assert set(keep) <= {op.name for op in kept}

    with pytest.raises(ValueError):
        registry.sample(5, keep=keep, seed=0)
