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

Handling = Literal["whole", "filtered"]

HANDLINGS: tuple[Handling, ...] = ("whole", "filtered")
"""What happens to a response on its way into the context.

`whole` is the default almost every MCP server ships: the object comes back entire. `filtered` lets
the agent reduce it first — the CLI through a `| jq` pipe, the MCP format through a projection
parameter on the tool itself.

The two are given the *same* filter language on purpose. A CLI that could pipe to `jq` while the
tools offered some bespoke field selector would be measuring which syntax the model knows better,
and `jq` is the one it has actually read a lot of. The `mcp/filtered` cell is not a straw man
either: it is the well-designed server, and the strongest form of the argument for MCP.
"""

OBJECTIVE = "Answer the user's question using the tools available to you. Reply with the final value only."
"""The system prompt, byte-identical in all six cells.

It states the goal and nothing else. A prompt that also explained *how* to use the tools would stop
being a constant of the experiment and become part of the treatment — and telling one cell to "run
`--help` first" while telling another only that tools "can be searched" is not the same amount of
help. Every mechanism now lives in the tool descriptions, which are part of the surface under test
and already counted in tokens. Catalogues still ride in the prompt, but as data, which is precisely
what is being measured.
"""
