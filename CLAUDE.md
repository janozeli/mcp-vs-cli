# mcp-vs-cli

A benchmark measuring what it costs to expose a set of capabilities to an LLM agent, and what each
way of doing it buys back.

Exposure is three independent factors: **format** (JSON Schema vs. help text), **disclosure**
(eager / indexed / lazy), and **result handling** (whole vs. filtered). Collapsing them into "MCP vs
CLI" is the mistake the design exists to avoid — clients defer tool loading, and a manual can be
preloaded. The first two are paid once, the third on every call.

## Invariants

These are what make the numbers mean anything. Breaking one silently invalidates the experiment.

1. **One source of truth.** `bench/spec.py` turns an OpenAPI document into a `Registry` of
   `Operation`s. Every cell is *generated* from that registry. Never hand-write a tool schema or a
   CLI subcommand — if the cells can drift, the experiment compares implementations instead of
   exposure. Deferring a description must never hide a capability.
2. **Identical responses across arms.** All API access goes through the record-replay cache. A trial
   never touches the network. Two arms running the same task must see byte-identical payloads.
3. **Determinism.** Fixed seeds, temperature 0, sorted iteration order. Operation sampling for the
   N-scaling axis goes through `Registry.sample(n, keep=..., seed=...)`, never ad-hoc slicing.
4. **Auditable accounting.** Every request and response is written to JSONL with the exact wire
   payload and the provider's native usage numbers. Any published figure must be recomputable from
   `runs/` alone, by someone who does not trust us.
5. **No LLM judges.** Task success is decided by comparing against ground truth computed from the
   frozen snapshot.

## Layout

- `bench/spec.py` — OpenAPI → `Registry` (the source of truth)
- `bench/arms/` — emitters, one module per format; each takes a `Disclosure`
- `bench/design.py` — the crossing, and what each cell costs in context
- `bench/measure.py` — the static half of the experiment (`uv run python -m bench.measure`)
- `data/specs/` — vendored API specs with provenance (`*.meta.json`: source URL, fetch date, sha256)
- `runs/` — raw JSONL traces (gitignored; results are committed as aggregates)

## Conventions

- Python 3.12+, uv, ruff (`E,F,W,I,UP,B,SIM,RUF`), pytest, mypy strict.
- Prose and identifiers in English — this repo is public and read cold by strangers.
- `uv run pytest`, `uv run ruff check`, `uv run mypy bench`.
