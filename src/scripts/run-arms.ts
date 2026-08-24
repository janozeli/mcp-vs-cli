/**
 * Run one task across the triad, through the shared harness.
 *
 * Every arm goes through `harness.run`, so what differs between them is what was installed, never
 * how the run was set up.
 *
 *     bun run run-arms t1-civil-name
 *     bun run run-arms t1-civil-name --arms baseline,cli
 */

import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseArgs } from "node:util";
import specDocument from "../../data/specs/camara-dados-abertos-v2.json";
import { Api } from "../api.ts";
import { MODEL, run } from "../harness.ts";
import { normalise } from "../spec.ts";
import { byId, check } from "../tasks.ts";
import { armByKey, TRIAD } from "../triad.ts";

const { values, positionals } = parseArgs({
  args: Bun.argv.slice(2),
  options: { arms: { type: "string" } },
  allowPositionals: true,
});

const task = byId(positionals[0] ?? "t1-civil-name");
const arms = values.arms ? values.arms.split(",").map((k) => armByKey(k.trim())) : [...TRIAD];

const apiKey = process.env.OPENROUTER_API_KEY?.trim();
if (!apiKey) {
  console.error("OPENROUTER_API_KEY is not set. Copy .env.example to .env and paste a key from");
  console.error("https://openrouter.ai/keys. Only the run-time half needs one; `bun run measure` does not.");
  process.exit(1);
}
// From here on this local is the key's only custodian. Children of this process — the model's
// bash, the MCP server — inherit the environment, and the harness refuses to run if anything
// credential-shaped is still in it. The trial reads the key back through dsh's file-backed
// credential store, never the environment.
delete process.env.OPENROUTER_API_KEY;

const registry = await normalise(specDocument);
console.log(`${task.id} — ${task.question}`);
const expected = await task.solve(new Api(registry.baseUrl, { pauseMs: 200 }));
console.log(`solved live: ${expected}  ·  model ${MODEL}\n`);

const traceDir = join("runs", task.id);
await mkdir(traceDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[:.]/g, "-");

const rows: string[][] = [];
for (const arm of arms) {
  process.stdout.write(`  running ${arm.key} …`);
  // Each arm gets its own working directory, so one arm's installation cannot leak into the arm
  // that runs next.
  const cwd = await mkdtemp(join(tmpdir(), `arm-${arm.key}-`));
  const result = await run({ arm, question: task.question, apiKey, cwd });
  const ok = check(task, result.answer, expected);

  // The audit half of the open-network boundary: egress is free by invariant 3, so what the model
  // reached beyond the API it was given is a reported fact, never a silent one.
  const apiHost = new URL(registry.baseUrl).host;
  const foreignHosts = result.hosts.filter((host) => host !== apiHost);

  // Invariant 4: the run has to be recomputable by someone who does not trust us, and a trace
  // without tool results cannot distinguish an arm that worked from one that gave up.
  const trace = [
    {
      kind: "meta",
      task: task.id,
      arm: arm.key,
      model: MODEL,
      expected,
      answer: result.answer,
      ok,
      jailed: result.jailed,
      hosts: result.hosts,
      contextSource: result.contextSource,
    },
    { kind: "tools", active: result.activeTools, called: result.toolCalls },
    ...result.entries.map((entry) => ({ kind: "entry", entry })),
    ...result.turns.map((turn) => ({ kind: "usage", ...turn })),
  ];
  await writeFile(
    join(traceDir, `${stamp}-${arm.key}.jsonl`),
    `${trace.map((row) => JSON.stringify(row)).join("\n")}\n`,
    "utf8",
  );

  console.log(`${result.aborted ? " ABORTED" : ok ? " ok" : " wrong"}  [${result.toolCalls.join(", ")}]`);
  console.log(`      offered: ${result.activeTools.join(", ")}`);
  if (result.aborted) console.log(`      ${result.aborted}`);
  for (const failure of result.errors) console.log(`      error: ${failure}`);
  if (foreignHosts.length > 0) console.log(`      foreign hosts: ${foreignHosts.join(", ")}`);
  rows.push([
    arm.key,
    result.aborted ? "—" : ok ? "yes" : "no",
    String(result.turns.length),
    String(result.toolCalls.length),
    (result.contextTokens ?? result.peakContext).toLocaleString("en-US"),
    result.totalOutput.toLocaleString("en-US"),
  ]);
}

const headers = ["arm", "ok", "turns", "calls", "context", "output"];
const widths = headers.map((h, i) => Math.max(h.length, ...rows.map((r) => (r[i] ?? "").length)));
const line = (cells: string[]) => cells.map((c, i) => c.padStart(widths[i] ?? 0)).join("  ");
console.log(`\n${line(headers)}`);
for (const row of rows) console.log(line(row));
