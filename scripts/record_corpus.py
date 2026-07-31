"""Fill the cassette by running every task's solver against the live API.

Run this deliberately, rarely, and never as part of a benchmark run:

    uv run python -m scripts.record_corpus

It covers the happy path — the calls a correct agent must make. An agent that explores, guesses a
parameter or takes a wrong turn will ask for calls that are not here; those are recorded during a
pilot run, after which the corpus is frozen again and every arm replays the same bytes.
"""

from __future__ import annotations

from pathlib import Path

from bench import spec, tasks
from bench.replay import Cassette

ROOT = Path(__file__).resolve().parents[1]
CASSETTES = ROOT / "data" / "cassettes"
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"


def main() -> None:
    registry = spec.load(SPEC)
    cassette = Cassette(CASSETTES, base_url=registry.base_url, mode="record")

    print(f"recording into {CASSETTES.relative_to(ROOT)} from {registry.base_url}\n")
    for task in tasks.TASKS:
        answer = task.solver(cassette)
        verdict = "matches" if task.check(str(answer)) else "DIFFERS FROM PINNED"
        print(f"  [{task.difficulty}] {task.id:<28} -> {answer!r}  ({verdict}: {task.answer!r})")

    print(f"\n{len(cassette)} calls in the cassette ({cassette.recorded} new, {cassette.hits} reused)")


if __name__ == "__main__":
    main()
