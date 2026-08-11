# Roadmap

The project is a ladder, not a verdict. Stage 0 establishes what each format costs before anyone
tunes it; every later number is a distance from there.

## Stage 0 — the unoptimised triad

Three formats, each in its honest default, all installed beside the same stock agent.
**Implemented; not yet run with repeats.**

| arm | what the user installed |
| --- | --- |
| `baseline` | nothing — a shell, and the API's own errors to learn from |
| `mcp` | an MCP server exposing the 78 operations |
| `cli` | a compiled binary on `PATH` |

Defined in [`src/triad.ts`](src/triad.ts). Every arm keeps unrestricted `bash`: that is the common
denominator a terminal agent already has, and the arm is what sits beside it.

## Stage 1 — the optimisation ladder

Introduce optimisations one at a time, **to all three arms wherever they apply**, and measure each as
a delta against stage 0. Where an optimisation cannot apply to an arm, that asymmetry is the finding.

Each must be an independent toggle, never a bundle, or a gain cannot be attributed.

| optimisation | `baseline` | `mcp` | `cli` | state |
| --- | --- | --- | --- | --- |
| filter results | jq over curl | projection parameter | `\| jq` | artifacts support it; not measured |
| compact output format | — | server returns TSV | `--format tsv` | not built |
| truncate with a marker | — | cap arrays, say "N more" | `--limit` | not built |
| errors that teach | (the API already does) | echo valid parameters | usage on error | commander does half |
| trim descriptions | — | shorter tool descriptions | one-line help | not built |

The expected result is convergence: an optimised `baseline` is a CLI built by accident. If the spread
between arms narrows at every rung, the conclusion is that **the format is the default, not the
ceiling** — a more useful claim than any winner.

Likely the largest single win, and untested: output format. 366 vote records as nested JSON against
the same records as TSV.

## Stage 2 — the report

A step-by-step walkthrough of the ladder, showing what each cheap optimisation returns.

## Instrumentation

- **Egress allowlist, if the audit ever shows a reason.** Trials run jailed (ai-jail over
  bubblewrap) with the network open, because ground truth is solved live; what the model reached is
  audited from the trace instead of blocked. If audited runs ever show real probing beyond the
  subject API, the upgrade path is a host-side filtering proxy with the jail's network unshared —
  the pattern Anthropic's sandbox-runtime uses. Not built until the audit says so.

- **Accounting comes from pi**, not from a derivation of ours: per-turn usage with reasoning and
  cache separated, plus `getContextUsage()`, the estimate pi itself uses for compaction.
- **Probe count per task, from the baseline.** How much the `baseline` arm has to probe is a validity
  measure for each task. A task it answers in one call without probing has no discovery cost, and
  therefore cannot discriminate between ways of documenting an API — task 1 is already known to be
  one of these. Worth reporting next to every task.

## Prerequisites, before any of it is publishable

- **Re-run everything.** Every published figure predates the move to a stock harness, and the
  run-time ones also predate the removal of the recorded corpus. All withdrawn.
- **Repeats.** Two runs of an identical arm on an identical task have differed by a whole turn, with
  live API variance on top. Any optimisation worth less than that is unmeasurable until the noise
  comes down. The triad is cheap enough to run at k=5.
- **Task 5, and a second model tier.**
- **Decide what to do about task 1.** The baseline answers it in one call without probing, so it
  measures no discovery cost at all.
