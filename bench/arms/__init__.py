"""Emitters that turn the operation registry into the surface an agent actually sees.

Every arm is generated from the same `Registry`, so the arms can differ in how capabilities are
exposed but never in which capabilities exist.

Exposure is two independent choices, not one. The *format* is how a capability is described — a JSON
Schema or a page of help text. The *disclosure* is when that description enters the context:

- `eager`   — everything up front: all schemas, or the whole manual.
- `indexed` — names and one-line summaries up front, full descriptions on request.
- `lazy`    — nothing up front; even the catalogue costs a round trip.

Crossing the two gives six arms. Treating "MCP" as a synonym for `eager` is the mistake this design
exists to avoid: current clients defer tool loading, and a CLI can just as easily be preloaded.
"""

from typing import Literal

Disclosure = Literal["eager", "indexed", "lazy"]

DISCLOSURES: tuple[Disclosure, ...] = ("eager", "indexed", "lazy")

OBJECTIVE = "Answer the user's question using the tools available to you. Reply with the final value only."
"""The system prompt, byte-identical in all six cells.

It states the goal and nothing else. A prompt that also explained *how* to use the tools would stop
being a constant of the experiment and become part of the treatment — and telling one cell to "run
`--help` first" while telling another only that tools "can be searched" is not the same amount of
help. Every mechanism now lives in the tool descriptions, which are part of the surface under test
and already counted in tokens. Catalogues still ride in the prompt, but as data, which is precisely
what is being measured.
"""
