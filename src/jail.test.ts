import { describe, expect, test } from "bun:test";
import { leakyEnvNames, referencedHosts } from "./jail.ts";

describe("leakyEnvNames", () => {
  test("flags credential-shaped names that carry a value", () => {
    expect(
      leakyEnvNames({
        OPENROUTER_API_KEY: "sk-or-v1-abc",
        GITHUB_TOKEN: "gho_x",
        DB_PASSWORD: "hunter2",
        MY_SECRET: "s",
        PASSWORD: "p",
      }),
    ).toEqual(["DB_PASSWORD", "GITHUB_TOKEN", "MY_SECRET", "OPENROUTER_API_KEY", "PASSWORD"]);
  });

  test("ignores ordinary variables even when a suffix appears mid-word", () => {
    expect(
      leakyEnvNames({
        PATH: "/usr/bin",
        HOME: "/home/lua",
        MONKEY: "sees no evil", // ends in KEY but not _KEY
        TOKENIZERS_PARALLELISM: "false",
        SSH_AUTH_SOCK: "/tmp/agent",
      }),
    ).toEqual([]);
  });

  test("ignores matches whose value is empty or blank", () => {
    expect(leakyEnvNames({ OPENROUTER_API_KEY: "", OTHER_TOKEN: "   " })).toEqual([]);
  });

  test("is case-insensitive and sorted", () => {
    expect(leakyEnvNames({ b_token: "1", A_KEY: "2" })).toEqual(["A_KEY", "b_token"]);
  });
});

describe("referencedHosts", () => {
  // The shape dsh's session log gives a tool call: the model's arguments arrive as the JSON
  // string it produced.
  const call = (args: Record<string, unknown>) => ({
    type: "tool/call",
    seq: 1,
    data: { turn: 1, step: 1, callId: "t1", name: "bash", arguments: JSON.stringify(args) },
  });

  test("extracts hosts from URLs in tool-call arguments", () => {
    const entries = [call({ command: "curl -s https://dadosabertos.camara.leg.br/api/v2/deputados" })];
    expect(referencedHosts(entries)).toEqual(["dadosabertos.camara.leg.br"]);
  });

  test("ignores URLs that appear only in results, not in arguments", () => {
    const entries = [
      {
        type: "tool/result",
        seq: 2,
        data: {
          message: {
            content: [
              {
                type: "tool-result",
                content: [{ type: "text", text: '{"urlFoto":"https://www.camara.leg.br/foto.jpg"}' }],
              },
            ],
          },
        },
      },
    ];
    expect(referencedHosts(entries)).toEqual([]);
  });

  test("deduplicates, lowercases, sorts, and strips port and userinfo", () => {
    const entries = [
      call({ command: "curl https://EXAMPLE.com:8443/x && curl http://user@example.com/y" }),
      call({ command: "wget https://api.other.dev/z" }),
    ];
    expect(referencedHosts(entries)).toEqual(["api.other.dev", "example.com"]);
  });

  test("tolerates events without data or with non-string arguments", () => {
    expect(
      referencedHosts([
        {},
        { type: "tool/call" },
        { type: "tool/call", data: { arguments: { command: "curl https://obj.example/x" } } },
      ]),
    ).toEqual(["obj.example"]);
  });
});
