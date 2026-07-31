"""A hand-written stand-in for the API, so the suite can test code without storing anyone's data.

Every payload here was authored for the test that needs it. Nothing was recorded from the live
service and nothing is reused between runs — which is the point: a fixture is a stub, a corpus is a
cache, and this project keeps only the first.

The values are deliberately *not* the real ones. A test that asserted the real answer would be
asserting the world, and the world is checked by `scripts/check_ground_truth.py`, live, where a
failure means something real rather than a stale file.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from bench.api import Api, canonical_request

BASE = "https://api.example.test/v2"


def _deputy(identifier: int, name: str, uf: str, party: str) -> dict[str, Any]:
    return {"id": identifier, "nome": name, "siglaUf": uf, "siglaPartido": party}


def _vote(name: str, uf: str, party: str, choice: str) -> dict[str, Any]:
    return {"tipoVoto": choice, "deputado_": {"nome": name, "siglaUf": uf, "siglaPartido": party}}


# path?sorted-query  ->  (status, body)
ROUTES: dict[str, tuple[int, Any]] = {
    "GET /deputados/204554": (
        200,
        {"dados": {"id": 204554, "nomeCivil": "TESTE DA SILVA SANTOS", "ultimoStatus": {"nome": "Teste"}}},
    ),
    "GET /deputados?itens=100&siglaUf=AC": (
        200,
        {
            "dados": [
                _deputy(1, "Alpha", "AC", "PA"),
                _deputy(2, "Bravo", "AC", "PB"),
                _deputy(3, "Charlie", "AC", "PA"),
            ],
            "links": [{"rel": "self", "href": f"{BASE}/deputados"}],
        },
    ),
    "GET /deputados?siglaUf=AC": (200, {"dados": [_deputy(1, "Alpha", "AC", "PA")]}),
    "GET /deputados?nome=Socorro Neri&siglaUf=AC": (
        200,
        {"dados": [_deputy(104552, "Socorro Neri", "AC", "PA")]},
    ),
    "GET /deputados/104552/despesas?ano=2024&itens=100&mes=3": (
        200,
        {
            "dados": [
                {"tipoDespesa": "A", "valorLiquido": 60.25},
                {"tipoDespesa": "B", "valorLiquido": 40.25},
            ]
        },
    ),
    "GET /deputados/104552/despesas?ano=2024&mes=3": (
        200,
        {"dados": [{"tipoDespesa": "A", "valorLiquido": 60.25}]},
    ),
    "GET /votacoes/2400758-37": (200, {"dados": {"id": "2400758-37", "idEvento": 72248}}),
    "GET /votacoes/2400758-37/votos": (
        200,
        {
            "dados": [
                _vote("Alpha", "SP", "PA", "Sim"),
                _vote("Bravo", "SP", "PB", "Sim"),
                _vote("Charlie", "RJ", "PA", "Sim"),
                _vote("Delta", "SP", "PA", "Não"),
                _vote("Echo", "MG", "PB", "Não"),
                _vote("Foxtrot", "MG", "PA", "Não"),
            ]
        },
    ),
    # The real service rejects `itens` here with a 400 that names the offending parameter, and
    # recovering from it is half of what one task measures. Authored to behave the same way.
    "GET /votacoes/2400758-37/votos?itens=600": (
        400,
        {
            "status": 400,
            "title": "Requisição inválida",
            "detail": "Parâmetro(s) inválido(s).",
            "instance": "itens",
        },
    ),
    "GET /eventos/72248/votacoes": (
        200,
        {"dados": [{"id": "2400758-37"}, {"id": "2401227-50"}]},
    ),
    "GET /votacoes/2401227-50/votos": (200, {"dados": []}),
}

# What the solvers should produce against the payloads above. Kept next to them so a drifting
# fixture and a drifting solver cannot both go unnoticed.
FIXTURE_ANSWERS = {
    "t1-civil-name": "TESTE DA SILVA SANTOS",
    "t2-acre-headcount": 3,
    "t3-march-expenses": 100.50,
    "t4-sao-paulo-yes-votes": 2,
    "t5-session-party-no-votes": "PA",
}


BASE_PATH = urlsplit(BASE).path


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.startswith(BASE_PATH):
        path = path[len(BASE_PATH) :] or "/"
    params = dict(request.url.params)
    key = canonical_request("GET", path, params)
    if key not in ROUTES:
        raise AssertionError(f"no fixture authored for {key!r}; add one to tests/conftest.py")
    status, body = ROUTES[key]
    return httpx.Response(status, json=body)


@pytest.fixture
def api() -> Api:
    """A live-looking client that never leaves the process."""
    return Api(BASE, client=httpx.Client(transport=httpx.MockTransport(_handler)))
