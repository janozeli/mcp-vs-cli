# Contract — add or change an arm

An arm is an *installation*: what a user put beside their agent. It is not a code path.

## Inputs

- Layer 3: `CLAUDE.md` invariants 1, 2 and 7; [`../reference/arm-symmetry.md`](../reference/arm-symmetry.md)
- Layer 3: `src/spec.ts` — the `Registry` every artifact must be generated from
- Layer 3: `src/harness.ts` — the `Arm` shape and the settings every arm shares
- Layer 4: none. This stage does not read run artifacts, and a change justified by a run result is a
  finding, not an arm change.

## Process

One transformation: describe what gets installed. Nothing here decides what a task is, what a trial
costs, or which claim survives.

1. Answer the three symmetry questions in writing, in the commit message. A change that cannot answer
   them is not ready.
2. Generate the artifact from the registry. Never hand-write a tool schema, a subcommand or a help
   line — if a capability has to be typed out per arm, the registry is missing something and that is
   the actual change.
3. Prefer a library to your own code, especially for anything the experiment measures. The CLI help
   is commander's for that reason: hand-rendered, it cost 42% less than what a real framework prints,
   and the README had to carry a caveat about it.
4. Every arm keeps unrestricted `bash`. That is the common denominator a terminal agent already has;
   the arm is what sits beside it.
5. Pay for the capability where it is used. A projection parameter costs schema tokens on every tool.
   That cost is part of what is being measured, so do not exempt one side from it.
6. If the change belongs to level zero, update `src/triad.ts` and say why the new default is the
   honest untuned one. Otherwise it is an optimisation and belongs in `ROADMAP.md`'s ladder table as
   an independent toggle, never bundled with another.

## Outputs

- the artifact, under `src/artifacts/`
- an equivalence test proving every operation and parameter reaches it, alongside
  `src/artifacts/artifacts.test.ts`
- a `ROADMAP.md` or `src/triad.ts` entry, whichever applies

## Acceptance

- `bun run check` passes, including the equivalence tests
- the artifact's token cost appears in `bun run measure`
- no previously published number changed meaning without being addressed in `README.md`

## What this prevents

Four separate biased designs shipped as correct implementations. Every one passed its tests.
