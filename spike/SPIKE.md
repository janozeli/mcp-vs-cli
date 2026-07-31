# Spike — running the arms inside a stock harness

**Question.** The benchmark measures how capabilities are exposed to an agent. Measuring that inside
a loop we wrote means every quirk of our loop is a confound — which has already happened four times
([arm-symmetry](../.claude/reference/arm-symmetry.md)). Could the arms instead be *installed* into a
complete, off-the-shelf harness, with us supplying only configuration and telemetry?

This file reports what was observed. It does not choose. Dated 2026-07-31.

## pi

[`@earendil-works/pi`](https://github.com/earendil-works/pi) 0.83.0, MIT.

Observed:

- System prompt reported under 1,000 tokens; extensions documented as possible without forking.
- Per-turn `Usage` carries `input`, `output`, `cacheRead`, `cacheWrite`, `reasoning` and a cost
  breakdown — more than the loop in `bench/agent.py` collects today.
- **No MCP support.** No mention in `pi-agent-core` or `pi-coding-agent`, and no MCP SDK in the
  dependency tree; the only textual match in the published package is inside a vendored
  `highlight.js`. `AgentContext` takes `tools` directly.

What that implies is a choice, not a fact: an MCP arm on pi means supplying the MCP client, which
may be acceptable as an extension or may be the hand-crafting this spike set out to avoid.

## Goose

[Goose](https://github.com/block/goose) 1.45.0, Apache 2.0. Windows binary from the GitHub release,
run against OpenRouter with `deepseek/deepseek-v4-flash`.

Observed:

| flag | behaviour |
| --- | --- |
| `--with-extension <cmd>` | installs a stdio MCP server; the agent listed and called its tools |
| `--no-profile` | loads nothing else; measured floor of **382 input tokens** for a trivial prompt |
| `--output-format json` | full message list plus `input_tokens`, `output_tokens`, cache counters, `cost_usd` |
| `--max-turns`, `--no-session`, `--provider` | turn ceiling, batch runs, provider override |

`camara_mcp.py` generates the server from `bench/spec.py`, synthesising one function signature per
operation so the SDK derives the JSON Schema rather than us writing it.

End to end on task 1, all 78 operations installed:

```
answer   JOSE ABILIO SILVA DE SANTANA        correct
tokens   48,070 in · 113 out · $0.0045       1 tool call, 2 assistant turns
```

## The measurement that is independent of any choice

A real MCP server renders larger than `bench/arms/mcp.py` says:

| | tokens for 78 operations |
| --- | ---: |
| `bench/arms/mcp.py` | 16,712 |
| real server, as the SDK renders it | 20,411 |
| the same, with `output_schema` | 23,188 |

Mostly optionality: the SDK writes `anyOf: [T, null]` where our emitter writes a bare type. On task
1 the full stack spent 48,070 input tokens against 42,181 in our own loop, **+14%**.

**This holds regardless of which harness is chosen, and it goes against the direction the published
figures argue.** Our static numbers understate a real MCP server.

## Not answered

- **Per-turn telemetry.** `--output-format json` aggregates the run. `stream-json` and the session
  JSONL were not examined, and `peak_context` cannot be computed without per-turn numbers.
- Whether the CLI and baseline arms install as cleanly as the MCP one.
- Whether Goose's tool-loading behaviour is configurable, or simply what it is.
- Nothing was tried beyond these two. OpenCode, OpenHands and the platform agents were not
  installed.

## What a decision would rest on

- Accepting a harness means giving up disclosure as a controlled variable: the harness decides when
  it loads tools. That is the price of asking "what does a user actually pay" instead of "what does
  the mechanism cost".
- Keeping our own loop keeps the axes, and keeps the confound the four symmetry failures came from.
- A third option was not explored: keep the loop for the mechanism study and use a harness only to
  calibrate it, reporting the gap.
