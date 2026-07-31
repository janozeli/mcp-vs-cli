# Contract — run trials against a model

## Inputs

- Layer 3: `CLAUDE.md` invariants 2, 3 and 4
- Layer 3: `bench/config.py` — the pinned model and temperature
- Layer 3: `bench/triad.py` — which cells constitute level zero, and their turn ceilings
- Layer 4: `data/cassettes/` — the corpus, and whether this run may extend it

## Process

Two jobs that must not be confused, because they have opposite requirements.

**Recording** is deliberate, human-run, and mutates the corpus. Agents explore, so a first contact
with a task will reach for calls no solver needed. Run in record mode on purpose, know that the
corpus changed, and re-run affected earlier trials afterwards — `scripts/pilot.py` currently records
while it runs, which means a trial has already silently extended the corpus mid-experiment.

**Measuring** replays and mutates nothing. Every cell of a comparison must see the same corpus, or
the comparison is between two datasets.

1. Pin the model. A router (`openrouter/auto`, `openrouter/free`) picks per request, so two cells can
   land on different models and the comparison stops being about exposure. Every trace records the
   model the provider actually resolved; check them before believing a table.
2. Give each arm the turn ceiling it needs. Blind discovery cut at the documented arms' ceiling
   measures the ceiling. Running out of turns is a result and is recorded as one.
3. Retry capacity errors, never score them. A free endpoint answers HTTP 200 with `choices: null`
   when it is out of workers; a trial that landed on a busy worker says nothing about its arm.
4. Repeat. Two runs of an identical cell on an identical task produced 125,574 and 102,467 prompt
   tokens at temperature 0 — a 22% spread. A single trial cannot support any claim smaller than
   that, and no optimisation should be reported against a k=1 baseline.
5. Never invent a response. A cassette miss in replay aborts the trial. A run built on fabricated
   data is worse than no run.

## Outputs

- `runs/<run>/<task>/<task>__<arm>.jsonl` — one trace per trial
- any new recordings in `data/cassettes/`, committed separately from code, so the corpus change is
  visible in history

## Acceptance

- `uv run python -m scripts.summarise <run>` reproduces the reported numbers from the traces alone
- every trace resolved to the same pinned model
- the corpus at the end of the comparison is the corpus every cell ran against

## What this prevents

Comparing cells that saw different bytes, scoring a provider outage as an arm's failure, and
reporting a difference smaller than the noise.
