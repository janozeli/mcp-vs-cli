"""Run trials against a model, in one of two modes that must not be confused.

Contract: `.claude/contracts/run-trials.md`.

**measure** (the default) replays and mutates nothing. Every cell of a comparison sees the same
corpus, and a call that was never recorded aborts its trial instead of quietly going to the network.
This is the only mode whose numbers may be published.

**discover** is a deliberate act that extends the corpus. Agents explore, so first contact with a
task reaches for calls no solver ever needed. Recording them is necessary — doing it while measuring
is not, and it used to happen here: a trial silently extended the corpus mid-experiment, which left
the cells of one comparison having run against different corpora.

    uv run python -m scripts.pilot t4-sao-paulo-yes-votes --discover   # extend the corpus
    uv run python -m scripts.pilot t4-sao-paulo-yes-votes              # then measure
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


def _parse() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("task", nargs="?", default=tasks.TASKS[0].id, help="task id")
    parser.add_argument("--arm", default="triad", help="`triad`, or one arm key")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="extend the corpus with whatever the agents reach for; never publish these numbers",
    )
    return parser.parse_args()


def _summary_table(task_id: str, mode: str, results: list[Trial]) -> Table:
    table = Table(title=f"{task_id} — {mode}")
    table.add_column("arm")
    table.add_column("ok", justify="center")
    for column in ("turns", "calls", "upfront", "peak ctx", "prompt Σ", "tool out"):
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
        )
    return table


def main() -> None:
    args = _parse()
    task = tasks.by_id(args.task)
    arms = _arms(args.arm)
    mode = "discover" if args.discover else "measure"

    registry = spec.load(SPEC)
    cassette = Cassette(CASSETTES, base_url=registry.base_url, mode="record" if args.discover else "replay")
    before = cassette.fingerprint()
    client = OpenAI(base_url=config.OPENROUTER_BASE_URL, api_key=config.api_key())

    console = Console()
    console.print(f"[bold]{task.id}[/] — {task.question}")
    console.print(
        f"expecting [green]{task.answer!r}[/], model [cyan]{config.MODEL}[/], "
        f"mode [cyan]{mode}[/], corpus [dim]{before}[/] ({len(cassette)} calls)\n"
    )

    trace_dir = RUNS / mode / task.id
    results: list[Trial] = []
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

    console.print()
    console.print(_summary_table(task.id, mode, results))
    for trial in results:
        console.print(f"  [dim]{trial.arm:<24}[/] {trial.answer[:60] or trial.aborted}")

    after = cassette.fingerprint()
    resolved = sorted({m for t in results for m in t.resolved_models})
    manifest = {
        "task": task.id,
        "mode": mode,
        "model_requested": config.MODEL,
        "models_resolved": resolved,
        "arms": [t.arm for t in results],
        "corpus_calls": len(cassette),
        "corpus_before": before,
        "corpus_after": after,
    }
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    console.print(f"\n[dim]models the provider actually used: {', '.join(resolved) or 'none'}[/]")
    console.print(f"[dim]traces and manifest in {trace_dir.relative_to(ROOT)}[/]")

    if mode == "measure":
        # The whole point of the mode. If this ever trips, the comparison spanned two datasets.
        assert before == after, "measuring must not change the corpus"
        misses = [t for t in results if t.aborted and "cassette miss" in t.aborted]
        if misses:
            console.print(
                f"\n[red]{len(misses)} trial(s) hit an unrecorded call.[/] Run the same task with "
                f"[bold]--discover[/] to extend the corpus, commit the new recordings, then measure "
                "again."
            )
    else:
        console.print(
            f"[yellow]corpus extended by {cassette.recorded} call(s)[/] — commit them separately, "
            "and re-run any measurement that predates this change."
            if cassette.recorded
            else "[dim]corpus unchanged; nothing new was reached for[/]"
        )


if __name__ == "__main__":
    main()
