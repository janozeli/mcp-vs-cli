import { describe, expect, test } from "bun:test";
import {
  byId,
  byName,
  check,
  fromOpenApi,
  groups,
  isArrayParam,
  load,
  normalise,
  type Registry,
  renderPath,
  sample,
  toolName,
} from "./spec.ts";

const SPEC = "data/specs/camara-dados-abertos-v2.json";
const registry: Registry = await load(SPEC);

test("the vendored snapshot has the shape the experiment assumes", () => {
  expect(registry.operations).toHaveLength(78);
  expect(registry.baseUrl).toBe("https://dadosabertos.camara.leg.br/api/v2");
  expect(groups(registry).size).toBe(11);
});

test("every operation is fully described", () => {
  for (const op of registry.operations) {
    expect(op.id).toBeTruthy();
    expect(op.method).toBeTruthy();
    expect(op.path.startsWith("/")).toBe(true);
    expect(op.group).toBeTruthy();
    for (const param of op.params) {
      expect(param.name).toBeTruthy();
      expect(["query", "path", "header", "cookie"]).toContain(param.location);
    }
  }
});

describe("tool names are derived, never taken from the spec", () => {
  const cases: [string, string, string][] = [
    ["get", "/deputados", "list_deputados"],
    ["get", "/deputados/{id}", "get_deputados"],
    ["get", "/deputados/{id}/despesas", "list_deputados_despesas"],
    ["get", "/referencias/proposicoes/siglaTipo", "list_referencias_proposicoes_siglatipo"],
    ["post", "/deputados", "create_deputados"],
    ["delete", "/deputados/{id}", "delete_deputados"],
  ];
  for (const [method, path, expected] of cases) {
    test(`${method.toUpperCase()} ${path} → ${expected}`, () => {
      expect(toolName(method, path)).toBe(expected);
    });
  }

  test("they replace the spec's own unusable ones", () => {
    // The spec calls these `search`, `listar` and `listar_1` — unusable as tool names, and unusable
    // identically in every arm, which would add noise for no reason.
    expect(byId(registry, "search").name).toBe("list_proposicoes");
    expect(byId(registry, "listar").name).toBe("list_votacoes");
    expect(byId(registry, "listar_1").name).toBe("list_orgaos");
  });

  test("they are unique", () => {
    const names = registry.operations.map((op) => op.name);
    expect(new Set(names).size).toBe(names.length);
  });
});

test("the richest operation is parsed", () => {
  const op = byName(registry, "list_proposicoes");
  expect(op.method).toBe("GET");
  expect(op.path).toBe("/proposicoes");
  expect(op.id).toBe("search");
  expect(op.params).toHaveLength(22); // 23 in the spec, minus the Accept header
  expect(op.params.find((p) => p.name === "ordem")?.default).toBe("ASC");
  const sigla = op.params.find((p) => p.name === "siglaTipo");
  expect(sigla && isArrayParam(sigla)).toBe(true);
});

test("transport parameters are hidden from the agent", async () => {
  const exposed = registry.operations.flatMap((op) => op.params);
  expect(exposed.some((p) => p.location === "header" || p.location === "cookie")).toBe(false);

  const faithful = await load(SPEC, { dropTransportParams: false });
  expect(faithful.operations.flatMap((op) => op.params).some((p) => p.location === "header")).toBe(true);
});

test("path rendering substitutes and complains", () => {
  const op = byName(registry, "get_deputados");
  expect(renderPath(op, { id: 204554 })).toBe("/deputados/204554");
  expect(() => renderPath(op, {})).toThrow();
});

test("sampling is deterministic and keeps what the tasks need", () => {
  const keep = ["list_deputados", "list_proposicoes"];
  const a = sample(registry, 20, { keep, seed: 7 });
  const b = sample(registry, 20, { keep, seed: 7 });
  expect(a.operations.map((op) => op.name)).toEqual(b.operations.map((op) => op.name));
  expect(a.operations).toHaveLength(20);
  for (const name of keep) expect(a.operations.some((op) => op.name === name)).toBe(true);

  // ordering follows the full registry, so token counts do not wobble between runs
  const chosen = new Set(a.operations.map((op) => op.name));
  const inFullOrder = registry.operations.filter((op) => chosen.has(op.name)).map((op) => op.name);
  expect(a.operations.map((op) => op.name)).toEqual(inFullOrder);
});

test("sampling refuses impossible requests", () => {
  expect(() => sample(registry, 500)).toThrow();
  expect(() => sample(registry, 1, { keep: ["list_deputados", "list_proposicoes"] })).toThrow();
});

// The vendored spec happens to use neither $ref parameters nor real enums, so the parser's handling
// of them is pinned against a synthetic document instead. The claim is that any OpenAPI 3 document
// works, not just this one.
const SYNTHETIC = {
  openapi: "3.0.3",
  info: { title: "synthetic", version: "9" },
  servers: [{ url: "https://example.test/v1/" }],
  components: {
    parameters: {
      Page: {
        name: "page",
        in: "query",
        required: false,
        description: "Page number.",
        schema: { type: "integer", default: 1 },
      },
    },
  },
  paths: {
    "/widgets/{id}/parts": {
      parameters: [{ name: "id", in: "path", required: true, schema: { type: "integer" } }],
      get: {
        operationId: "legacyName",
        tags: ["Widgets"],
        summary: "List parts.",
        parameters: [
          { $ref: "#/components/parameters/Page" },
          { name: "status", in: "query", schema: { type: "string", enum: ["open", "closed"] } },
          {
            name: "tags",
            in: "query",
            schema: { type: "array", items: { type: "string", enum: ["a", "b"] } },
          },
        ],
      },
    },
  },
};

test("a synthetic document is normalised", async () => {
  const reg = await normalise(SYNTHETIC);
  expect(reg.baseUrl).toBe("https://example.test/v1");
  const op = byName(reg, "list_widgets_parts");
  expect(op.id).toBe("legacyName");
  const params = new Map(op.params.map((p) => [p.name, p]));

  // the path-level parameter is inherited by the operation
  expect(params.get("id")?.location).toBe("path");
  expect(params.get("id")?.required).toBe(true);
  // $ref is resolved, default is captured
  expect(params.get("page")?.type).toBe("integer");
  expect(params.get("page")?.default).toBe("1");
  expect(params.get("status")?.enum).toEqual(["open", "closed"]);
  // an array parameter reports its item type, and enums are read through items
  expect(params.get("tags")?.type).toBe("array[string]");
  expect(params.get("tags")?.enum).toEqual(["a", "b"]);
});

test("a non-OpenAPI-3 document is rejected", () => {
  expect(() => fromOpenApi({ swagger: "2.0", paths: {} })).toThrow();
});

test("the vendored spec is reported as invalid, and used anyway", async () => {
  // A fact about the subject rather than a defect here: the published document carries one enum
  // violation. Refusing it would be refusing the only API the benchmark has.
  const report = await check(SPEC);
  expect(report.valid).toBe(false);
  expect(report.errors.length).toBeGreaterThan(0);
  expect(registry.operations).toHaveLength(78);
});
