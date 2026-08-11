# Contract — turn traces into a published claim

## Inputs

- Layer 3: `CLAUDE.md` invariant 4
- Layer 4: `runs/` — the traces the claim rests on
- Layer 4: the aggregate from pi's own accounting, never a number remembered from a terminal

## Process

One transformation: a measurement becomes a claim, with its confidence attached.

1. Recompute from the traces. If pi's own accounting cannot produce the number, it is not
   publishable, whatever the run printed at the time.
2. State the resolution before the result. The 22% single-trial spread bounds every claim in the
   repo, so it belongs above them, not in a footnote.
3. Say what a claim depends on. A figure that assumes the harness is unbiased has to say so — three
   findings here were artifacts of the harness, and each looked clean until someone read a trace.
4. Withdraw in public. A claim that does not survive goes to the README's *Findings withdrawn* with
   why it fell, not into a silent edit. A benchmark that publishes only what held up is advertising.
5. Separate window from money. Caching makes repeated schemas cheap to bill without making them
   cheap to carry; a cache hit does not give the window back. Report `peak_context` and
   `prompt_tokens` as different things, because conflating them is how this argument usually goes
   wrong.
6. Name what the result does not show. Every task run so far has been answered correctly by every
   cell — there is a cost difference and no accuracy difference, and saying so is part of the result.

## Outputs

- the claim in `README.md`, with its caveat
- any withdrawal in *Findings withdrawn*
- `results/*.json` for figures that are recomputable offline

## Acceptance

- every number in the README traces to a committed aggregate or a reproducible command
- no claim rests on a difference smaller than the measured spread
- the caveats section still lists the confounds that have not been removed

## What this prevents

Publishing the harness's bias as a property of a format, and quietly deleting the findings that did
not work out.
