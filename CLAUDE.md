# mcp-vs-cli — steward configuration

This file configures agents working **on this repository**. It is not about the benchmark's own
pipeline, which is ordinary tested code under `src/`.

Structured after the Interpretable Context Methodology (Van Clief & McDermott, arXiv:2603.16021v2):
identity, then routing, then per-task contracts, with stable constraints separated from run
artifacts. One deviation is deliberate — the host always loads this file and nothing else, so the
constraints that must bind *unconditionally* live here rather than in a reference file that a
contract would have to pull in. Anything that binds conditionally is under `.claude/`.

---

## Layer 0 — Identity

A benchmark measuring what it costs to expose a set of capabilities to an LLM agent, and what each
way of doing it buys back.

**The arms are installations, not code paths.** Every trial runs on
[deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) (dsh), vendored at a pinned
commit and composed in-process from its core packages in `src/harness.ts` — the loop, tool dispatch
and accounting are dsh's; which plugins are mounted is declared in that one file. Every arm gets the
same objective, the same composition and unrestricted `bash`; what differs is only what has been
installed beside it: an MCP server, a binary on `PATH`, or nothing. Measuring exposure inside a loop
we wrote ourselves made every quirk of that loop a confound, which happened four times before a
shipped harness replaced it.

The project is a ladder, not a verdict. `src/triad.ts` is level zero: each format in its honest
untuned default. Everything else is an optimisation, and only means anything as a distance from
there. See [ROADMAP.md](ROADMAP.md).

**What this repo is not.** Not a library, not an agent framework. Nothing here is meant to be
imported. It exists to produce numbers a stranger can recompute.

---

## Layer 1 — Routing

| If the task is… | read | before touching |
| --- | --- | --- |
| adding or changing an arm | [`.claude/contracts/add-arm.md`](.claude/contracts/add-arm.md) | `src/triad.ts`, `src/artifacts/` |
| adding or changing a benchmark task | [`.claude/contracts/add-task.md`](.claude/contracts/add-task.md) | `src/tasks.ts` |
| running trials against a model | [`.claude/contracts/run-trials.md`](.claude/contracts/run-trials.md) | `src/harness.ts`, `src/scripts/` |
| turning results into a published claim | [`.claude/contracts/report-findings.md`](.claude/contracts/report-findings.md) | `README.md` |
| anything that changes what an arm can reach or discover | [`.claude/reference/arm-symmetry.md`](.claude/reference/arm-symmetry.md) | anything |

For work that fits none of these, the invariants below still bind. Say which one governs your change
before making it.

---

## Layer 3 — Invariants

Unconditional. These are what make the numbers mean anything; breaking one silently invalidates the
experiment rather than failing a test.

1. **One source of truth.** `src/spec.ts` turns an OpenAPI document into a `Registry` of
   `Operation`s. Both artifacts — the MCP server and the CLI binary — are *generated* from it. Never
   hand-write a tool schema or a subcommand: if the artifacts can drift, the experiment compares
   implementations instead of exposure.
2. **Prefer the ecosystem to our own code.** `$ref` resolution, seeded sampling, HTTP retry, CLI help
   and jq are all libraries, not ours. This is not tidiness — the CLI's `--help` is a *measured*
   quantity, and while it was hand-rendered it cost 42% less than what commander actually prints,
   quietly flattering that arm. Anything hand-written here is a thing we can accidentally tune.
3. **Nothing about the API is stored for reuse.** No cache, no recorded corpus, no fixtures standing
   in for real responses. Every trial reaches the live API, and ground truth is solved live in the
   same window as the trial it grades. Two arms could in principle receive different data; that is
   measured after the fact rather than prevented, because a freezer only made it invisible. A
   response that did not arrive is never invented.
4. **Determinism where it is ours to have, and honesty where it is not.** Sorted iteration order, and
   sampling through `sample(registry, n, { keep, seed })` rather than ad-hoc slicing. Compaction,
   tool-result pruning, spill and retries stay unmounted in the harness because each would silently
   rewrite what "context" means.
   Model sampling is not pinned: these models reason before answering, so claiming determinism there
   would be a claim the run cannot support. What remains is measured — repeats establish the spread.
5. **Auditable accounting.** Token counts come from the provider's own usage, surfaced by dsh on the
   session log, never from a local tokeniser; dsh's session-level measurement is recorded with its
   own label saying whether it anchored on provider usage or estimated. Any published figure must be
   recomputable by someone who does not trust us.
6. **No LLM judges.** Task success is decided against ground truth solved live, by a solver, in the
   same window as the trial it grades.
7. **Symmetry of affordance.** Any capability offered to one arm must be equally discoverable and
   equally idiomatic in the others. Where it cannot be, the asymmetry is declared and reported, never
   left to show up in the results as if it were a property of the format. This one has been violated
   four times — see [`.claude/reference/arm-symmetry.md`](.claude/reference/arm-symmetry.md).

---

## Layer 4 — Working directories

Run artifacts. Regenerable, never hand-edited, and never cited as evidence of anything except what
the run did.

- `runs/` — per-trial output. Gitignored.
- `bin/` — the compiled CLI artifact, produced by `bun run build:cli`. Gitignored: it is generated.
- `vendor/deepseek-harness`'s `node_modules/` and `lib/` — per-machine build products of the pinned
  submodule, produced by `bun run setup:harness`; the pin itself (the commit) is Layer 3, the build
  is regenerable.

`data/specs/` is **not** Layer 4. It is a frozen reference with provenance (`*.meta.json`: source
URL, fetch date, sha256) — the OpenAPI document, not API data. Both artifacts embed it at build time,
so re-fetching it is a deliberate act that changes what every arm is generated from.

---

## Layout

- `src/spec.ts` — OpenAPI → `Registry` (the source of truth)
- `src/artifacts/mcp-server.ts` — the MCP arm's installable, over stdio
- `src/artifacts/cli.ts`, `cli-main.ts` — the CLI arm's installable, compiled to a binary
- `src/harness.ts` — the dsh composition, mounted once for every arm
- `src/vendor/cordis.mjs` — the one runtime shim into the vendored checkout (see its header)
- `vendor/deepseek-harness` — the harness, a submodule pinned to one commit; `bun run setup:harness`
  builds it
- `src/triad.ts` — level zero: the unoptimised default of each format
- `src/tasks.ts` — the tasks, their live solvers and their drift references
- `src/api.ts` — the only way to the API: live, storing nothing
- `src/filter.ts` — jq, the one filter language both arms get
- `src/measure.ts` — the static half of the experiment
- `src/scripts/` — deliberate, human-run operations

## Conventions

- Bun + TypeScript, strict everywhere (`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`).
- Biome for formatting and linting, `bun test` for tests.
- Prose and identifiers in English — this repo is public and read cold by strangers.
- Gate: `bun run check`.
