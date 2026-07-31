# mcp-vs-cli

**What does an MCP server cost you in context, and what do you get back for it?**

Connecting an MCP server can put every one of its tool schemas into the request before the model has
read a word of your task, and most servers hand back whole response objects once it starts working.
Give the agent a CLI instead and it starts from nothing — but it spends turns on `--help`.

That trade gets argued about constantly and measured rarely. This repo measures it against a real
public API, live, with every request and response kept on disk so the numbers can be recomputed by
someone who does not trust them.

**Nothing about the API is cached.** No recorded corpus, no fixtures standing in for real responses:
every trial reaches the service as it is at that moment, which is what an agent in the wild does,
and ground truth is solved live in the same window as the trial it grades. The cost is stated rather
than engineered away — see *Caveats*.

## The comparison people actually mean

"MCP vs CLI" bundles together choices that are independent, and the bundling is where the argument
goes wrong. Modern clients defer tool loading; a CLI's manual can just as easily be pasted into the
system prompt; and a well-designed server can project its responses. So the design separates three
factors instead of confounding them:

| factor | levels | paid |
| --- | --- | --- |
| **format** | JSON Schema, or help text | — |
| **disclosure** | `eager` (all up front), `indexed` (names up front), `lazy` (nothing) | once |
| **result handling** | `whole`, or `filtered` before it reaches the context | **every call** |

Everything is generated from the same OpenAPI document, so a difference between cells is a
difference of exposure and never of capability — enforced by tests that compare the surfaces
operation by operation and parameter by parameter. Both filtering cells get the *same* filter
language (jq), so the comparison is about where filtering happens rather than which syntax the model
knows. The `mcp/filtered` cell is the well-designed server, not a straw man.

