# Contract — add or change a benchmark task

## Inputs

- Layer 3: `CLAUDE.md` invariants 2 and 5
- Layer 3: `bench/tasks.py` — the `Task` shape, the difficulty gradient, the grading rules
- Layer 4: `data/cassettes/` — the frozen corpus, read to confirm a solver is satisfiable

## Process

One transformation: turn a question about the frozen corpus into a task with a recomputable answer.

1. Write the solver first. It makes exactly the calls a correct agent must make, which is also how
   the corpus learns what to record.
2. Never type an answer in. The pinned value must come from running the solver, and a test asserts
   the two still agree — so a re-recorded corpus fails loudly instead of grading against a stale key.
3. State what the task stresses and why its difficulty is what it claims. A task that is hard only
   because it is long is not testing anything the shorter ones do not.
4. Check guessability. Run the `baseline` arm against it. If it answers in one call without probing,
   the route was inferable from REST convention or already known to the model, the task has no
   discovery cost, and it cannot discriminate between ways of documenting an API. Record the probe
   count either way — it is the task's validity measure.
5. Declare `requires`. It feeds `Registry.sample(keep=...)`, and without it an N-scaling run can
   silently make the task impossible.
6. Keep the grader programmatic. Accents and both decimal conventions are already handled; a model
   writing "R$ 46.960,46" answered correctly. If a task needs judgement to grade, it is the wrong
   task.

## Outputs

- a `Task` in `bench/tasks.py`, with its solver
- recordings in `data/cassettes/`, via `uv run python -m scripts.record_corpus`
- tests alongside `tests/test_tasks.py`, including the pinned-answer check
- the probe count, reported with the task

## Acceptance

- the solver reproduces the pinned answer offline, replaying only
- the grader accepts the right answer and rejects near misses
- `tasks.required_operations()` still fits the smallest N level any run intends to use

## What this prevents

Grading against an answer that was true once. And publishing a task that measures nothing: task 1 is
already known to be one of these, because the baseline guessed the route and never probed.
