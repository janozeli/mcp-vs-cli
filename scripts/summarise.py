"""Rebuild a run's numbers from its traces alone.

The point of writing every request and response to disk is that the summary should never be the only
copy of the truth. This reads nothing but the JSONL and recomputes what the pilot printed, which is
the check that a sceptic could do the same.

    uv run python -m scripts.summarise runs/measure
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

ROOT = Path(__file__).resolve().parents[1]


def summarise(trace: Path) -> dict[str, int]:
    turns = calls = prompt_sum = peak = tool_out = 0
    for line in trace.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        response = event.get("response")
        if response and response.get("choices"):
            usage = response.get("usage") or {}
            prompt = int(usage.get("prompt_tokens") or 0)
            prompt_sum += prompt
            peak = max(peak, prompt)
            turns = max(turns, int(event.get("turn") or 0))
        if "tool_call" in event:
            calls += 1
            tool_out += int(event.get("output_tokens") or 0)
    return {
        "turns": turns,
        "calls": calls,
        "peak": peak,
        "prompt_total": prompt_sum,
        "tool_output": tool_out,
    }


def _provenance(task_dir: Path) -> str:
    """What the run says about itself, so a table is never read without knowing what produced it."""
    manifest_path = task_dir / "manifest.json"
    if not manifest_path.exists():
        return "[yellow]no manifest — predates run provenance; corpus and model unverifiable[/]"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    resolved = ", ".join(manifest.get("models_resolved") or []) or "unknown"
    note = ""
    if manifest.get("mode") != "measure":
        note = "  [red]discover mode — not publishable[/]"
    if manifest.get("corpus_before") != manifest.get("corpus_after"):
        note += "  [red]corpus changed mid-run[/]"
    return f"[dim]corpus {manifest.get('corpus_after')} · model {resolved}[/]{note}"


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs" / "measure"
    console = Console()
    for task_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        table = Table(title=task_dir.name, caption=_provenance(task_dir))
        table.add_column("arm")
        for column in ("turns", "calls", "peak ctx", "prompt Σ", "tool out"):
            table.add_column(column, justify="right")
        for trace in sorted(task_dir.glob("*.jsonl")):
            arm = trace.stem.split("__")[-1]
            row = summarise(trace)
            table.add_row(
                arm,
                str(row["turns"]),
                str(row["calls"]),
                f"{row['peak']:,}",
                f"{row['prompt_total']:,}",
                f"{row['tool_output']:,}",
            )
        console.print(table)


if __name__ == "__main__":
    main()
