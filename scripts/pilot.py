"""Run trials against a model, live.

Contract: `.claude/contracts/run-trials.md`.

Nothing is cached and nothing is replayed. Every trial reaches the API as it is at that moment,
which is what an agent in the wild does. The ground truth is solved live too, immediately before the
arms run, so "correct" means correct against what the API said during this run rather than against a
value that was true once.

What that costs: two arms could in principle receive different data, and nobody can re-execute this
run later. What replaces the guarantee is measurement — every response is in the trace, and
`scripts/verify_parity.py` checks after the fact whether the arms actually saw the same bytes.

    uv run python -m scripts.pilot t4-sao-paulo-yes-votes
    uv run python -m scripts.pilot t1-civil-name --arm baseline
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from openai import OpenAI
from rich.console import Console
from rich.table import Table

from bench import config, spec, tasks, triad
from bench.agent import Trial, run_trial
from bench.api import Api

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"
RUNS = ROOT / "runs"

# The subject is a public service run at public expense; trials are sequential and spaced.
PAUSE_SECONDS = 0.2


def _arms(selector: str) -> list[triad.Arm]:
    """`triad` for level zero, or a single arm by key."""
    if selector == "triad":
        return list(triad.TRIAD)
    return [triad.by_key(selector)]


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("task", nargs="?", default=tasks.TASKS[0].id, help="task id")
    parser.add_argument("--arm", default="triad", help="`triad`, or one arm key")
    return parser.parse_args()


def _summary_table(task_id: str, results: list[Trial]) -> Table:
    table = Table(title=task_id)
    table.add_column("arm")
    table.add_column("ok", justify="center")
    for column in ("turns", "calls", "upfront", "peak ctx", "prompt Σ", "tool out", "reasoning"):
        table.add_column(column, justify="right")
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
            f"{trial.reasoning_tokens:,}",
        )
    return table


def main() -> None:
    args = _parse()
    task = tasks.by_id(args.task)
    arms = _arms(args.arm)

    registry = spec.load(SPEC)
    api = Api(registry.base_url, pause=PAUSE_SECONDS)
    client = OpenAI(base_url=config.OPENROUTER_BASE_URL, api_key=config.api_key())
    console = Console()

    console.print(f"[bold]{task.id}[/] — {task.question}")
    expected = task.solver(api)
    drifted = not task.check(str(expected))
    console.print(
        f"solved live: [green]{expected!r}[/]"
        + (f"  [red]drifted from the last observed {task.answer!r}[/]" if drifted else "")
    )
    console.print(f"model [cyan]{config.MODEL}[/]\n")

    results: list[Trial] = []
    trace_dir = RUNS / task.id
    for arm in arms:
        console.print(f"  running [bold]{arm.key}[/] ({arm.fmt}/{arm.disclosure}/{arm.handling}) …", end="")
        trial = run_trial(
            task,
            fmt=arm.fmt,
            disclosure=arm.disclosure,
            handling=arm.handling,
            expected=expected,
            registry=registry,
            api=api,
            client=client,
            trace_dir=trace_dir,
            max_turns=arm.max_turns,
        )
        console.print(" [green]ok[/]" if trial.success else f" [red]{trial.aborted or 'wrong answer'}[/]")
        results.append(trial)

    console.print()
    console.print(_summary_table(task.id, results))
    for trial in results:
        console.print(f"  [dim]{trial.arm:<24}[/] {trial.answer[:60] or trial.aborted}")

    resolved = sorted({m for t in results for m in t.resolved_models})
    manifest = {
        "task": task.id,
        "solved_live": expected,
        "reference_answer": task.answer,
        "drifted_from_reference": drifted,
        "model_requested": config.MODEL,
        "models_resolved": resolved,
        "arms": [t.arm for t in results],
        "api_calls": api.calls,
    }
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    console.print(f"\n[dim]models the provider actually used: {', '.join(resolved) or 'none'}[/]")
    console.print(f"[dim]{api.calls} API calls · traces and manifest in {trace_dir.relative_to(ROOT)}[/]")
    console.print("[dim]check the arms saw the same data: uv run python -m scripts.verify_parity[/]")


if __name__ == "__main__":
    main()
