# Spike — running the arms inside a stock harness

**Question.** The benchmark measures how capabilities are exposed to an agent. Measuring that inside
a loop we wrote means every quirk of our loop is a confound — which has already happened four times
([arm-symmetry](../.claude/reference/arm-symmetry.md)). Could the arms instead be *installed* into a
complete, off-the-shelf harness, with us supplying only configuration and telemetry?

This file reports what was observed. It does not choose. Dated 2026-07-31.

## Two corrections to earlier versions of this file

**pi does have MCP.** An earlier version said it did not. Three packages were inspected and a claim
was made about the project; pi is lean by design, so absence from the core says nothing about
absence from pi. [`pi-mcp-adapter`](https://pi.dev/packages/pi-mcp-adapter) is on npm (unscoped,
v2.16.0), installs with `pi install npm:pi-mcp-adapter`, reads standard `.mcp.json`, speaks stdio.

**The first pi numbers were contaminated and are withdrawn.** `--no-builtin-tools` keeps *extension*
tools, and the machine's own globally installed pi extensions came with them — `web_search`,
`fetch_content`, `resolve-library-id`, `subagent` and others, plus an attempt to reach an unrelated
MCP server from the user's global config. The contamination was noticed and the numbers were
tabulated anyway, which is worse than not noticing.

Isolation turned out to be simple: point `HOME` and `USERPROFILE` at an empty directory. Everything
below is from isolated runs.

## What each stack did with task 1

All three answered correctly. All three had the same 78 operations available.

| stack | how the operations are exposed | peak context | turns | tool calls |
| --- | --- | ---: | ---: | ---: |
| `bench/agent.py` (ours) | 78 schemas, eager | 21,292 | 2 | 1 |
| Goose + generated MCP server | 78 schemas, eager | aggregate only | 2 | 1 |
| pi + `pi-mcp-adapter`, isolated | one `mcp` proxy, search then call | **3,640** | 4 | 3 |

pi, per turn:

| turn | input | cacheRead | context carried | output |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 986 | 0 | 986 | 101 |
| 2 | 561 | 2,391 | 2,952 | 79 |
| 3 | 3,122 | 0 | 3,122 | 84 |
| 4 | 3,640 | 0 | 3,640 | 12 |

For scale: the same run *before* isolation peaked near 33,135. The machine's own configuration was
contributing roughly 29,000 tokens of context to every turn.

## What that shows, and what it does not

**pi and Goose ship opposite defaults on the disclosure axis.** Goose installs an MCP server as N
tools; pi's adapter installs it as one proxy with a search form and a call form, so the schemas
never enter the context. The axis this project treats as its central finding separates two shipped
products, not two configurations we invented — which also means **choosing a harness silently picks
a disclosure level**.

**A caution on reading the table.** One trial each. And the three stacks report cache differently —
pi reports `input` excluding cache reads, Goose reports an OpenRouter aggregate, `bench/agent.py` a
third convention. `peak context` above is `input + cacheRead` for pi and prompt tokens for ours;
reconciling that properly is a prerequisite for any published comparison and is not done.

An earlier reading of a tool listing was also wrong: the model enumerating 78 `camara_*` names was
reporting what the proxy's *search* returned, not what was in its context. The tool calls in the
trace are all `mcp`.

## The measurement that is independent of any of this

Generating a real MCP server from `bench/spec.py` (`camara_mcp.py`, signatures synthesised per
operation so the SDK derives the schema — invariant 1 survives the move) shows our emitter
understates a real server:

| | tokens for 78 operations |
| --- | ---: |
| `bench/arms/mcp.py` | 16,712 |
| real server, as the SDK renders it | 20,411 |
| the same, with `output_schema` | 23,188 |

Mostly optionality: the SDK writes `anyOf: [T, null]` where our emitter writes a bare type. **This
holds whichever harness runs it, and it goes against the direction the published figures argue.**

## Practical notes

- Goose: `--with-extension` installs a stdio MCP server, `--no-profile` drops everything else,
  `--output-format json` carries `input_tokens`/`output_tokens`/cache/`cost_usd` for the run,
  `--max-turns`, `--no-session`, `--provider`. Floor with `--no-profile`: **382 input tokens**.
- pi: `--print --mode json` emits a per-turn event stream with `input`, `output`, `reasoning`,
  `cacheRead`, `cacheWrite` and cost per assistant message. `--system-prompt` sets the prompt
  outright, `--no-builtin-tools` keeps extension tools only, `--no-tools` drops everything,
  `--approve` is required for project-local packages. Isolation needs `HOME`/`USERPROFILE`.

## Not answered

- Reconciling cache accounting across stacks, without which the table above is indicative only.
- Per-turn telemetry from Goose: `--output-format json` aggregates; `stream-json` and the session
  JSONL were not examined.
- Whether the CLI and baseline arms install as cleanly as the MCP one, on either.
- Whether either harness's disclosure behaviour is configurable, or simply what it is.
- Nothing beyond these two was tried. OpenCode, OpenHands and the platform agents were not installed.

## What a decision would rest on

- Accepting a harness means giving up disclosure as a controlled variable. Given that pi and Goose
  differ precisely there, the choice of harness *is* a choice of disclosure level.
- Keeping our own loop keeps the axes, and keeps the confound the four symmetry failures came from.
- A third option, unexplored: keep the loop for the mechanism study and use a harness only to
  calibrate it, reporting the gap.
