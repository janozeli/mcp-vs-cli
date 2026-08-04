import { describe, expect, test } from "bun:test";
import { jailWrapper, leakyEnvNames, referencedHosts } from "./jail.ts";

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

describe("jailWrapper", () => {
  const wrapper = jailWrapper("/home/lua/.local/share/mise/shims/ai-jail");

  test("is a shell script that hands every argument to bash inside the jail", () => {
    expect(wrapper.startsWith("#!/bin/sh\n")).toBe(true);
    expect(wrapper).toContain('bash "$@"');
    expect(wrapper).toContain('"/home/lua/.local/share/mise/shims/ai-jail"');
  });

  test("keeps the jail silent and stateless", () => {
    // --exec suppresses the banner (tool output must not reveal the jail or add noise) and
    // --no-save-config keeps the policy file out of the trial cwd the model can list.
    expect(wrapper).toContain("--exec");
    expect(wrapper).toContain("--no-save-config");
  });
});

describe("referencedHosts", () => {
  const entry = (content: unknown[]) => ({ message: { role: "assistant", content } });
  const call = (args: Record<string, unknown>) => ({
    type: "toolCall",
    id: "t1",
    name: "bash",
    arguments: args,
  });

  test("extracts hosts from URLs in tool-call arguments", () => {
    const entries = [
      entry([call({ command: "curl -s https://dadosabertos.camara.leg.br/api/v2/deputados" })]),
    ];
    expect(referencedHosts(entries)).toEqual(["dadosabertos.camara.leg.br"]);
  });

  test("ignores URLs that appear only in results, not in arguments", () => {
    const entries = [
      entry([
        {
          type: "toolResult",
          output: '{"urlFoto":"https://www.camara.leg.br/internet/deputado/foto.jpg"}',
        },
      ]),
    ];
    expect(referencedHosts(entries)).toEqual([]);
  });

  test("deduplicates, lowercases, sorts, and strips port and userinfo", () => {
    const entries = [
      entry([
        call({ command: "curl https://EXAMPLE.com:8443/x && curl http://user@example.com/y" }),
        call({ command: "wget https://api.other.dev/z" }),
      ]),
    ];
    expect(referencedHosts(entries)).toEqual(["api.other.dev", "example.com"]);
  });

  test("tolerates entries without messages or with non-array content", () => {
    expect(referencedHosts([{}, { message: {} }, { message: { content: "text" } }])).toEqual([]);
  });
});
