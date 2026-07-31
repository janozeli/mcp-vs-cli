import { expect, test } from "bun:test";
import { Api, canonicalRequest } from "./api.ts";

test("the canonical form does not depend on order or type", () => {
  const a = canonicalRequest("GET", "/deputados", { siglaUf: "AC", itens: 100 });
  const b = canonicalRequest("get", "/deputados", { itens: "100", siglaUf: "AC" });
  expect(a).toBe(b);
  expect(a).toBe("GET /deputados?itens=100&siglaUf=AC");
});

test("different calls have different canonical forms", () => {
  expect(canonicalRequest("GET", "/deputados", { siglaUf: "AC" })).not.toBe(
    canonicalRequest("GET", "/deputados", { siglaUf: "RJ" }),
  );
  expect(canonicalRequest("GET", "/deputados")).not.toBe(canonicalRequest("GET", "/proposicoes"));
});

test("an error response is a result, not an exception", async () => {
  // The API rejecting a parameter is part of what one task measures; swallowing it as a thrown
  // error would delete the obstacle.
  const api = new Api("https://dadosabertos.camara.leg.br/api/v2");
  const result = await api.get("/votacoes/2400758-37/votos", { itens: 600 });
  expect(result.ok).toBe(false);
  expect(result.status).toBe(400);
  expect(JSON.stringify(result.body)).toContain("itens");
}, 30_000);

test("array parameters are joined the way the API expects", async () => {
  const api = new Api("https://dadosabertos.camara.leg.br/api/v2");
  const result = await api.get("/deputados", { siglaUf: ["AC"], itens: 100 });
  expect(result.ok).toBe(true);
  expect(result.url).toContain("siglaUf=AC");
}, 30_000);
