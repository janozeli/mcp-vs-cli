# mcp-vs-cli

**What does an MCP server cost you in context, and what do you get back for it?**

Connecting an MCP server can put every one of its tool schemas into the request before the model has
read a word of your task. Handing the agent a CLI instead costs almost nothing up front, but the
agent has to spend turns running `--help` to find out what it can do.

That trade gets argued about constantly and measured rarely. This repo measures it, against a real
public API, reproducibly.

## The comparison people actually mean

"MCP vs CLI" bundles together choices that are independent, and the bundling is where the argument
goes wrong. Modern clients defer tool loading — schemas arrive when the model asks for them — and a
CLI's manual can just as easily be pasted into the system prompt. So the design separates the
factors instead of confounding them:

- **format** — how a capability is described: a JSON Schema, or a page of help text.
- **disclosure** — when that description enters the context.
- **result handling** — whether what comes back enters the context whole, or filtered first.

The first two are about *describing* capabilities and are paid once. The third is about *using*
them, and is paid on every call — which, as the measurements below show, is where the money
actually is.

|  | **MCP format** (JSON Schema) | **CLI format** (help text) |
| --- | --- | --- |
| **eager** — everything up front | all schemas declared on connect | the whole manual in the system prompt |
| **indexed** — names up front, detail on request | deferred loading with a tool catalogue | `api --help` preloaded |
| **lazy** — nothing up front | `tool_search` with no catalogue | agent runs `api --help` itself |

Six cells, fully crossed on the first two factors. All six are **generated from the same OpenAPI
document**, so a difference between cells is always a difference of exposure and never of capability
— enforced by tests that compare the surfaces operation by operation and parameter by parameter.

Result handling crosses over that grid again. It is the one place where the difference is
structural rather than conventional: a CLI writes to stdout, so a pipeline can reduce a response
before any of it reaches the context, while a tool call returns an object that lands whole. The
`mcp/filtered` cell is kept anyway, as the upper bound for a well-designed server — it is the
strongest version of the case for MCP, and the case for running code against tools rather than
calling them directly.

