"""Static context cost of every cell of the design, as a function of how many operations exist.

This answers the first half of the question — what each way of exposing capabilities occupies in the
window — offline and without spending anything. What each one *recovers* for that cost, in turns and
in accuracy, is the run-time half and lives elsewhere.

    uv run python -m bench.measure
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from bench import design, spec, tokens

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data" / "specs" / "camara-dados-abertos-v2.json"
RESULTS = ROOT / "results" / "context-cost.json"

# MCP clients namespace tools by server to keep names unique across connected servers. It is part of
# what the format costs, so it is counted.
PREFIX = "camara__"

LEVELS = (5, 10, 20, 40, 78)

# How many distinct operations a task needs. Most real questions touch a handful.
K = 3


def collect(registry: spec.Registry, levels: tuple[int, ...] = LEVELS) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for n in levels:
        sampled = registry.sample(n, seed=0) if n < len(registry) else registry
        rows.append(
            {
                "n_operations": n,
                "arms": {
                    arm.key: {
                        "upfront_tools": arm.upfront_tools,
                        "upfront_system": arm.upfront_system,
                        "upfront": arm.upfront,
                        "catalogue_on_demand": arm.catalogue_on_demand,
                        "detail_median": arm.detail_median,
                        f"readiness_k{K}": arm.readiness(K),
                    }
                    for arm in design.arms(sampled, prefix=PREFIX)
                },
            }
        )
    return {
        "spec": SPEC.name,
        "api": registry.title,
        "operations_available": len(registry),
        "encoding": tokens.ENCODING,
        "k": K,
        "note": (
            "Static estimate of context occupancy. `upfront` is what an arm holds before the task is "
            "read; `readiness_k` adds what it must fetch to be able to call k operations. Run-time "
            "usage is measured separately, from provider-reported numbers."
        ),
        "levels": rows,
    }


def _grid(console: Console, report: dict[str, Any], field: str, title: str) -> None:
    table = Table(title=title)
    table.add_column("arm")
    for row in report["levels"]:
        table.add_column(str(row["n_operations"]), justify="right")
    keys = list(report["levels"][0]["arms"])
    for key in keys:
        style = "red" if key.endswith("eager") else "green" if key.endswith("lazy") else "yellow"
        cells = [f"{row['arms'][key][field]:,}" for row in report["levels"]]
        table.add_row(key, *cells, style=style)
    console.print(table)


def main() -> None:
    registry = spec.load(SPEC)
    report = collect(registry)

    console = Console()
    _grid(console, report, "upfront", "Context occupied before the task is read, by operations exposed")
    _grid(console, report, f"readiness_k{K}", f"Context held to be ready to call {K} operations")

    full = report["levels"][-1]["arms"]
    console.print(
        f"\nAt {report['operations_available']} operations, the two [red]eager[/] cells cost "
        f"[red]{full['mcp/eager']['upfront']:,}[/] (mcp) and [red]{full['cli/eager']['upfront']:,}[/] (cli) "
        f"up front; the two [green]lazy[/] cells cost "
        f"[green]{full['mcp/lazy']['upfront']:,}[/] and [green]{full['cli/lazy']['upfront']:,}[/]."
    )

    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    console.print(f"[dim]wrote {RESULTS.relative_to(ROOT)}[/]")


if __name__ == "__main__":
    main()
