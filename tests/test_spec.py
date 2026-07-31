from __future__ import annotations

from pathlib import Path

import pytest

from bench import spec

SPEC = Path(__file__).resolve().parents[1] / "data" / "specs" / "camara-dados-abertos-v2.json"


@pytest.fixture(scope="module")
def registry() -> spec.Registry:
    return spec.load(SPEC)


def test_snapshot_shape(registry: spec.Registry) -> None:
    assert len(registry) == 78
    assert registry.base_url == "https://dadosabertos.camara.leg.br/api/v2"
    assert len(registry.groups()) == 11


def test_operations_are_fully_described(registry: spec.Registry) -> None:
    for op in registry:
        assert op.id and op.method and op.path.startswith("/")
        assert op.group
        for p in op.params:
            assert p.name
            assert p.location in {"query", "path", "header", "cookie"}


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("get", "/deputados", "list_deputados"),
        ("get", "/deputados/{id}", "get_deputados"),
        ("get", "/deputados/{id}/despesas", "list_deputados_despesas"),
        ("get", "/referencias/proposicoes/siglaTipo", "list_referencias_proposicoes_siglatipo"),
        ("post", "/deputados", "create_deputados"),
        ("delete", "/deputados/{id}", "delete_deputados"),
    ],
)
def test_tool_name_derivation(method: str, path: str, expected: str) -> None:
    assert spec.tool_name(method, path) == expected


def test_derived_names_replace_the_specs_own_poor_ones(registry: spec.Registry) -> None:
    # The spec calls these `search`, `listar` and `listar_1` — unusable as tool names, and unusable
    # identically in both arms, which would add noise for no reason.
    assert registry.by_id("search").name == "list_proposicoes"
    assert registry.by_id("listar").name == "list_votacoes"
    assert registry.by_id("listar_1").name == "list_orgaos"


def test_names_are_unique(registry: spec.Registry) -> None:
    names = [op.name for op in registry]
    assert len(set(names)) == len(names)


def test_richest_operation_is_parsed(registry: spec.Registry) -> None:
    op = registry.by_name("list_proposicoes")
    assert op.method == "GET"
    assert op.path == "/proposicoes"
    assert op.id == "search"
    assert len(op.params) == 22  # 23 in the spec, minus the Accept header
    ordem = next(p for p in op.params if p.name == "ordem")
    assert ordem.default == "ASC"
    sigla = next(p for p in op.params if p.name == "siglaTipo")
    assert sigla.is_array


def test_transport_params_are_hidden_from_the_agent(registry: spec.Registry) -> None:
    assert not [p for op in registry for p in op.params if p.location in {"header", "cookie"}]
    faithful = spec.load(SPEC, drop_transport_params=False)
    assert [p for op in faithful for p in op.params if p.location == "header"]


def test_path_rendering(registry: spec.Registry) -> None:
    op = registry.by_name("get_deputados")
    assert op.render_path({"id": 204554}) == "/deputados/204554"
    with pytest.raises(KeyError):
        op.render_path({})


def test_sample_is_deterministic_and_keeps_required_operations(registry: spec.Registry) -> None:
    keep = ["list_deputados", "list_proposicoes"]
    a = registry.sample(20, keep=keep, seed=7)
    b = registry.sample(20, keep=keep, seed=7)
    assert [op.name for op in a] == [op.name for op in b]
    assert len(a) == 20
    assert set(keep) <= {op.name for op in a}
    # ordering follows the full registry, so token counts do not wobble between runs
    full_order = [op.name for op in registry]
    assert [op.name for op in a] == [n for n in full_order if n in {op.name for op in a}]


def test_sample_rejects_impossible_requests(registry: spec.Registry) -> None:
    with pytest.raises(ValueError):
        registry.sample(500)
    with pytest.raises(ValueError):
        registry.sample(1, keep=["list_deputados", "list_proposicoes"])


# The vendored spec happens to use neither $ref parameters nor real enums, so the parser's handling
# of them is pinned against a synthetic document instead. The claim in the README is that any
# OpenAPI 3 document works, not just this one.
SYNTHETIC: dict = {
    "openapi": "3.0.3",
    "info": {"title": "synthetic", "version": "9"},
    "servers": [{"url": "https://example.test/v1/"}],
    "components": {
        "parameters": {
            "Page": {
                "name": "page",
                "in": "query",
                "required": False,
                "description": "Page number.",
                "schema": {"type": "integer", "default": 1},
            }
        }
    },
    "paths": {
        "/widgets/{id}/parts": {
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "integer"}}],
            "get": {
                "operationId": "legacyName",
                "tags": ["Widgets"],
                "summary": "List parts.",
                "parameters": [
                    {"$ref": "#/components/parameters/Page"},
                    {
                        "name": "status",
                        "in": "query",
                        "schema": {"type": "string", "enum": ["open", "closed"]},
                    },
                    {
                        "name": "tags",
                        "in": "query",
                        "schema": {"type": "array", "items": {"type": "string", "enum": ["a", "b"]}},
                    },
                ],
            },
        }
    },
}


def test_synthetic_document_is_normalised() -> None:
    reg = spec.from_openapi(SYNTHETIC)
    assert reg.base_url == "https://example.test/v1"
    op = reg.by_name("list_widgets_parts")
    assert op.id == "legacyName"
    by_name = {p.name: p for p in op.params}
    # the path-level parameter is inherited by the operation
    assert by_name["id"].location == "path" and by_name["id"].required
    # $ref is resolved, default is captured
    assert by_name["page"].type == "integer" and by_name["page"].default == "1"
    assert by_name["status"].enum == ("open", "closed")
    # an array parameter reports its item type, and enums are read through items
    assert by_name["tags"].type == "array[string]" and by_name["tags"].enum == ("a", "b")


def test_non_openapi3_is_rejected() -> None:
    with pytest.raises(ValueError):
        spec.from_openapi({"swagger": "2.0", "paths": {}})
