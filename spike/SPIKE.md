# Spike — can a stock harness run the arms?

**Question.** The benchmark measures how capabilities are exposed to an agent. Measuring that inside
a loop we wrote ourselves means every quirk of our loop is a confound — which has already happened
four times ([arm-symmetry](../.claude/reference/arm-symmetry.md)). Can the arms instead be *installed*
into a complete, off-the-shelf harness, so that the experiment is "a user just installed an MCP
server / a CLI", with us supplying only configuration and telemetry?

**Answer: yes, with Goose. No, with pi.** Dated 2026-07-31.

## What was tried

### pi — rejected

[`@earendil-works/pi`](https://github.com/earendil-works/pi) is the closest thing to the ideal
harness on paper: MIT, a system prompt under 1,000 tokens, extensions without forking, and per-turn
`Usage` carrying `input`, `output`, `cacheRead`, `cacheWrite`, `reasoning` and cost — better
telemetry than the loop we hand-rolled.

It has **no MCP support**. Not in `pi-agent-core`, not in `pi-coding-agent`, and no MCP SDK in its
dependency tree; the only match for "mcp" in the published package is inside a vendored
`highlight.js`. `AgentContext` takes `tools` directly, so an MCP arm would mean writing the MCP
client ourselves — which is exactly the hand-crafting this spike exists to avoid.

### Goose — works

[Goose](https://github.com/block/goose) 1.45.0, Apache 2.0, Windows binary from the GitHub release.
Every extension is an MCP server, which makes the MCP arm literally an installation. The flags that
matter turned out to be purpose-built for this:

| flag | why it matters here |
| --- | --- |
| `--with-extension <cmd>` | installs a stdio MCP server — this *is* the MCP arm |
| `--no-profile` | loads nothing else, so the arms do not inherit stray built-in tools |
| `--output-format json` | messages plus `input_tokens`, `output_tokens`, cache counters, `cost_usd` |
| `--max-turns` | the turn ceiling, per arm |
| `--no-session` | for batch runs |
| `--provider` | so the model is not confounded with the harness |

`camara_mcp.py` generates the server from `bench/spec.py`, synthesising one function signature per
operation so the SDK derives the JSON Schema. The schema the harness sees is still generated from
the registry — invariant 1 survives the move.

## What it found

**A real MCP server costs 22% more than our emitter said.**

| | tokens for 78 operations |
| --- | ---: |
| `bench/arms/mcp.py` (our emitter) | 16,712 |
| real server, as the SDK renders it | 20,411 |
| the same, with `output_schema` | 23,188 |

The gap is mostly optionality: the SDK writes `anyOf: [T, null]` where our emitter writes a bare
type. Our published static figures understate a real MCP server.

**End to end, on task 1, with all 78 operations installed:**

```
answer   JOSE ABILIO SILVA DE SANTANA        correct
tokens   48,070 in · 113 out · $0.0045       1 tool call, 2 assistant turns
```

Against 42,181 prompt tokens for the same task and arm in our own loop: **+14%**, from the more
verbose schemas plus Goose's own prompt floor, which `--no-profile` puts at **382 tokens** — small
enough not to swamp what is being measured.

## What it means

The ecological framing produces a *higher and more honest* number than the loop we wrote, and the
three arms map onto installations rather than code paths:

- **mcp** — `--with-extension` pointing at the generated server
- **cli** — `--with-builtin` shell, with the generated binary on `PATH`
- **baseline** — `--with-builtin` shell, and nothing else

What is given up is control of disclosure: the harness decides when it loads tools. That is the
price of the framing, and it is the right price to pay for a question phrased as "what does a user
actually pay".

## Not yet answered

- Per-*turn* telemetry. `--output-format json` aggregates the run; `stream-json` and the session
  JSONL were not examined, and peak context needs per-turn numbers.
- Whether the CLI and baseline arms are as clean to install as the MCP one.
- Whether Goose's tool-loading behaviour is configurable, or simply what it is.
