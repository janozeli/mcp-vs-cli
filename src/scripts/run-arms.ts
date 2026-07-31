/**
 * Run one task across the triad, through the shared harness.
 *
 * Every arm goes through `harness.run`, so what differs between them is what was installed, never
 * how the run was set up.
 *
 *     bun run run-arms t1-civil-name
 *     bun run run-arms t1-civil-name --arms baseline,cli
 */

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

const registry = await normalise(specDocument);
console.log(`${task.id} — ${task.question}`);
const expected = await task.solve(new Api(registry.baseUrl, { pauseMs: 200 }));
console.log(`solved live: ${expected}  ·  model ${MODEL}\n`);

const rows: string[][] = [];
for (const arm of arms) {
  process.stdout.write(`  running ${arm.key} …`);
  const result = await run({ arm, question: task.question, apiKey, cwd: process.cwd() });
  const ok = check(task, result.answer, expected);
  console.log(ok ? " ok" : " wrong");
  rows.push([
    arm.key,
    ok ? "yes" : "no",
    String(result.turns.length),
    String(result.toolCalls.length),
    (result.contextTokens ?? result.peakContext).toLocaleString("en-US"),
    result.totalOutput.toLocaleString("en-US"),
    result.totalReasoning.toLocaleString("en-US"),
    `$${result.cost.toFixed(4)}`,
  ]);
}

const headers = ["arm", "ok", "turns", "calls", "context", "output", "reasoning", "cost"];
const widths = headers.map((h, i) => Math.max(h.length, ...rows.map((r) => (r[i] ?? "").length)));
const line = (cells: string[]) => cells.map((c, i) => c.padStart(widths[i] ?? 0)).join("  ");
console.log(`\n${line(headers)}`);
for (const row of rows) console.log(line(row));
