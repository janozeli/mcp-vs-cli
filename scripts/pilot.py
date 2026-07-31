"""A pilot run: one task across all six cells, in record mode.

The first contact with a real model has to be able to record, because an agent explores and will ask
for calls no solver ever needed. Once the corpus covers what agents actually try, it is frozen and
the published runs replay it, so every cell sees the same bytes.

    uv run python -m scripts.pilot                            # t1 across the triad
    uv run python -m scripts.pilot t4-sao-paulo-yes-votes     # one task, all three
    uv run python -m scripts.pilot t1-civil-name baseline     # one task, one arm
"""

from __future__ import annotations

import sys
from pathlib import Path

from openai import OpenAI
from rich.console import Console
from rich.table import Table

from bench import config, spec, tasks, triad
from bench.agent import run_trial
from bench.replay import Cassette

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"
CASSETTES = ROOT / "data" / "cassettes"
RUNS = ROOT / "runs"

def _arms(selector: str) -> list[triad.Arm]:
    """`triad` for level zero, or a single arm by key."""
    if selector == "triad":
        return list(triad.TRIAD)
    return [triad.by_key(selector)]


def main() -> None:
    task = tasks.by_id(sys.argv[1]) if len(sys.argv) > 1 else tasks.TASKS[0]
    arms = _arms(sys.argv[2] if len(sys.argv) > 2 else "triad")
    registry = spec.load(SPEC)
    cassette = Cassette(CASSETTES, base_url=registry.base_url, mode="record")
    client = OpenAI(base_url=config.OPENROUTER_BASE_URL, api_key=config.api_key())

    console = Console()
    console.print(f"[bold]{task.id}[/] — {task.question}")
    console.print(f"expecting [green]{task.answer!r}[/], model [cyan]{config.MODEL}[/]\n")

    trace_dir = RUNS / "pilot" / task.id
    results = []
    for arm in arms:
        console.print(f"  running [bold]{arm.key}[/] ({arm.fmt}/{arm.disclosure}/{arm.handling}) …", end="")
        trial = run_trial(
            task,
            fmt=arm.fmt,
            disclosure=arm.disclosure,
            handling=arm.handling,
            registry=registry,
            cassette=cassette,
            client=client,
            trace_dir=trace_dir,
            max_turns=arm.max_turns,
        )
        console.print(" [green]ok[/]" if trial.success else f" [red]{trial.aborted or 'wrong answer'}[/]")
        results.append(trial)

    table = Table(title=f"{task.id} — pilot")
    for column, justify in (
        ("arm", "left"),
        ("ok", "center"),
        ("turns", "right"),
        ("calls", "right"),
        ("upfront", "right"),
        ("peak ctx", "right"),
        ("prompt Σ", "right"),
        ("tool out", "right"),
    ):
        table.add_column(column, justify=justify)
    for trial in results:
        table.add_row(
            trial.arm,
            "[green]yes[/]" if trial.success else "[red]no[/]",
            str(trial.turns),
            str(trial.tool_calls),
            f"{trial.upfront_tokens:,}",
            f"{trial.peak_context:,}",
            f"{trial.prompt_tokens:,}",
            f"{trial.tool_output_tokens:,}",
        )
    console.print()
    console.print(table)

    answers = {t.arm: (t.answer[:60] or t.aborted) for t in results}
    for arm, answer in answers.items():
        console.print(f"  [dim]{arm:<14}[/] {answer}")

    resolved = {m for t in results for m in t.resolved_models}
    console.print(f"\n[dim]models the provider actually used: {', '.join(sorted(resolved)) or 'none'}[/]")
    console.print(f"[dim]traces in {trace_dir.relative_to(ROOT)}[/]")
    console.print(f"[dim]cassette now holds {len(cassette)} calls ({cassette.recorded} new)[/]")


if __name__ == "__main__":
    main()
