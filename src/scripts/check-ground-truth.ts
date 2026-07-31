/**
 * Solve every task against the live API and compare with the value last observed.
 *
 * The test suite deliberately cannot do this. A test that reaches the network fails for reasons that
 * have nothing to do with the code, and a suite that fails for external reasons is a suite people
 * learn to ignore. So the tests check the code, and this checks the world.
 *
 * Run it before a batch of measurements. A task whose answer has moved is not broken — it is a task
 * whose difficulty or meaning may have changed, and the reference in `tasks.ts` needs updating
 * deliberately rather than silently.
 *
 *     bun run ground-truth
 */

import specDocument from "../../data/specs/camara-dados-abertos-v2.json";
import { Api } from "../api.ts";
import { normalise } from "../spec.ts";
import { check, TASKS } from "../tasks.ts";

const registry = await normalise(specDocument);
const api = new Api(registry.baseUrl, { pauseMs: 200 });

console.log(`solving ${TASKS.length} tasks against ${registry.baseUrl}\n`);
const drifted: { id: string; reference: unknown; live: unknown }[] = [];

for (const task of TASKS) {
  const live = await task.solve(api);
  const agrees = check(task, String(live));
  console.log(
    `  [${task.difficulty}] ${task.id.padEnd(28)} ${String(live).padEnd(32)} ${agrees ? "agrees" : "DRIFTED"}`,
  );
  if (!agrees) drifted.push({ id: task.id, reference: task.reference, live });
}

console.log(`\n${api.calls} API calls`);
if (drifted.length > 0) {
  console.log("\nthe API no longer says what these tasks recorded:");
  for (const row of drifted) console.log(`  ${row.id}: reference ${row.reference}, now ${row.live}`);
  console.log("\nUpdate `reference` in src/tasks.ts deliberately, and consider whether the task still");
  console.log("stresses what it claims to.");
  process.exitCode = 1;
}
