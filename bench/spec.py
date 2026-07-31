"""Normalise an OpenAPI 3 document into the operation registry that every arm is generated from.

The registry is the single source of truth of the experiment. The MCP arm and the CLI arm are both
emitted from it, so a behavioural difference between arms is always a difference of *exposure* and
never of capability. Nothing here knows about MCP, about CLIs, or about token counting.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")

_WRITE_VERBS = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "delete"}


def tool_name(method: str, path: str) -> str:
    """Derive a stable, readable name for an operation from its method and route.

    Real specs cannot be trusted to name things usefully: the vendored one calls two unrelated
    listings `listar` and `listar_1`, and a bare `search`. Those names would handicap the agent, so
    both arms get names from this transform instead — mechanically, identically, and without
    touching the spec. Only the verb is imposed; the resource nouns stay exactly as the API spells
    them, because they are domain vocabulary rather than something we are free to translate.
    """
    segments = [s for s in path.strip("/").split("/") if s]
    concrete = [s for s in segments if not (s.startswith("{") and s.endswith("}"))]
    if method.upper() == "GET":
        verb = "get" if segments and segments[-1].startswith("{") else "list"
    else:
        verb = _WRITE_VERBS.get(method.upper(), method.lower())
    noun = "_".join(re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") for s in concrete)
    return f"{verb}_{noun}" if noun else verb


@dataclass(frozen=True, slots=True)
class Param:
    """A single input to an operation, described independently of how it is later exposed."""

    name: str
    location: str
    required: bool
    type: str
    description: str
    enum: tuple[str, ...] = ()
    default: str | None = None

    @property
    def is_array(self) -> bool:
        return self.type.startswith("array")


@dataclass(frozen=True, slots=True)
class Operation:
    """One callable capability: an HTTP operation stripped of its transport details."""

    name: str
    """Derived by `tool_name`. This is what the agent sees, in both arms."""

    id: str
    """The spec's own `operationId`, kept only so findings can be traced back to the source."""

    method: str
    path: str
    group: str
    summary: str
    description: str
    params: tuple[Param, ...]

    @property
    def required_params(self) -> tuple[Param, ...]:
        return tuple(p for p in self.params if p.required)

    def render_path(self, values: Mapping[str, Any]) -> str:
        """Substitute path parameters, leaving query parameters to the caller."""
        path = self.path
        for p in self.params:
            if p.location == "path":
                if p.name not in values:
                    raise KeyError(f"{self.id}: missing path parameter {p.name!r}")
                path = path.replace("{" + p.name + "}", str(values[p.name]))
        return path


@dataclass(frozen=True, slots=True)
class Registry:
    """An ordered, immutable set of operations plus the metadata needed to call them."""

    title: str
    version: str
    base_url: str
    operations: tuple[Operation, ...]

    def __len__(self) -> int:
        return len(self.operations)

    def __iter__(self) -> Iterator[Operation]:
        return iter(self.operations)

    def by_name(self, name: str) -> Operation:
        for op in self.operations:
            if op.name == name:
                return op
        raise KeyError(f"unknown operation: {name!r}")

    def by_id(self, operation_id: str) -> Operation:
        """Look an operation up by the spec's original `operationId`."""
        for op in self.operations:
            if op.id == operation_id:
                return op
        raise KeyError(f"unknown operationId: {operation_id!r}")

    def groups(self) -> dict[str, tuple[Operation, ...]]:
        """Operations bucketed by their OpenAPI tag.

        Groups stand in for separate MCP servers: connecting six servers is the situation the
        context cost of MCP is usually complained about, and tags are the spec's own partition.
        """
        out: dict[str, list[Operation]] = {}
        for op in self.operations:
            out.setdefault(op.group, []).append(op)
        return {group: tuple(ops) for group, ops in sorted(out.items())}

    def sample(self, n: int, *, keep: Sequence[str] = (), seed: int = 0) -> Registry:
        """Deterministically narrow the registry to `n` operations for the N-scaling axis.

        Operations named in `keep` are always included — the tasks have to stay solvable as N
        shrinks, otherwise a small-N arm looks efficient only because it was handed an impossible
        job. The remainder is drawn with a seeded RNG, and the result keeps the registry's original
        ordering so token counts do not wobble between runs.
        """
        if n > len(self.operations):
            raise ValueError(f"cannot sample {n} of {len(self.operations)} operations")
        kept = [self.by_name(name) for name in keep]
        if len(kept) > n:
            raise ValueError(f"keep= names {len(kept)} operations, more than n={n}")
        kept_names = {op.name for op in kept}
        pool = sorted((op for op in self.operations if op.name not in kept_names), key=lambda op: op.name)
        drawn = random.Random(seed).sample(pool, n - len(kept))
        chosen = kept_names | {op.name for op in drawn}
        return Registry(
            title=self.title,
            version=self.version,
            base_url=self.base_url,
            operations=tuple(op for op in self.operations if op.name in chosen),
        )


