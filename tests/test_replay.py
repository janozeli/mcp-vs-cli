"""The cassette is what makes two arms comparable, so its failure modes matter more than its API.

Every test here runs offline: recording is exercised against a mock transport, and replay is
exercised against a client that raises if it is touched at all.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bench.replay import Cassette, CassetteMiss, canonical_request, key_for

BASE = "https://api.example.test/v2"


def mock_client(
    handler: httpx.MockTransport | None = None, *, calls: list[str] | None = None
) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(200, json={"dados": [{"id": 1, "nome": "Ada"}], "url": str(request.url)})

    return httpx.Client(transport=handler or httpx.MockTransport(respond))


def exploding_client() -> httpx.Client:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"replay mode must not touch the network, but requested {request.url}")

    return httpx.Client(transport=httpx.MockTransport(refuse))


def test_parameter_order_does_not_change_the_key() -> None:
    a = key_for("GET", "/deputados", {"siglaUf": "SP", "itens": 100})
    b = key_for("GET", "/deputados", {"itens": 100, "siglaUf": "SP"})
    assert a == b


def test_different_calls_get_different_keys() -> None:
    assert key_for("GET", "/deputados", {"siglaUf": "SP"}) != key_for("GET", "/deputados", {"siglaUf": "RJ"})
    assert key_for("GET", "/deputados", None) != key_for("GET", "/proposicoes", None)


def test_values_are_compared_as_text() -> None:
    # An agent may pass 100 or "100" for the same parameter; both are the same call.
    assert key_for("GET", "/x", {"itens": 100}) == key_for("GET", "/x", {"itens": "100"})


def test_canonical_form_is_readable() -> None:
    assert canonical_request("get", "/deputados", {"itens": 2, "siglaUf": "SP"}) == (
        "GET /deputados?itens=2&siglaUf=SP"
    )


def test_record_then_replay_returns_identical_bytes(tmp_path: Path) -> None:
    calls: list[str] = []
    recorder = Cassette(tmp_path, base_url=BASE, mode="record", client=mock_client(calls=calls))
    first = recorder.get("/deputados", {"siglaUf": "SP"})
    assert recorder.recorded == 1
    assert len(calls) == 1

    player = Cassette(tmp_path, base_url=BASE, mode="replay", client=exploding_client())
    second = player.get("/deputados", {"siglaUf": "SP"})
    assert second.body == first.body
    assert second.key == first.key
    assert player.hits == 1
    assert len(calls) == 1, "replay must not have gone to the network"


def test_recording_is_reused_rather_than_refetched(tmp_path: Path) -> None:
    calls: list[str] = []
    recorder = Cassette(tmp_path, base_url=BASE, mode="record", client=mock_client(calls=calls))
    recorder.get("/deputados", {"siglaUf": "SP"})
    recorder.get("/deputados", {"siglaUf": "SP"})
    assert len(calls) == 1
    assert recorder.recorded == 1
    assert recorder.hits == 1


def test_replay_raises_on_a_miss_instead_of_falling_back(tmp_path: Path) -> None:
    player = Cassette(tmp_path, base_url=BASE, mode="replay", client=exploding_client())
    with pytest.raises(CassetteMiss) as excinfo:
        player.get("/proposicoes", {"ano": 2024})
    # The message has to say what was missing, or re-recording becomes guesswork.
    assert "GET /proposicoes?ano=2024" in str(excinfo.value)


def test_two_arms_calling_differently_still_share_one_recording(tmp_path: Path) -> None:
    """The point of the cassette: an MCP call and a CLI invocation of the same operation collide."""
    calls: list[str] = []
    recorder = Cassette(tmp_path, base_url=BASE, mode="record", client=mock_client(calls=calls))
    from_mcp = recorder.get("/deputados", {"siglaUf": "SP", "itens": 10})
    from_cli = recorder.get("/deputados", {"itens": "10", "siglaUf": "SP"})
    assert from_mcp.body == from_cli.body
    assert len(calls) == 1
    assert len(recorder) == 1


def test_stored_document_is_self_describing(tmp_path: Path) -> None:
    import json

    recorder = Cassette(tmp_path, base_url=BASE, mode="record", client=mock_client())
    recorded = recorder.get("/deputados", {"siglaUf": "SP"})
    document = json.loads((tmp_path / f"{recorded.key}.json").read_text(encoding="utf-8"))
    assert document["request"]["canonical"] == "GET /deputados?siglaUf=SP"
    assert document["response"]["status"] == 200
    assert document["recorded_at"].endswith("Z")
