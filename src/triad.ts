/**
 * The unoptimised triad: what each of the three formats looks like before anyone tunes it.
 *
 * This is level zero of the ladder, and a deliberate choice rather than a limitation. Every
 * optimisation the project goes on to measure is a delta against these three, so they have to be the
 * honest defaults — what you get without thinking about it.
 *
 * Every arm gets unrestricted `bash`. That is the common denominator a real terminal agent already
 * has; the arm is what gets installed beside it.
 */

import type { Arm } from "./harness.ts";

const REPO = new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");

export const TRIAD: readonly Arm[] = [
  {
    key: "baseline",
    tools: ["bash"],
    mcpServers: {},
    installs: [],
    pathAdditions: [],
    why: "a shell and nothing else: the price of having no documentation at all",
  },
  {
    // `mcp` is the adapter's own tool. With an allowlist in force, an extension's tools have to be
    // named explicitly or they are filtered out — which would have made this arm a silent baseline.
    // The server itself is spawned by the client on the host, as in any real installation — which
    // places it outside the jail; declared in .claude/reference/arm-symmetry.md.
    key: "mcp",
    tools: ["bash", "mcp"],
    mcpServers: { camara: `bun run ${REPO}src/artifacts/mcp-server.ts` },
    installs: [],
    pathAdditions: [],
    why: "the user installed an MCP server; the client decides how it reaches the model",
  },
  {
    // The binary is copied into the trial's cwd: it is the installation, and it has to exist
    // inside the jail, where the repository does not.
    key: "cli",
    tools: ["bash"],
    mcpServers: {},
    installs: [{ from: `${REPO}bin/api`, to: "bin/api" }],
    pathAdditions: ["bin"],
    why: "the user installed a CLI; the shell it already had is how it gets called",
  },
];

export function armByKey(key: string): Arm {
  const found = TRIAD.find((arm) => arm.key === key);
  if (!found) throw new Error(`unknown arm: '${key}'`);
  return found;
}