def _resolve(node: Any, doc: Mapping[str, Any]) -> Any:
    """Follow a local `$ref` one hop. Remote refs are out of scope and raise."""
    if not isinstance(node, dict) or "$ref" not in node:
        return node
    ref = node["$ref"]
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref: {ref!r}")
    target: Any = doc
    for part in ref[2:].split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    return _resolve(target, doc)


def _param_type(schema: Mapping[str, Any], doc: Mapping[str, Any]) -> str:
    kind = schema.get("type", "string")
    if kind == "array":
        items = _resolve(schema.get("items", {}), doc)
        return f"array[{items.get('type', 'string')}]"
    return str(kind)


def _param_enum(schema: Mapping[str, Any], doc: Mapping[str, Any]) -> tuple[str, ...]:
    if "enum" in schema:
        return tuple(str(v) for v in schema["enum"])
    if schema.get("type") == "array":
        items = _resolve(schema.get("items", {}), doc)
        if "enum" in items:
            return tuple(str(v) for v in items["enum"])
    return ()


def _params(
    operation: Mapping[str, Any], doc: Mapping[str, Any], *, drop_transport_params: bool
) -> tuple[Param, ...]:
    params: list[Param] = []
    for raw in operation.get("parameters", []):
        p = _resolve(raw, doc)
        location = str(p.get("in", "query"))
        if drop_transport_params and location in {"header", "cookie"}:
            continue
        schema = _resolve(p.get("schema", {}), doc)
        default = schema.get("default")
        params.append(
            Param(
                name=str(p["name"]),
                location=location,
                required=bool(p.get("required", False)),
                type=_param_type(schema, doc),
                description=str(p.get("description", "")).strip(),
                enum=_param_enum(schema, doc),
                default=None if default is None else str(default),
            )
        )
    return tuple(params)


def from_openapi(
    doc: Mapping[str, Any], *, base_url: str | None = None, drop_transport_params: bool = True
) -> Registry:
    """Build a `Registry` from a parsed OpenAPI 3 document.

    `drop_transport_params` hides header and cookie parameters. The vendored spec declares an
    `Accept` header on all 78 operations, and exposing it would let the agent ask for XML and break
    response parsing for reasons that have nothing to do with the comparison. The harness pins those
    headers instead. The filter runs here, once, so both arms are guaranteed to inherit it.
    """
    version = str(doc.get("openapi", ""))
    if not version.startswith("3."):
        raise ValueError(f"expected OpenAPI 3.x, got {version!r}")

    servers = doc.get("servers") or [{}]
    resolved_base = base_url or str(servers[0].get("url", "")).rstrip("/")

    operations: list[Operation] = []
    for path, item in doc.get("paths", {}).items():
        shared = item.get("parameters", [])
        for method in HTTP_METHODS:
            if method not in item:
                continue
            op = dict(item[method])
            op["parameters"] = [*shared, *op.get("parameters", [])]
            tags = op.get("tags") or ["default"]
            operations.append(
                Operation(
                    name=tool_name(method, str(path)),
                    id=str(op.get("operationId") or f"{method}_{path}"),
                    method=method.upper(),
                    path=str(path),
                    group=str(tags[0]),
                    summary=str(op.get("summary", "")).strip(),
                    description=str(op.get("description", "")).strip(),
                    params=_params(op, doc, drop_transport_params=drop_transport_params),
                )
            )

    names = [op.name for op in operations]
    if len(set(names)) != len(names):
        clashes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"derived tool names are not unique: {clashes}")

    info = doc.get("info", {})
    return Registry(
        title=str(info.get("title", "api")),
        version=str(info.get("version", "")),
        base_url=resolved_base,
        operations=tuple(operations),
    )


def load(path: Path | str, *, base_url: str | None = None, drop_transport_params: bool = True) -> Registry:
    """Load a vendored OpenAPI document from disk."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return from_openapi(doc, base_url=base_url, drop_transport_params=drop_transport_params)
