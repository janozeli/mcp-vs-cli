"""The unoptimised triad: what each of the three formats looks like before anyone tunes it.

This is level zero of the ladder, and it is a deliberate choice rather than a limitation. Every
optimisation the project goes on to measure is a delta against these three, so they have to be the
honest defaults — what you get without thinking about it:

- **baseline** — an HTTP verb and a base URL. No documentation of any kind.
- **mcp** — every schema declared on connect, responses returned whole. This is the off-the-shelf
  server, not a caricature of one.
- **cli** — one command tool, discovery through `--help`, responses returned whole. Nobody pastes a
  manual into a system prompt unprompted.

The variants already implemented elsewhere in this package — deferred loading, a preloaded manual,
result filtering — are not part of this level. They are the optimisation catalogue, and their value
is only legible as a distance from here.
"""

from __future__ import annotations

from dataclasses import dataclass

from bench.arms import Disclosure, Handling


@dataclass(frozen=True, slots=True)
class Arm:
    """One configuration to run, with the turn ceiling it needs to be judged fairly."""

    key: str
    fmt: str
    disclosure: Disclosure
    handling: Handling
    max_turns: int
    why: str


TRIAD: tuple[Arm, ...] = (
    Arm(
        key="baseline",
        fmt="raw",
        disclosure="lazy",
        handling="whole",
        # Blind discovery needs room. Cut it at the same ceiling as the documented arms and the
        # result would measure the ceiling instead of the arm; running out of turns here is a
        # finding, and it is recorded as one.
        max_turns=30,
        why="an HTTP verb and a base URL: the price tag on having no documentation at all",
    ),
    Arm(
        key="mcp",
        fmt="mcp",
        disclosure="eager",
        handling="whole",
        max_turns=12,
        why="the off-the-shelf server: every schema up front, responses whole",
    ),
    Arm(
        key="cli",
        fmt="cli",
        disclosure="lazy",
        handling="whole",
        max_turns=12,
        why="one command tool, discovery through --help, responses whole",
    ),
)


def by_key(key: str) -> Arm:
    for arm in TRIAD:
        if arm.key == key:
            return arm
    raise KeyError(f"unknown arm: {key!r}")
