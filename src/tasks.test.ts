/**
 * The suite grades agents, so it has to be graded first.
 *
 * These tests check the grader against invented values, and the solvers against a hand-written stub
 * of the API. They deliberately do not check whether the real answers are still the real answers:
 * that is a question about the world, it can only be answered by reaching the network, and a suite
 * that fails for external reasons is a suite people learn to ignore.
 *
 * The world is checked by `src/scripts/check-ground-truth.ts`, live, where a failure means something.
 */

import { expect, test } from "bun:test";
import type { Api } from "./api.ts";
import { byName, load, sample } from "./spec.ts";
import { byId, check, numbersIn, requiredOperations, TASKS } from "./tasks.ts";

/**
 * A hand-written stand-in for the API. Every payload was authored for the test that needs it;
 * nothing was recorded from the live service. The values are deliberately *not* the real ones — a
 * test asserting the real answer would be asserting the world.
 */
const ROUTES: Record<string, unknown> = {
  "/deputados/204554": { dados: { id: 204554, nomeCivil: "TESTE DA SILVA SANTOS" } },
  "/deputados?itens=100&siglaUf=AC": { dados: [{ id: 1 }, { id: 2 }, { id: 3 }] },
  "/deputados?nome=Socorro Neri&siglaUf=AC": { dados: [{ id: 104552 }] },
  "/deputados/104552/despesas?ano=2024&itens=100&mes=3": {
    dados: [{ valorLiquido: 60.25 }, { valorLiquido: 40.25 }],
  },
  "/votacoes/2400758-37": { dados: { id: "2400758-37", idEvento: 72248 } },
  "/votacoes/2400758-37/votos": {
    dados: [
      { tipoVoto: "Sim", deputado_: { siglaUf: "SP", siglaPartido: "PA" } },
      { tipoVoto: "Sim", deputado_: { siglaUf: "SP", siglaPartido: "PB" } },
      { tipoVoto: "Sim", deputado_: { siglaUf: "RJ", siglaPartido: "PA" } },
      { tipoVoto: "Não", deputado_: { siglaUf: "SP", siglaPartido: "PA" } },
      { tipoVoto: "Não", deputado_: { siglaUf: "MG", siglaPartido: "PB" } },
      { tipoVoto: "Não", deputado_: { siglaUf: "MG", siglaPartido: "PA" } },
    ],
  },
  "/eventos/72248/votacoes": { dados: [{ id: "2400758-37" }, { id: "2401227-50" }] },
  "/votacoes/2401227-50/votos": { dados: [] },
};

/** What each solver should produce against the payloads above. */
const FIXTURE_ANSWERS: Record<string, string | number> = {
  "t1-civil-name": "TESTE DA SILVA SANTOS",
  "t2-acre-headcount": 3,
  "t3-march-expenses": 100.5,
  "t4-sao-paulo-yes-votes": 2,
  "t5-session-party-no-votes": "PA",
};

function stubApi(): Api {
  const calls: string[] = [];
  return {
    baseUrl: "https://api.example.test/v2",
    get calls() {
      return calls.length;
    },
    async get(path: string, params: Record<string, unknown> = {}) {
      const query = Object.entries(params)
        .map(([k, v]) => [String(k), String(v)] as const)
        .sort(([a], [b]) => (a < b ? -1 : 1))
        .map(([k, v]) => `${k}=${v}`)
        .join("&");
      const key = query ? `${path}?${query}` : path;
      calls.push(key);
      const body = ROUTES[key];
      if (body === undefined) throw new Error(`no fixture authored for ${key}`);
      return { status: 200, body, url: key, ok: true };
    },
  } as unknown as Api;
}

for (const task of TASKS) {
  test(`${task.id}: the solver computes what the API told it`, async () => {
    const computed = await task.solve(stubApi());
    const expected = FIXTURE_ANSWERS[task.id];
    if (expected === undefined) throw new Error(`no fixture answer for ${task.id}`);
    if (typeof expected === "number") {
      expect(Math.abs(Number(computed) - expected)).toBeLessThanOrEqual(Math.max(task.tolerance, 0.01));
    } else {
      expect(computed).toBe(expected);
    }
  });

  test(`${task.id}: grading uses the value solved this run`, async () => {
    const live = await task.solve(stubApi());
    expect(check(task, String(live), live)).toBe(true);
    // The stale reference is not silently accepted when the live value disagrees.
    if (String(live) !== String(task.reference)) {
      expect(check(task, String(task.reference), live)).toBe(false);
    }
  });

  test(`${task.id}: the reference still grades when nothing was solved`, () => {
    expect(check(task, String(task.reference))).toBe(true);
  });
}

test("the grader rejects near misses", () => {
  expect(check(byId("t2-acre-headcount"), "There are 9 deputies.")).toBe(false);
  expect(check(byId("t5-session-party-no-votes"), "PSD")).toBe(false);
  expect(check(byId("t3-march-expenses"), "R$ 46,960.45")).toBe(false);
});

test("the grader tolerates how a model writes numbers", () => {
  const task = byId("t3-march-expenses");
  for (const phrasing of ["46960.46", "R$ 46,960.46", "46.960,46 reais", "The total is 46960.46."]) {
    expect(check(task, phrasing)).toBe(true);
  }
});

test("the grader ignores case and accents", () => {
  expect(check(byId("t1-civil-name"), "josé abílio silva de santana")).toBe(true);
});

test("both decimal conventions parse", () => {
  expect(numbersIn("46.960,46")).toEqual([46960.46]);
  expect(numbersIn("46,960.46")).toEqual([46960.46]);
  expect(numbersIn("1,234")).toEqual([1234]);
});

test("difficulty is a strict gradient", () => {
  expect(TASKS.map((t) => t.difficulty)).toEqual([1, 2, 3, 4, 5]);
  expect(new Set(TASKS.map((t) => t.id)).size).toBe(TASKS.length);
});

test("every required operation exists, and sampling can preserve them", async () => {
  const registry = await load("data/specs/camara-dados-abertos-v2.json");
  const keep = requiredOperations();
  for (const name of keep) byName(registry, name); // throws if the suite depends on a phantom
  expect(keep).toHaveLength(6);

  const kept = sample(registry, 10, { keep, seed: 0 });
  for (const name of keep) expect(kept.operations.some((op) => op.name === name)).toBe(true);
  // N-scaling must not quietly make a task impossible.
  expect(() => sample(registry, 5, { keep, seed: 0 })).toThrow();
});
