/**
 * The two artifacts must expose the same operations and the same parameters.
 *
 * This is the last place the arms could drift apart without anyone noticing: the schemas could match
 * perfectly and the comparison still be spoiled if one artifact quietly dropped a capability. These
 * tests compare the surfaces operation by operation and parameter by parameter.
 */

import { expect, test } from "bun:test";
import { applyFilter } from "../filter.ts";
import { byName, load, type Registry } from "../spec.ts";
import { commandHelp, fullHelp, rootHelp } from "./cli.ts";
import { inputSchema, toolDefinitions } from "./mcp-server.ts";

const registry: Registry = await load("data/specs/camara-dados-abertos-v2.json");

test("every operation reaches both artifacts", () => {
  const fromMcp = new Set(toolDefinitions(registry, false).map((t) => t.name as string));
  const help = rootHelp(registry);
  expect(fromMcp).toEqual(new Set(registry.operations.map((op) => op.name)));
  for (const op of registry.operations) expect(help).toContain(op.name);
});

test("every parameter reaches both artifacts", () => {
  for (const op of registry.operations) {
    const schema = inputSchema(op, false) as { properties: Record<string, unknown> };
    expect(new Set(Object.keys(schema.properties))).toEqual(new Set(op.params.map((p) => p.name)));

    const help = commandHelp(registry, op.name);
    for (const param of op.params) {
      if (param.location === "path") expect(help).toContain(`<${param.name}>`);
      else expect(help).toContain(`--${param.name}`);
    }
  }
});

test("required parameters agree", () => {
  for (const op of registry.operations) {
    const schema = inputSchema(op, false) as { required?: string[] };
    const required = new Set(schema.required ?? []);
    expect(required).toEqual(new Set(op.params.filter((p) => p.required).map((p) => p.name)));
  }
});

test("the help is commander's, not ours", () => {
  // If this ever stops being true, the caveat about a hand-tuned help returns with it.
  expect(rootHelp(registry)).toContain("Usage: api");
  expect(commandHelp(registry, "list_deputados")).toContain("Options:");
  expect(fullHelp(registry).startsWith(rootHelp(registry))).toBe(true);
});

test("filtering is opt-in and paid for on every tool", () => {
  const plain = inputSchema(byName(registry, "list_votacoes_votos"), false) as {
    properties: Record<string, unknown>;
  };
  const filtered = inputSchema(byName(registry, "list_votacoes_votos"), true) as {
    properties: Record<string, unknown>;
  };
  expect("filter" in plain.properties).toBe(false);
  expect("filter" in filtered.properties).toBe(true);
  expect(JSON.stringify(filtered).length).toBeGreaterThan(JSON.stringify(plain).length);
});

test("jq runs, and a bad expression comes back readable", async () => {
  const body = { dados: [{ v: "Sim" }, { v: "Não" }, { v: "Sim" }] };
  expect(await applyFilter(body, '[.dados[]|select(.v=="Sim")]|length')).toBe("2");
  const broken = await applyFilter(body, "this is not jq");
  expect(broken.startsWith("jq: error")).toBe(true);
  expect(broken.length).toBeLessThan(500);
});
