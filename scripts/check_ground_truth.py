"""Solve every task against the live API and compare with the value last observed.

The test suite deliberately cannot do this. A test that reaches the network fails for reasons that
have nothing to do with the code, and a suite that fails for external reasons is a suite people
learn to ignore. So the tests check the code, and this checks the world.

Run it before a batch of measurements. A task whose answer has moved is not broken — it is a task
whose difficulty or meaning may have changed, and the reference in `bench/tasks.py` needs updating
deliberately rather than silently.

    uv run python -m scripts.check_ground_truth
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from bench import spec, tasks
from bench.api import Api

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"


def main() -> None:
    registry = spec.load(SPEC)
    api = Api(registry.base_url, pause=0.2)
    console = Console()

    console.print(f"solving {len(tasks.TASKS)} tasks against [cyan]{registry.base_url}[/]\n")
    drifted = []
    for task in tasks.TASKS:
        live = task.solver(api)
        agrees = task.check(str(live))
        mark = "[green]agrees[/]" if agrees else "[red]DRIFTED[/]"
        console.print(f"  [{task.difficulty}] {task.id:<28} {live!r:<32} {mark}")
        if not agrees:
            drifted.append((task, live))

    console.print(f"\n[dim]{api.calls} API calls[/]")
    if drifted:
        console.print("\n[red]the API no longer says what these tasks recorded:[/]")
        for task, live in drifted:
            console.print(f"  {task.id}: reference {task.answer!r}, now {live!r}")
        console.print(
            "\nUpdate `answer` in bench/tasks.py deliberately, and consider whether the task still "
            "stresses what it claims to."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
