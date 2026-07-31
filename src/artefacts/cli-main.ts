#!/usr/bin/env bun
/**
 * The entry point compiled into the binary the CLI arm installs.
 *
 *     bun run build:cli    →    bin/api
 *
 * A compiled binary rather than a script, because "the user installed a CLI" means something on
 * `PATH`, not an interpreter plus a file. The arm should be an installation.
 */

import specDocument from "../../data/specs/camara-dados-abertos-v2.json";
import { Api } from "../api.ts";
import { normalise } from "../spec.ts";
import { buildProgram, invoke } from "./cli.ts";

// The document is imported, not read from disk: `bun build --compile` embeds it, so the binary is a
// single file that works wherever it is put. A CLI that needed a data file beside it would not be
// an installation.
const registry = await normalise(specDocument);
const api = new Api(registry.baseUrl);

const program = buildProgram(registry, async (operation, args) =>
  invoke(api, registry, operation.name, args),
);

try {
  await program.parseAsync(process.argv);
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  // commander throws for --help and for usage errors alike; only the second is a failure.
  if (!/outputHelp|commander\.help/.test(String((error as { code?: string })?.code ?? ""))) {
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
  }
}