**The subject.** [Dados Abertos da Câmara dos Deputados](https://dadosabertos.camara.leg.br/swagger/api.html),
the Brazilian Chamber of Deputies' open-data API: OpenAPI 3.0.1, 78 operations across 11 tag groups,
no authentication, real relational data. Chosen for size — enough operations to scale N over a real
curve — and for obscurity at the record level: a model cannot answer *which deputy filed which bill*
from memory, so the arms have to actually use the tools. The spec is vendored under
[`data/specs/`](data/specs) with its source URL, fetch date and sha256.

## Result: disclosure dominates format

Static token counts (`o200k_base`), from `uv run python -m bench.measure`.

**Occupied before the task is read**, by number of operations exposed:

| arm | 5 | 10 | 20 | 40 | 78 |
| --- | ---: | ---: | ---: | ---: | ---: |
| mcp/eager | 690 | 1,740 | 3,704 | 7,944 | 16,974 |
| mcp/indexed | 262 | 389 | 617 | 1,094 | 1,929 |
| mcp/lazy | 127 | 127 | 127 | 127 | 127 |
| cli/eager | 819 | 1,886 | 3,815 | 7,965 | 16,737 |
| cli/indexed | 287 | 399 | 597 | 1,014 | 1,735 |
| cli/lazy | 131 | 131 | 131 | 131 | 131 |

Up-front cost flatters the lazy cells, because what they defer they still have to fetch — and a
catalogue or a schema that arrives mid-run occupies the window exactly like anything else. So the
honest total is **everything an arm must hold to be ready to call 3 operations**:

| arm | 5 | 10 | 20 | 40 | 78 |
| --- | ---: | ---: | ---: | ---: | ---: |
| mcp/eager | 690 | 1,740 | 3,704 | 7,944 | 16,974 |
| mcp/indexed | 538 | 665 | 914 | 1,493 | 2,340 |
| mcp/lazy | 533 | 660 | 909 | 1,488 | 2,335 |
| cli/eager | 819 | 1,886 | 3,815 | 7,965 | 16,737 |
| cli/indexed | 500 | 612 | 822 | 1,338 | 2,077 |
| cli/lazy | 493 | 605 | 815 | 1,331 | 2,070 |

Three things fall out, at 78 operations:

**Format barely matters.** Holding disclosure fixed, JSON Schema and help text land within 1.4%
(eager) and 13% (deferred) of each other. Whether a capability is described in a schema or in a man
page is close to a rounding error.

**Disclosure matters enormously.** Holding format fixed, going from eager to deferred cuts the cost
by **7.3×** (16,974 → 2,340). The row you pick is worth roughly fifty times more than the column.

**The index is not where the money is.** `indexed` and `lazy` end up within 0.2% of each other
(2,340 vs 2,335): you pay for the catalogue either way, and putting it up front only saves a round
trip. What is expensive is carrying the *detail* of 78 operations to call 3 of them.

So the real question is not MCP versus CLI. It is eager versus deferred — and MCP, in a client that
defers tool loading, costs about what a CLI costs. That is a claim about context only; whether
deferral costs turns or accuracy is measured next.

### Why the numbers should be believed

That the two eager cells land within 1.4% is the check on the CLI renderer: a terser help text would
have handed the CLI format a win by construction. It carries the same information at the same price.

## Preliminary: response payloads dwarf all of this

Everything above is paid once. Response payloads are paid on every call, and most MCP servers return
the whole object. Five realistic calls against the live API, each compared against the smallest
projection that still answers a plausible question about it:

| call | raw | projected | ratio |
| --- | ---: | ---: | ---: |
| deputies from São Paulo | 8,393 | 864 | 10× |
| bills of one type in a year (20) | 2,496 | 675 | 4× |
| votes in a month (20) | 3,626 | 121 | 30× |
| one bill's details | 414 | 56 | 7× |
| one deputy's expenses | 46 | — | empty response, excluded |

**14,929 tokens across four calls, against 1,716 that carry the answer — 8.7×.** For comparison, the
entire eager schema bill for all 78 operations is 16,974. Four raw payloads cost nearly as much as
the whole thing that the schema argument is about — and payloads recur while schemas do not.

Two honest caveats. The projections are mine, written by hand; they are an illustration of the
headroom, not a measurement of what an agent would actually do. And this probe hits the live API, so
the numbers move. Both are why the record-replay cache is the next piece of work — after which this
becomes a fixed corpus, and the projection ratio becomes something the agent has to earn.

Reproduce it (requires network): `uv run python scripts/probe_payloads.py`.

## Reproduce

```bash
uv sync && uv run python -m bench.measure
```

Quality gate:

```bash
uv run ruff check . && uv run mypy bench && uv run pytest
```

## Method notes

- **Names.** The spec's own `operationId`s are unusable as tool names (`search`, `listar`,
  `listar_1`). Every cell gets names from one mechanical transform over method and route
  (`list_proposicoes`, `get_deputados_despesas`), applied identically so it cannot favour a format.
  Resource nouns stay in the API's own Portuguese; only the verb is imposed.
- **Namespacing is counted.** MCP clients prefix tools by server (`camara__list_deputados`). It is
  part of the bill, so it is in the numbers.
- **Transport parameters are hidden.** The spec declares an `Accept` header on all 78 operations;
  exposing it would let the agent request XML and break parsing for reasons unrelated to the
  comparison. Filtered once, in the registry, so every cell inherits it.
- **The lazy cells are modelled conservatively.** `tool_search` is priced as returning the whole
  catalogue. A keyword-filtered search would return less and cost less, so the lazy figures here are
  an upper bound. The run-time experiment issues real queries and measures what actually comes back.
- **Static counts are estimates.** Counted offline with `o200k_base`. Run-time accounting uses the
  provider's own reported usage, recorded per request.
- **Window occupied ≠ dollars.** Prompt caching makes repeated schemas cheap to *bill* without making
  them cheap to *carry*: a cache hit does not give the window back. The two are reported separately.

## Status

- [x] OpenAPI → operation registry, with every cell generated from it
- [x] Static context cost across the 2×3 design and across N
- [x] Preliminary probe of response payload sizes
- [ ] Record-replay cache, so every trial sees byte-identical API responses
- [ ] Task suite with ground truth computed from the frozen snapshot, plus a no-tools control arm to
      detect memorisation
- [ ] Agent loop over OpenRouter with full request/response traces
- [ ] Run-time results: turns, success rate, tool-selection accuracy, latency, cost
