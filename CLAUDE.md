# mcp-vs-cli — steward configuration

This file configures agents working **on this repository**. It is not about the benchmark's own
pipeline, which is ordinary tested code under `bench/`.

Structured after the Interpretable Context Methodology (Van Clief & McDermott, arXiv:2603.16021v2):
identity, then routing, then per-task contracts, with stable constraints separated from run
artifacts. One deviation is deliberate — the host always loads this file and nothing else, so the
constraints that must bind *unconditionally* live here rather than in a reference file that a
contract would have to pull in. Anything that binds conditionally is under `.claude/`.

---

## Layer 0 — Identity

A benchmark measuring what it costs to expose a set of capabilities to an LLM agent, and what each
way of doing it buys back.

Exposure is three independent factors: **format** (JSON Schema vs. help text), **disclosure**
(eager / indexed / lazy), and **result handling** (whole vs. filtered). Collapsing them into "MCP vs
CLI" is the mistake the design exists to avoid — clients defer tool loading, and a manual can be
preloaded. The first two are paid once, the third on every call.

The project is a ladder, not a verdict. `bench/triad.py` is level zero: each format in its honest
untuned default. Everything else is an optimisation, and only means anything as a distance from
there. See [ROADMAP.md](ROADMAP.md).

**What this repo is not.** Not a library, not an MCP server, not an MCP client. Nothing here is
meant to be imported or deployed. It exists to produce numbers that a stranger can recompute.

---

## Layer 1 — Routing

| If the task is… | read | before touching |
| --- | --- | --- |
| adding or changing a format, disclosure level or handling mode | [`.claude/contracts/add-arm.md`](.claude/contracts/add-arm.md) | `bench/arms/`, `bench/triad.py` |
| adding or changing a benchmark task | [`.claude/contracts/add-task.md`](.claude/contracts/add-task.md) | `bench/tasks.py` |
| running trials against a model | [`.claude/contracts/run-trials.md`](.claude/contracts/run-trials.md) | `scripts/pilot.py`, `data/cassettes/` |
| turning traces into a published claim | [`.claude/contracts/report-findings.md`](.claude/contracts/report-findings.md) | `README.md` |
| anything that changes what an arm can reach or discover | [`.claude/reference/arm-symmetry.md`](.claude/reference/arm-symmetry.md) | anything |

For work that fits none of these, the invariants below still bind. Say which one governs your change
before making it.

---

## Layer 3 — Invariants

Unconditional. These are what make the numbers mean anything; breaking one silently invalidates the
experiment rather than failing a test.

1. **One source of truth.** `bench/spec.py` turns an OpenAPI document into a `Registry` of
   `Operation`s. Every cell is *generated* from that registry. Never hand-write a tool schema or a
   CLI subcommand — if the cells can drift, the experiment compares implementations instead of
   exposure. Deferring a description must never hide a capability.
2. **Identical responses across arms.** All API access goes through the record-replay cassette. Two
   arms running the same task must see byte-identical payloads. A trial in replay mode never touches
   the network, and a miss aborts the trial rather than inventing a response.
3. **Determinism.** Fixed seeds, temperature 0, sorted iteration order. Operation sampling goes
   through `Registry.sample(n, keep=..., seed=...)`, never ad-hoc slicing.
4. **Auditable accounting.** Every request and response is written to JSONL with the exact wire
   payload and the provider's native usage numbers. Any published figure must be recomputable from
   `runs/` alone, by someone who does not trust us. `scripts/summarise.py` is the proof that it can.
5. **No LLM judges.** Task success is decided against ground truth recomputed from the frozen
   corpus.
6. **Symmetry of affordance.** Any capability offered to one arm must be equally discoverable and
   equally idiomatic in the others. Where it cannot be, the asymmetry is declared and reported, never
   left to show up in the results as if it were a property of the format. This one is newest and has
   been violated four times — see [`.claude/reference/arm-symmetry.md`](.claude/reference/arm-symmetry.md).

---

## Layer 4 — Working directories

Run artifacts. Regenerable, never hand-edited, and never cited as evidence of anything except what
the run did.

- `runs/` — raw JSONL traces, one file per trial. Gitignored.
- `data/cassettes/` — recorded API responses. Committed, because the repo must run offline, but
  extended only through the recording contract, never by hand.

`data/specs/` is **not** Layer 4. It is a frozen reference with provenance (`*.meta.json`: source
URL, fetch date, sha256), and re-fetching it is a deliberate act that invalidates ground truth.

---

## Layout

- `bench/spec.py` — OpenAPI → `Registry` (the source of truth)
- `bench/arms/` — one module per format (`mcp`, `cli`, `raw`); each takes a `Disclosure`
- `bench/triad.py` — level zero: the unoptimised default of each format
- `bench/design.py` — the crossing, and what each cell costs in context
- `bench/measure.py` — the static half of the experiment
- `bench/replay.py` — the record-replay cassette
- `bench/execute.py` — tool calls and command lines, through one code path
- `bench/tasks.py` — the tasks, their solvers and their pinned answers
- `bench/agent.py` — the trial loop and its traces
- `scripts/` — deliberate, human-run operations (`uv run python -m scripts.<name>`)

## Conventions

- Python 3.12+, uv, ruff (`E,F,W,I,UP,B,SIM,RUF`), pytest, mypy strict.
- Prose and identifiers in English — this repo is public and read cold by strangers.
- Gate: `uv run ruff check . && uv run mypy bench && uv run pytest`.
