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

# Calls no correct solution needs, but a real agent will make anyway: the obvious wrong turns and the
# obstacles the tasks are built around. Recording them keeps a replayed trial from dying on the first
# mistake, and keeps the API's own error responses in the corpus where the experiment can see them.
WRONG_TURNS: tuple[tuple[str, dict[str, object], str], ...] = (
    (
        "/votacoes/2400758-37/votos",
        {"itens": 600},
        "the endpoint answers 400 to `itens`; recovering from it is half of t4",
    ),
    (
        "/deputados/104552/despesas",
        {"ano": 2024, "mes": 3},
        "the un-paginated 15 of 24 records: what t3 looks like when the trap is not noticed",
    ),
    ("/deputados", {"siglaUf": "AC"}, "t2 without raising the page size"),
    ("/deputados", {"nome": "Socorro Neri"}, "t3's lookup without narrowing by state"),
)


def main() -> None:
    registry = spec.load(SPEC)
    cassette = Cassette(CASSETTES, base_url=registry.base_url, mode="record")

    print(f"recording into {CASSETTES.relative_to(ROOT)} from {registry.base_url}\n")
    for task in tasks.TASKS:
        answer = task.solver(cassette)
        verdict = "matches" if task.check(str(answer)) else "DIFFERS FROM PINNED"
        print(f"  [{task.difficulty}] {task.id:<28} -> {answer!r}  ({verdict}: {task.answer!r})")

    print("\nwrong turns and obstacles:")
    for path, params, why in WRONG_TURNS:
        recorded = cassette.get(path, params)
        print(f"  {recorded.status}  {path:<38} {why}")

    print(f"\n{len(cassette)} calls in the cassette ({cassette.recorded} new, {cassette.hits} reused)")


if __name__ == "__main__":
    main()