**The subject.** [Dados Abertos da Câmara dos Deputados](https://dadosabertos.camara.leg.br/swagger/api.html),
the Brazilian Chamber of Deputies' open-data API: OpenAPI 3.0.1, 78 operations across 11 tag groups,
no authentication, real relational data. Chosen for size — enough operations to scale N over a real
curve — and for obscurity at the record level: a model cannot answer *which deputy filed which bill*
from memory, so the arms have to use the tools. The OpenAPI document is vendored under
[`data/specs/`](data/specs) with its source URL, fetch date and sha256, because every arm is
generated from it. The API's *responses* are not vendored anywhere.

## Static result: disclosure dominates format

Token counts for what each cell holds before the task is read (`o200k_base`), from
`uv run python -m bench.measure`:

| arm | 5 ops | 10 | 20 | 40 | 78 |
| --- | ---: | ---: | ---: | ---: | ---: |
| mcp/eager | 690 | 1,740 | 3,704 | 7,944 | 16,974 |
| mcp/indexed | 262 | 389 | 617 | 1,094 | 1,929 |
| mcp/lazy | 127 | 127 | 127 | 127 | 127 |
| cli/eager | 819 | 1,886 | 3,815 | 7,965 | 16,737 |
| cli/indexed | 287 | 399 | 597 | 1,014 | 1,735 |
| cli/lazy | 131 | 131 | 131 | 131 | 131 |

Holding disclosure fixed, the two formats land within 1.4% of each other at 78 operations. Holding
format fixed, deferring cuts the cost 7–8×. **The row is worth roughly fifty times more than the
column.** That the two eager cells land within 1.4% is also the check on the CLI renderer: a terser
help text would have handed that format a win by construction.

## Run-time result: what a whole payload costs

Five tasks run against the live API, graded programmatically against ground truth solved in the
same window — no LLM judge. Task 4 asks how many São Paulo deputies voted "Sim" in one vote; the
response is 366 nested records and about 150 kB.

Model `deepseek/deepseek-v4-flash`, temperature 0, one trial per cell:

| cell | ok | turns | peak context | prompt Σ | tool output |
| --- | :-: | ---: | ---: | ---: | ---: |
| mcp/eager/whole | ✓ | 2 | 81,566 | 102,467 | 55,499 |
| cli/eager/whole | ✓ | 2 | 80,264 | 99,859 | 55,499 |
| mcp/indexed/whole | ✓ | 4 | 64,307 | 73,145 | 55,938 |
| cli/indexed/whole | ✓ | 3 | 63,005 | 69,831 | 55,499 |
| mcp/indexed/filtered | ✓ | 4 | 64,497 | 73,525 | 56,026 |
| **cli/indexed/filtered** | ✓ | 6 | **5,108** | **26,433** | **2,041** |

**One cell filtered, and it changed the order of magnitude.** Piping to jq cut tool output 27× and
peak context 12×, for the same correct answer, at the cost of three extra turns.

**The other filtering cell had the same capability and did not use it.** `mcp/indexed/filtered` was
handed a projection parameter on every tool, in the same jq syntax, and returned the whole payload
anyway. The plain reading is that `cmd | jq` is idiomatic and a projection argument is an affordance
the model has never seen — a capability the model does not reach for is a capability that is not
there. The less flattering reading is in *Caveats*: the parameter is named `_jq`, and a leading
underscore means "internal" in every convention the model has read.

Notice also what the eager cells bought: nothing. Every cell answered correctly, so the 30k tokens of
schemas made no difference to the outcome and only to the bill.

## Findings withdrawn

Three claims measured here did not survive scrutiny, and are listed because a benchmark that only
publishes what held up is not reporting, it is advertising.

- **"Blind tool search costs 4× an index."** An artefact: the search returned five full schemas for
  every keyword guess. Made to browse by name, `mcp/lazy` went from 34,762 prompt tokens to 4,624 on
  the same task — from the most expensive deferred cell to the cheapest of all six.
- **"An upfront index costs twice a lazy search."** The mechanism is real — anything upfront is
  re-sent every turn — but the measurement was driven by a round trip the harness forced on a model
  that had correctly read the index it was given.
- **Deferred-cell numbers for tasks 1–3.** The harness let those cells call tools they had never
  loaded, which made `indexed` behave as "eager without paying for the schemas". Fixed; those runs
  are being redone. Eager and CLI numbers are unaffected.
- **Every run above predates the move to a live API**, and was made against a frozen corpus that no
  longer exists. They stand as evidence of what the harness did, not as measurements to cite.

Two of the three were found by reading the traces rather than by reasoning about the code.

## Caveats

- **One trial per cell.** Re-running an identical cell on an identical task produced 125,574 and
  102,467 prompt tokens on two attempts — a 22% spread at temperature 0. Nothing here should be read
  as a difference smaller than that until the repeats are in.
- **The `_jq` parameter may be handicapping its own cell.** A leading underscore reads as private.
  The null result above has to be retested with an honest name before it means anything.
- **Familiarity is a confound, and it favours the CLI.** Models have read enormous amounts of
  `--help` and `| jq`; `tool_search` with a `select:` form is a protocol invented here and learned
  in-context. Part of what "CLI format" measures is prior exposure. This is not removable inside the
  experiment — and arguably it is a real advantage rather than an artefact.
- **Two arms can receive different data.** With nothing cached, the API can move between one trial
  and the next. This is not prevented; it is measured. Every response is in the trace, and
  `scripts/verify_parity.py` reports any request that two arms made and got different bytes for. A
  run whose parity check is dirty is reported as such rather than quietly averaged.
- **A past run cannot be re-executed by anyone, including us.** Auditing survives — the traces hold
  the exact responses, so any published figure can still be recomputed and disputed. Re-collection
  does not. That is the price of not keeping a copy of someone else's data, and it is the trade this
  project chose deliberately.
- **Static counts are estimates.** Computed offline with `o200k_base`. Run-time accounting uses the
  provider's own reported usage.
- **Window occupied ≠ dollars.** Caching makes repeated schemas cheap to *bill* without making them
  cheap to *carry*: a cache hit does not give the window back. Reported separately.

## Reproduce

The static half needs no network and no key:

```bash
uv sync && uv run python -m bench.measure
```

The run-time half reaches the live API, and needs an [OpenRouter](https://openrouter.ai/keys) key in
`.env` (see `.env.example`):

```bash
uv run python -m scripts.check_ground_truth
uv run python -m scripts.pilot t4-sao-paulo-yes-votes
```

Then the two checks that replace what a frozen corpus used to guarantee — recompute the numbers from
the traces alone, and confirm the arms saw the same data:

```bash
uv run python -m scripts.summarise runs && uv run python -m scripts.verify_parity
```

Quality gate:

```bash
uv run ruff check . && uv run mypy bench && uv run pytest
```

## Method notes

- **Names.** The spec's own `operationId`s are unusable as tool names (`search`, `listar`,
  `listar_1`). Every cell gets names from one mechanical transform over method and route, applied
  identically so it cannot favour a format. Resource nouns stay in the API's own Portuguese.
- **The prompt states an objective, never a procedure.** One sentence, byte-identical in all six
  cells. Mechanism lives in the tool descriptions, where it is part of the surface under test and
  counted in tokens. An earlier version told the CLI cells to run `--help` "first" and gave them a
  syntax template while telling the MCP cells only that tools could be searched; that is not a
  constant of the experiment, and it showed up in the results as if it were a property of the format.
- **Namespacing is counted.** MCP clients prefix tools by server (`camara__list_deputados`).
- **Transport parameters are hidden.** The spec declares an `Accept` header on all 78 operations;
  exposing it would let the agent request XML and break parsing for reasons unrelated to the
  comparison. Filtered once, in the registry, so every cell inherits it.
- **Errors are data.** `/votacoes/{id}/votos` answers 400 to `itens`, and recovering from that is
  half of what one task measures. An error response is returned to the agent, never swallowed.
- **A response that did not arrive is never invented.** With nothing cached behind it, it is simply
  gone, and the trial aborts.
- **The tests do not touch the network.** They check this repository against hand-written payloads in
  `tests/conftest.py` — a stub, not a recording, and deliberately not the real values. Whether the
  world still says what the tasks expect is a separate, live question, asked by
  `scripts/check_ground_truth.py`. A suite that fails for external reasons is a suite people learn
  to ignore.
- **Provider capacity errors are retried, not scored.** Free endpoints answer HTTP 200 with
  `choices: null` when they are out of workers. A trial that landed on a busy worker says nothing
  about the arm it was measuring.

## Status

- [x] OpenAPI → operation registry, every cell generated from it
- [x] Static context cost across the design and across N
- [x] Live API access with no stored responses anywhere, and parity measured after the fact
- [x] Five tasks with ground truth solved live in the same window as the trial
- [x] Agent loop with full request/response traces
- [x] Result-handling axis (whole vs filtered)
- [ ] Re-run everything against the live API; the published numbers above predate it
- [ ] Repeats, to get past the 22% single-trial spread
- [ ] Retest the projection parameter under a name that does not read as private
- [ ] Task 5, and the second model tier
