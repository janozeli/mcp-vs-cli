# Contract — run trials against a model

## Inputs

- Layer 3: `CLAUDE.md` invariants 3, 4 and 5
- Layer 3: `src/harness.ts` — the objective, the pinned model, and the settings every arm shares
- Layer 3: `src/triad.ts` — which arms constitute level zero
- Layer 4: none at the start. A run produces its evidence; it does not consume any.

## Process

One transformation: a task and a set of arms become results.

Everything is live. There is no cache, no corpus and no replay, so a run cannot be made to see the
past — and does not pretend to.

1. **Build the artefacts first.** `bun run build:cli` — the CLI arm installs a binary, and a stale one
   measures the wrong thing.
2. **Solve the ground truth live, once, before the arms run.** Every arm is graded against that value.
   A recorded reference would go stale in silence; `src/tasks.ts` keeps one only as a drift signal,
   and `bun run ground-truth` is what consumes it.
3. **Change nothing per arm except what is installed.** The harness sets the objective, the settings
   and the tools once. An arm that needs a different setting is no longer the same experiment, and
   the difference has to be declared.
4. **Leave compaction and retries off.** pi compacts context automatically, and its own
   `getContextUsage()` reports null tokens until a post-compaction assistant response exists — a
   context benchmark with compaction on loses its metric exactly when it matters.
5. **Repeat.** Two runs of an identical arm on an identical task have differed by a whole turn, at
   temperature unpinned and with live API variance on top. A single trial cannot support a claim
   smaller than that, and no optimisation should be reported against a k=1 baseline.
6. **Be a good guest.** The subject is a public, unauthenticated service run at public expense.
   Trials are sequential and requests are spaced.

## Outputs

- per-trial results: turns, tool calls, context, output, reasoning and cost, from pi's own accounting
- the live ground truth the run graded against

## Acceptance

- every arm ran through `harness.run`, with no per-arm setting changed
- the reported context figure is pi's `getContextUsage`, not a derivation
- the model actually used is the model requested

## What this prevents

Grading against a value that was true once, measuring pi's compactor instead of the exposure, and
reporting a difference smaller than the noise.
