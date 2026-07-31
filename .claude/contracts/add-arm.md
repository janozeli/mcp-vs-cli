# Contract — add or change an arm

Covers a new format, a new disclosure level, a new handling mode, or any change to what an existing
cell exposes.

## Inputs

- Layer 3: `CLAUDE.md` invariants 1 and 6; [`../reference/arm-symmetry.md`](../reference/arm-symmetry.md)
- Layer 3: `bench/spec.py` — the `Registry` every surface must be generated from
- Layer 3: `bench/arms/__init__.py` — `Disclosure`, `Handling`, and the shared `OBJECTIVE`
- Layer 4: none. This stage does not read run artifacts, and a change justified by a run result is a
  finding, not an arm change.

## Process

One transformation: emit a surface from the registry. Nothing here decides what a task is, what a
trial costs, or which claim survives.

1. Answer the three symmetry questions in writing, in the commit message. A change that cannot
   answer them is not ready.
2. Generate. Never hand-write a schema, a subcommand or a help line — if a capability has to be
   typed out per arm, the registry is missing something and that is the actual change.
3. Keep mechanism in the tool description, never in the system prompt. `OBJECTIVE` is byte-identical
   across every cell and stays that way; a prompt that teaches a procedure is a treatment, not a
   constant.
4. Pay for the capability where it is used. A projection parameter costs schema tokens on every
   tool; advertising a pipe costs description tokens. Both are correct — the cost is part of what is
   being measured, so do not exempt one side from it.
5. If the change belongs to level zero, update `bench/triad.py` and say why the new default is the
   honest untuned one. Otherwise it is an optimisation and belongs in `ROADMAP.md`'s ladder table as
   an independent toggle, never bundled with another.

## Outputs

- the emitter, under `bench/arms/`
- an equivalence test proving every operation and parameter reaches the new surface, alongside
  `tests/test_arms.py`
- a `ROADMAP.md` or `bench/triad.py` entry, whichever applies

## Acceptance

- `uv run pytest` passes, including the equivalence tests
- the surface's token cost appears in `uv run python -m bench.measure`
- no previously published number changed meaning without being addressed in `README.md`

## What this prevents

Four separate biased designs shipped as correct implementations. Every one passed its tests.
