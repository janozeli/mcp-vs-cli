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
