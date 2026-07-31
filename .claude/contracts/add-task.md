# Contract — add or change a benchmark task

## Inputs

- Layer 3: `CLAUDE.md` invariants 2 and 5
- Layer 3: `bench/tasks.py` — the `Task` shape, the difficulty gradient, the grading rules
- Layer 3: `tests/conftest.py` — the hand-written API the suite tests solvers against

## Process

One transformation: turn a question about the live API into a task whose answer is recomputable at
the moment it is used.

1. Write the solver first. It makes exactly the calls a correct agent must make, and it runs live in
   the same window as the trial it grades.
2. The `answer` field is a drift reference, not the grading key. Record what the API said when the
   task was written, and let `scripts/check_ground_truth.py` tell you when that stops being true.
   Never treat it as authoritative in a run that could have solved live instead.
3. State what the task stresses and why its difficulty is what it claims. A task that is hard only
   because it is long is not testing anything the shorter ones do not.
4. Check guessability. Run the `baseline` arm against it. If it answers in one call without probing,
   the route was inferable from REST convention or already known to the model, the task has no
   discovery cost, and it cannot discriminate between ways of documenting an API. Record the probe
   count either way — it is the task's validity measure.
5. Prefer historical questions. Live data means a task about *current* state can change answer
   between one trial and the next; a question about a 2024 vote cannot. Where a task must be about
   the present, say so, because that is where parity between arms is most likely to break.
6. Declare `requires`. It feeds `Registry.sample(keep=...)`, and without it an N-scaling run can
   silently make the task impossible.
7. Keep the grader programmatic. Accents and both decimal conventions are already handled; a model
   writing "R$ 46.960,46" answered correctly. If a task needs judgement to grade, it is the wrong
   task.

## Outputs

- a `Task` in `bench/tasks.py`, with its solver
- a fixture for it in `tests/conftest.py`, hand-written and deliberately not the real values
- tests alongside `tests/test_tasks.py`, exercising the solver's logic against that fixture
- the probe count, reported with the task

## Acceptance

- the solver produces the fixture's answer offline, and the live answer live
- the grader accepts the right answer and rejects near misses
- `tasks.required_operations()` still fits the smallest N level any run intends to use
- `uv run python -m scripts.check_ground_truth` agrees with the recorded reference

## What this prevents

Publishing a task that measures nothing — task 1 is already known to be one of these, because the
baseline guessed the route and never probed. And a suite that tests the world instead of the code:
the fixtures are authored so the tests fail only when *this repository* breaks.
