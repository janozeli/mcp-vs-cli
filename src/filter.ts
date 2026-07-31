/**
 * Reducing a response before it reaches the context, in the one language both arms get.
 *
 * The CLI reaches this through a `| jq` pipe and the MCP server through a projection parameter. Same
 * language on both sides on purpose: a bespoke field selector on one side would measure which syntax
 * the model knows rather than where the filtering happens, and jq is the one it has read a lot of.
 *
 * Real jq, compiled to WebAssembly — not a lookalike, and no native dependency, so the repository
 * stays cloneable and runnable anywhere Bun runs.
 */

import * as jq from "jq-wasm";

/**
 * Run a jq expression over a response.
 *
 * A bad expression comes back as an error the model can read and correct, exactly as a failed pipe
 * would. Silently returning the unfiltered body instead would hide the cost of getting it wrong,
 * which is part of what filtering actually costs.
 */
export async function applyFilter(body: unknown, expression: string): Promise<string> {
  try {
    const outputs = await jq.json(body as never, expression);
    const list = Array.isArray(outputs) ? outputs : [outputs];
    return list.map((item) => JSON.stringify(item)).join("\n");
  } catch (error) {
    return `jq: error: ${error instanceof Error ? error.message : String(error)}`;
  }
}

/** Whether an expression is valid, without running it against real data. */
export async function isValidFilter(expression: string): Promise<boolean> {
  const result = await applyFilter({}, expression);
  return !result.startsWith("jq: error");
}
