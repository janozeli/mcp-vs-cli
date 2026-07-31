# Contract — run trials against a model

## Inputs

- Layer 3: `CLAUDE.md` invariants 2, 3 and 4
- Layer 3: `bench/config.py` — the pinned model and temperature
- Layer 3: `bench/triad.py` — which cells constitute level zero, and their turn ceilings
- Layer 4: none at the start. A run produces its evidence; it does not consume any.

## Process

One transformation: a task and a set of arms become traces.

Everything is live. There is no cache, no corpus and no replay, so a run cannot be made to see the
past — and does not pretend to.

1. **Solve the ground truth live, once, before the arms run.** Every arm in the comparison is graded
   against that value. A recorded reference would go stale in silence, which is worse than the drift
   it was meant to guard against; the reference in `bench/tasks.py` is a drift signal only, and
   `scripts/check_ground_truth.py` is what consumes it.
2. **Pin the model.** A router (`openrouter/auto`, `openrouter/free`) picks per request, so two cells
   can land on different models and the comparison stops being about exposure. Every trace records
   the model the provider actually resolved; check them before believing a table.
3. **Give each arm the turn ceiling it needs.** Blind discovery cut at the documented arms' ceiling
   measures the ceiling. Running out of turns is a result and is recorded as one.
4. **Retry capacity errors, never score them.** A free endpoint answers HTTP 200 with `choices: null`
   when it is out of workers; a trial that landed on a busy worker says nothing about its arm. The
   same applies to a 5xx from the subject API, which is retried with backoff.
5. **Verify parity afterwards.** Run `scripts/verify_parity.py`. Where two arms made the same request
   and got different bytes, the API moved mid-comparison. That does not necessarily invalidate the
   run, but it has to be reported rather than discovered later by a reader.
6. **Repeat.** Two runs of an identical cell on an identical task produced 125,574 and 102,467 prompt
   tokens at temperature 0 — a 22% spread, now with live API variance on top of it. A single trial
   cannot support any claim smaller than that.
7. **Be a good guest.** The subject is a public, unauthenticated service run at public expense.
   Trials are sequential, requests are spaced, and retries are bounded. Do not parallelise a battery
   across arms to save wall-clock.

## Outputs

- `runs/<task>/<task>__<arm>.jsonl` — one trace per trial, holding every request and every response
- `runs/<task>/manifest.json` — the live solve, the drift check against the reference, the models
  the provider resolved, and the API call count

## Acceptance

- `uv run python -m scripts.summarise runs` reproduces the reported numbers from the traces alone
- `uv run python -m scripts.verify_parity` reports no divergence, or the divergence is reported
- every trace resolved to the same pinned model

## What this prevents

Grading against a value that was true once, scoring a provider outage as an arm's failure, reporting
a difference smaller than the noise, and — the one that cannot be prevented, only detected — a
comparison whose arms saw different data.
