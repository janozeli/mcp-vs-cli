# Symmetry of affordance

**Layer 3 — stable constraint. Loaded by every contract that changes what an arm can reach.**

> Any capability offered to one arm must be equally discoverable and equally idiomatic in the
> others. Where it cannot be, the asymmetry is declared and reported.

## Why this exists

It is not a principle someone admired in the abstract. It is the residue of the same mistake made
four times, each one caught only after it had already produced a published number.

| # | What was built | How it favoured one side | How it was caught |
| --- | --- | --- | --- |
| 1 | `tool_search` returned five full schemas per keyword query | charged the MCP format a schema for every guess, while `--help` cost one flat listing to browse | comparing tool-output tokens across cells |
| 2 | an exact tool name still required spelling `select:` | punished a model for having read the index it was given; cost two turns in every indexed trial | reading the trace's tool-call arguments |
| 3 | the system prompt told CLI cells to run `--help` "first" and gave them a syntax template, while telling MCP cells only that tools could be searched | unequal scaffolding presented as a property of the format | the user read the prompts |
| 4 | the projection parameter was named `_jq` | a leading underscore reads as private in every convention a model has seen; the cell never used the capability it had | noticing the filtered cell's output was identical to the unfiltered one |

Three of the four were found by inspecting an intermediate artifact rather than by a test. The
fourth was found by a human reading the configuration. **No test in this repo would have caught any
of them**, because each was a correct implementation of a biased design.

## What the constraint demands

Before adding or changing any affordance, answer all three in writing:

1. **Does every arm have this capability?** If not, say which cannot have it and why the absence is
   structural rather than an omission. A capability the `raw` arm cannot have is a finding about
   documentation, not a defect.
2. **Is it equally discoverable?** Compare what each arm must do to learn the capability exists.
   "It is in the tool description" and "it is in the manual" are equivalent; "it is in the tool
   description" and "the model already knows this from pretraining" are not.
3. **Is it equally idiomatic?** Prefer a mechanism the model has read a great deal of. Where the two
   arms must differ, give them the same *language* even when the delivery differs — this is why the
   CLI pipe and the tool parameter both take jq, rather than jq on one side and a bespoke field
   selector on the other.

## The confound that cannot be removed

Models have read enormous amounts of `--help` and `| jq`. `tool_search` with a `select:` form is a
protocol invented here and learned in-context. Part of what "CLI format" measures is prior exposure.

This is not fixable inside the experiment, and it should not be quietly compensated for by
handicapping the CLI. It is declared in the README's caveats, and it is arguably a real advantage of
the format rather than an artifact of the harness.

## Declared asymmetries

Standing differences that cannot be removed without changing what an arm *is*. Declared here and
reported with results, per the constraint above.

- **The MCP server process runs on the host, outside the jail.** Every arm's `bash` runs through
  the identical ai-jail wrapper, set once in the harness. But the `mcp` arm's server is spawned by
  the MCP client — pi's adapter — on the host, exactly as a real installation works: the boundary
  difference is structural to MCP's client-spawns-server design, not an omission. All arms reach
  the API over the same open network, so the affordance itself stays symmetric.
- **`.mcp.json` sits in the mcp arm's working directory.** It is that arm's honest installation
  artifact — a real MCP user has one in the project — but it is also a file the other arms' cwds
  do not contain. Inside the jail the repository path it names does not exist, so listing it
  discloses nothing reachable.

## Failure mode to watch for

The tempting repair is to tune the disadvantaged arm until the numbers look fair. That is how bias
enters in the opposite direction, and it happened here: after fixing (1) and (2), the MCP format's
discovery had been optimised while the CLI's result handling had not, and the comparison was tilted
for two runs before the pipe was implemented.

When one side gets an improvement, ask what the equivalent improvement on the other side would be,
and either build it in the same change or record the debt.
