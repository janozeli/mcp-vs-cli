"""The suite grades agents, so it has to be graded first.

Every test replays from the committed cassette and never opens a socket. If the corpus is
re-recorded and the underlying data has moved, these fail — which is the point. A benchmark quietly
grading against a stale answer key is worse than one that does not run.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bench import spec, tasks
from bench.replay import Cassette

ROOT = Path(__file__).resolve().parents[1]
CASSETTES = ROOT / "data" / "cassettes"
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"


@pytest.fixture(scope="module")
def cassette() -> Cassette:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"the suite must grade offline, but tried to reach {request.url}")

    return Cassette(
        CASSETTES,
        base_url="https://dadosabertos.camara.leg.br/api/v2",
        mode="replay",
        client=httpx.Client(transport=httpx.MockTransport(refuse)),
    )


@pytest.mark.parametrize("task", tasks.TASKS, ids=lambda t: t.id)
def test_pinned_answer_matches_the_corpus(task: tasks.Task, cassette: Cassette) -> None:
    computed = task.solver(cassette)
    if task.is_numeric:
        assert abs(float(computed) - float(task.answer)) <= task.tolerance
    else:
        assert str(computed) == str(task.answer)


@pytest.mark.parametrize("task", tasks.TASKS, ids=lambda t: t.id)
def test_check_accepts_the_right_answer(task: tasks.Task) -> None:
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


def test_every_required_operation_exists() -> None:
    registry = spec.load(SPEC)
    for name in tasks.required_operations():
        registry.by_name(name)  # raises if the suite depends on something the API does not expose


def test_sampling_can_still_preserve_the_suite() -> None:
    """N-scaling must not quietly make a task impossible."""
    registry = spec.load(SPEC)
    keep = tasks.required_operations()
    assert len(keep) == 6, "the suite's footprint is the floor for any N level used with tasks"

    kept = registry.sample(10, keep=keep, seed=0)
    assert set(keep) <= {op.name for op in kept}

    with pytest.raises(ValueError):
        registry.sample(5, keep=keep, seed=0)


def test_solvers_only_need_recorded_calls(cassette: Cassette) -> None:
    # A solver reaching for something unrecorded would raise CassetteMiss; running them all is the
    # assertion that the committed corpus is complete for the happy path.
    for task in tasks.TASKS:
        task.solver(cassette)
