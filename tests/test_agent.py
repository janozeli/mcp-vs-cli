"""The loop is what produces every published number, so it is tested against a scripted provider.

No network, no key: a stub client hands back completions written here, which makes it possible to
assert the things that actually matter — that deferred loading really defers, that an unrecorded call
aborts instead of being invented, and that a busy provider is retried rather than scored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from bench import agent, spec, tasks
from bench.replay import Cassette

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"
CASSETTES = ROOT / "data" / "cassettes"


class _Completion:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return self._payload


class StubClient:
    """Replays a script of completions and remembers the requests it was given."""

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = list(script)
        self.requests: list[dict[str, Any]] = []
        outer = self

        class _Completions:
            def create(self, **kwargs: Any) -> _Completion:
                kwargs.pop("extra_body", None)
                outer.requests.append(kwargs)
                if not outer.script:
                    raise AssertionError("the loop asked for more turns than the script provides")
                return _Completion(outer.script.pop(0))

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _text(content: str) -> dict[str, Any]:
    return {
        "model": "stub",
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10},
    }


def _tool_call(name: str, arguments: str, call_id: str = "call-1") -> dict[str, Any]:
    return {
        "model": "stub",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 500, "completion_tokens": 20},
    }


def _error(message: str) -> dict[str, Any]:
    return {"model": None, "choices": None, "error": {"message": message, "code": 502}, "usage": None}


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


@pytest.fixture
def cassette() -> Cassette:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"trials must replay, but tried to reach {request.url}")

    return Cassette(
        CASSETTES,
        base_url="https://dadosabertos.camara.leg.br/api/v2",
        mode="replay",
        client=httpx.Client(transport=httpx.MockTransport(refuse)),
    )


def _run(task_id: str, script: list[dict[str, Any]], registry: spec.Registry, cassette: Cassette, **kw: Any):
    client = StubClient(script)
    trial = agent.run_trial(
        tasks.by_id(task_id),
        registry=registry,
        cassette=cassette,
        client=client,  # type: ignore[arg-type]
        **kw,
    )
    return trial, client


def test_a_correct_answer_is_scored(registry: spec.Registry, cassette: Cassette) -> None:
    trial, _ = _run(
        "t1-civil-name",
        [
            _tool_call("camara__get_deputados", '{"id": 204554}'),
            _text("JOSE ABILIO SILVA DE SANTANA"),
        ],
        registry,
        cassette,
        fmt="mcp",
        disclosure="eager",
    )
    assert trial.success
    assert trial.turns == 2
    assert trial.tool_calls == 1
    assert trial.prompt_tokens == 600
    assert trial.peak_context == 500, "peak is the largest single prompt, not their sum"


def test_a_wrong_answer_is_not(registry: spec.Registry, cassette: Cassette) -> None:
    trial, _ = _run(
        "t1-civil-name", [_text("Someone Else")], registry, cassette, fmt="mcp", disclosure="eager"
    )
    assert not trial.success


def test_eager_sends_every_schema_on_the_first_turn(registry: spec.Registry, cassette: Cassette) -> None:
    _, client = _run("t1-civil-name", [_text("x")], registry, cassette, fmt="mcp", disclosure="eager")
    assert len(client.requests[0]["tools"]) == len(registry)


def test_deferred_starts_with_one_tool_and_grows(registry: spec.Registry, cassette: Cassette) -> None:
    trial, client = _run(
        "t1-civil-name",
        [
            _tool_call("tool_search", '{"query": "deputados"}'),
            _tool_call("tool_search", '{"query": "select:camara__get_deputados"}', call_id="call-2"),
            _tool_call("camara__get_deputados", '{"id": 204554}', call_id="call-3"),
            _text("JOSE ABILIO SILVA DE SANTANA"),
        ],
        registry,
        cassette,
        fmt="mcp",
        disclosure="lazy",
    )
    assert trial.success
    first, after_browse, after_select = (client.requests[i]["tools"] for i in (0, 1, 2))
    assert [t["function"]["name"] for t in first] == ["tool_search"]
    # Browsing must not load anything: that is what makes it cheaper than reading every schema.
    assert [t["function"]["name"] for t in after_browse] == ["tool_search"]
    assert any(t["function"]["name"] == "camara__get_deputados" for t in after_select)


def test_browsing_returns_names_and_selecting_returns_schemas(registry: spec.Registry) -> None:
    loaded: set[str] = set()
    browsed, names = agent._search(registry, "despesas", loaded)
    assert not names and not loaded, "browsing loads nothing"
    assert "camara__list_deputados_despesas" in browsed
    assert '"parameters"' not in browsed, "browsing must not pay for full schemas"

    selected, names = agent._search(registry, "select:camara__list_deputados_despesas", loaded)
    assert names == ["list_deputados_despesas"]
    assert loaded == {"list_deputados_despesas"}
    assert '"parameters"' in selected


def test_selecting_an_unknown_tool_says_so(registry: spec.Registry) -> None:
    text, names = agent._search(registry, "select:camara__list_senadores", set())
    assert not names
    assert "No such tools" in text


@pytest.mark.parametrize("disclosure", ["indexed", "lazy"])
def test_a_deferred_cell_refuses_a_tool_it_never_loaded(
    registry: spec.Registry, cassette: Cassette, disclosure: str
) -> None:
    """Otherwise the cell is 'eager without paying for the schemas', which nobody can deploy.

    The indexed cell shows the model a list of names. Left unguarded, the model reads a name and
    calls it straight away, skipping the very round trip this cell exists to measure.
    """
    trial, _ = _run(
        "t1-civil-name",
        [
            _tool_call("camara__get_deputados", '{"id": 204554}'),
            _tool_call("tool_search", '{"query": "select:camara__get_deputados"}', call_id="c2"),
            _tool_call("camara__get_deputados", '{"id": 204554}', call_id="c3"),
            _text("JOSE ABILIO SILVA DE SANTANA"),
        ],
        registry,
        cassette,
        fmt="mcp",
        disclosure=disclosure,
        trace_dir=None,
    )
    assert trial.success, "the model should be able to recover by loading the tool"
    assert trial.turns == 4, "the unloaded call costs a turn rather than being served"


def test_an_eager_cell_needs_no_loading(registry: spec.Registry, cassette: Cassette) -> None:
    trial, _ = _run(
        "t1-civil-name",
        [
            _tool_call("camara__get_deputados", '{"id": 204554}'),
            _text("JOSE ABILIO SILVA DE SANTANA"),
        ],
        registry,
        cassette,
        fmt="mcp",
        disclosure="eager",
    )
    assert trial.success and trial.turns == 2


def test_the_cli_format_never_sends_more_than_one_tool(registry: spec.Registry, cassette: Cassette) -> None:
    for disclosure in ("eager", "indexed", "lazy"):
        _, client = _run("t1-civil-name", [_text("x")], registry, cassette, fmt="cli", disclosure=disclosure)
        tools = client.requests[0]["tools"]
        assert [t["function"]["name"] for t in tools] == ["run_cli"]


def test_an_unrecorded_call_aborts_rather_than_being_invented(
    registry: spec.Registry, cassette: Cassette
) -> None:
    trial, _ = _run(
        "t1-civil-name",
        [_tool_call("camara__get_deputados", '{"id": 999999999}'), _text("made up")],
        registry,
        cassette,
        fmt="mcp",
        disclosure="eager",
    )
    assert not trial.success
    assert trial.aborted is not None and "cassette miss" in trial.aborted


def test_a_busy_provider_is_retried_not_scored(
    registry: spec.Registry, cassette: Cassette, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "BACKOFF_SECONDS", (0, 0))
    trial, _ = _run(
        "t1-civil-name",
        [
            _error("Upstream error from Nvidia: ResourceExhausted: Worker local total request limit reached"),
            _tool_call("camara__get_deputados", '{"id": 204554}'),
            _text("JOSE ABILIO SILVA DE SANTANA"),
        ],
        registry,
        cassette,
        fmt="mcp",
        disclosure="eager",
    )
    assert trial.success, "a capacity error is noise about the provider, not signal about the arm"


def test_a_permanent_error_is_not_retried(
    registry: spec.Registry, cassette: Cassette, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "BACKOFF_SECONDS", (0, 0))
    trial, client = _run(
        "t1-civil-name", [_error("invalid model")], registry, cassette, fmt="mcp", disclosure="eager"
    )
    assert not trial.success
    assert len(client.requests) == 1
    assert trial.aborted is not None and "invalid model" in trial.aborted


def test_a_looping_agent_is_cut_off(registry: spec.Registry, cassette: Cassette) -> None:
    script = [_tool_call("camara__get_deputados", '{"id": 204554}', call_id=f"c{i}") for i in range(4)]
    trial, _ = _run("t1-civil-name", script, registry, cassette, fmt="mcp", disclosure="eager", max_turns=3)
    assert not trial.success
    assert trial.aborted is not None and "gave up" in trial.aborted


def test_the_trace_records_every_request(registry: spec.Registry, cassette: Cassette, tmp_path: Path) -> None:
    trial, _ = _run(
        "t1-civil-name",
        [_tool_call("camara__get_deputados", '{"id": 204554}'), _text("JOSE ABILIO SILVA DE SANTANA")],
        registry,
        cassette,
        fmt="mcp",
        disclosure="eager",
        trace_dir=tmp_path,
    )
    lines = Path(trial.trace).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 4, "each turn writes its request and its response, plus every tool call"
