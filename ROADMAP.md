# Roadmap

The project is a ladder, not a verdict. Stage 0 establishes what each format costs before anyone
tunes it; every later number is a distance from there.

## Stage 0 — the unoptimised triad

Three formats, each in its honest default. **Implemented; not yet run with repeats.**

| arm | what the model gets |
| --- | --- |
| `baseline` | an HTTP verb and a base URL. No documentation of any kind. |
| `mcp` | every schema declared on connect, responses returned whole — the off-the-shelf server |
| `cli` | one command tool, discovery through `--help`, responses returned whole |

Defined in [`bench/triad.py`](bench/triad.py).

## Stage 1 — the optimisation ladder

Introduce optimisations one at a time, **to all three arms wherever they apply**, and measure each as
a delta against stage 0. Where an optimisation cannot apply to an arm, that asymmetry is the finding.

Each must be an independent toggle, never a bundle, or a gain cannot be attributed. Several already
exist in the codebase and were measured before the triad was framed; they are optimisations, not
part of the baseline.

| optimisation | `baseline` | `mcp` | `cli` | state |
| --- | --- | --- | --- | --- |
| defer discovery | — | `tool_search` | `--help` | built |
| preload documentation | fetch the spec | (is the default) | manual in prompt | built |
| filter results | `_jq` argument | projection parameter | `\| jq` | built |
| compact output format | — | server returns TSV | `--format tsv` | not built |
| truncate with a marker | — | cap arrays, say "N more" | `--limit` | not built |
| errors that teach | (the API already does) | echo valid parameters | usage on error | not built |
| trim descriptions | — | shorter tool descriptions | one-line help | not built |

The expected result is convergence: an optimised `baseline` is a CLI built by accident. If the spread
between arms narrows at every rung, the conclusion is that **the format is the default, not the
ceiling** — which is a more useful claim than any winner.

Likely the largest single win, and untested: output format. 366 vote records as nested JSON against
the same records as TSV.

## Stage 2 — the report

A step-by-step walkthrough of the ladder, showing what each cheap optimisation returns.

## Instrumentation

- **Complete per-turn logs.** Done, and no longer optional. Nothing caches API responses, so a trace
  is the only place one survives: each turn now records its request, its response, and every tool
  call with the bytes it returned. Both invariant 4 and the parity check rest on it.
- **Parity between arms.** Live data cannot guarantee that two arms saw the same bytes, so
  `scripts/verify_parity.py` measures it from the traces instead and reports any shared request that
  diverged. A comparison that spans a change in the API is still usable, but only if it says so.
- **Probe count per task, from the baseline.** How much the `baseline` arm has to probe is a
  validity measure for each task. A task it answers in one call without probing has no discovery
  cost, and therefore cannot discriminate between ways of documenting an API — task 1 is already
  known to be one of these. Worth reporting next to every task.

## Prerequisites, before any of it is publishable

- **Re-run everything.** Every published number predates the removal of the recorded corpus and was
  measured against data that no longer exists in this repository. They are evidence of what the
  harness did, not measurements to cite.
- **Repeats.** Two runs of an identical cell on an identical task produced 125,574 and 102,467
  prompt tokens — a 22% spread at temperature 0, and now with live API variance on top. Any
  optimisation worth less than that is unmeasurable until the noise comes down. The triad is cheap
  enough to run at k=5.
- **Re-run tasks 1–3.** Deferred cells were executing tools they had never loaded; fixed, but those
  numbers are understated and stand withdrawn until redone.
- **Rename the projection parameter.** `_jq` reads as private in every convention a model has seen,
  so the null result for `mcp/filtered` may be an artefact of the name rather than of the format.
- **Task 5, and the second model tier.**
