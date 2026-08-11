/**
 * Static context cost of each artifact, as a function of how many operations exist.
 *
 * This answers the first half of the question — what each way of exposing capabilities occupies in
 * the window — offline and without spending anything. What each one *recovers* for that cost is the
 * run-time half and lives elsewhere.
 *
 *     bun run measure
 */

import { getEncoding } from "js-tiktoken";
import specDocument from "../data/specs/camara-dados-abertos-v2.json";
import { fullHelp, rootHelp } from "./artifacts/cli.ts";
import { toolDefinitions } from "./artifacts/mcp-server.ts";
import { normalise, type Registry, sample } from "./spec.ts";

const ENCODING = "o200k_base";
const encoder = getEncoding(ENCODING);

/**
 * A static estimate: what a payload costs before anything runs.
 *
 * The right tool for "how much does this occupy before the task is read", and the wrong tool for
 * reporting what a run consumed — for that the harness records the provider's own usage.
 */
export const countText = (text: string): number => encoder.encode(text).length;
export const countJson = (payload: unknown): number => countText(JSON.stringify(payload));

const LEVELS = [5, 10, 20, 40, 78] as const;

export interface Row {
  readonly operations: number;
  /** Every schema declared up front, as an MCP client that does not defer would send them. */
  readonly mcpEager: number;
  /** The same, with a projection parameter on every tool. */
  readonly mcpFiltered: number;
  /** The whole manual up front. */
  readonly cliManual: number;
  /** One line per command: what `api --help` costs to read. */
  readonly cliIndex: number;
}

export function costs(registry: Registry): Row {
  return {
    operations: registry.operations.length,
    mcpEager: countJson(toolDefinitions(registry, false)),
    mcpFiltered: countJson(toolDefinitions(registry, true)),
    cliManual: countText(fullHelp(registry)),
    cliIndex: countText(rootHelp(registry)),
  };
}

export function curve(registry: Registry): Row[] {
  return LEVELS.map((n) =>
    costs(n < registry.operations.length ? sample(registry, n, { seed: 0 }) : registry),
  );
}

if (import.meta.main) {
  const registry = await normalise(specDocument);
  const rows = curve(registry);
  const pad = (value: string | number, width = 12) => String(value).padStart(width);

  console.log(`Static context cost — ${registry.title} (${ENCODING})\n`);
  console.log(
    ["operations", "mcp eager", "mcp filtered", "cli manual", "cli index"].map((h) => pad(h)).join(""),
  );
  for (const row of rows) {
    console.log(
      [row.operations, row.mcpEager, row.mcpFiltered, row.cliManual, row.cliIndex]
        .map((v) => pad(v.toLocaleString("en-US")))
        .join(""),
    );
  }

  const last = rows.at(-1);
  if (last) {
    console.log(
      `\nAt ${last.operations} operations: declaring every schema costs ${last.mcpEager.toLocaleString("en-US")};` +
        ` the same manual as help text costs ${last.cliManual.toLocaleString("en-US")};` +
        ` one line per command costs ${last.cliIndex.toLocaleString("en-US")}.`,
    );
    console.log(
      `Offering projection on every tool adds ${(last.mcpFiltered - last.mcpEager).toLocaleString("en-US")}` +
        " tokens — the honest price of advertising the capability.",
    );
  }
}
