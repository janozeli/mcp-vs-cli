"""Run one task across the arms, through the shared wrapper.

Spike-stage. Every arm goes through `runner.run`, so what differs between them is what was
installed, never how the run was set up.

    uv run python -m spike.run_arms t1-civil-name
    uv run python -m spike.run_arms t1-civil-name --arms baseline,mcp
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table

from bench import config, spec, tasks
from bench.api import Api
from spike.runner import ARMS, run

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "data" / "specs" / "camara-dados-abertos-v2.json"
RUNS = REPO / "runs" / "pi"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="?", default=tasks.TASKS[0].id)
    parser.add_argument("--arms", default="baseline,mcp")
    parser.add_argument("--thinking", default=None, help="off, low, medium, high …")
    parser.add_argument("--fresh", action="store_true", help="discard the previous run directory")
    args = parser.parse_args()

    task = tasks.by_id(args.task)
    registry = spec.load(SPEC)
    console = Console()

    console.print(f"[bold]{task.id}[/] — {task.question}")
    expected = task.solver(Api(registry.base_url, pause=0.2))
    console.print(f"solved live: [green]{expected!r}[/]  ·  model [cyan]{config.MODEL}[/]\n")

    key = config.api_key()
    results = []
    for name in args.arms.split(","):
        arm = ARMS[name.strip()]
        workdir = RUNS / task.id / arm.key
        if args.fresh and workdir.exists():
            shutil.rmtree(workdir)
        console.print(f"  running [bold]{arm.key}[/] ({', '.join(arm.tools)}) …", end="")
        result = run(
            task.question,
            arm,
            model=config.MODEL,
            provider="openrouter",
            api_key=key,
            workdir=workdir,
            thinking=args.thinking,
        )
        ok = task.check(result.answer, expected)
        console.print(" [green]ok[/]" if ok else " [red]wrong[/]")
        results.append((arm, result, ok))

    table = Table(title=f"{task.id} — pi")
    table.add_column("arm")
    table.add_column("ok", justify="center")
    for column in ("turns", "calls", "ctx (pi)", "% janela", "tokens Σ", "peak (nosso)", "cost"):
        table.add_column(column, justify="right")
    for arm, result, ok in results:
        stats = result.stats
        table.add_row(
            arm.key,
            "[green]yes[/]" if ok else "[red]no[/]",
            str(len(result.turns)),
            str(len(result.tool_calls)),
            f"{stats.context_tokens:,}" if stats and stats.context_tokens else "—",
            f"{stats.context_percent:.1f}%" if stats and stats.context_percent else "—",
            f"{stats.total:,}" if stats else "—",
            f"{result.peak_context:,}",
            f"${stats.cost:.4f}" if stats else f"${result.cost:.4f}",
        )
    console.print()
    console.print(table)
    for arm, result, _ in results:
        console.print(f"  [dim]{arm.key:<10}[/] {result.answer[:70]}")
        console.print(f"  [dim]{'':<10} tools: {result.tool_calls}[/]")


if __name__ == "__main__":
    main()
