"""Check, after the fact, whether the arms of a comparison saw the same data.

Nothing is cached here, so nothing guarantees that two arms asking the same question got the same
answer — the API is live and can move between one trial and the next. That guarantee is replaced by
this: the traces hold every response verbatim, so the property can be *measured* instead of assumed.

A comparison where some shared request returned different bytes is not necessarily wrong, but it is
no longer a clean comparison, and saying so is the difference between a caveat and a defect.

    uv run python -m scripts.verify_parity              # every task under runs/
    uv run python -m scripts.verify_parity runs/t4-...  # one
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from rich.console import Console

ROOT = Path(__file__).resolve().parents[1]


def _requests_by_arm(trace: Path) -> dict[str, str]:
    """Every API response this arm received, keyed by the *resolved* request that produced it.

    The three formats spell the same call differently — a tool call, a command line, a URL — so the
    key has to be what they all reduce to, which the executor records. Keying on the spelling would
    compare `{"id": 204554}` with `api get_deputados 204554` and conclude, wrongly and every time,
    that the arms shared nothing.

    Events with no resolved request (help text, tool search, usage errors) never reached the API and
    are skipped.
    """
    seen: dict[str, str] = {}
    for line in trace.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        request = event.get("request")
        output = event.get("output")
        if not isinstance(request, str) or output is None:
            continue
        seen[request] = hashlib.sha256(output.encode("utf-8")).hexdigest()[:12]
    return seen


def verify(task_dir: Path, console: Console) -> bool:
    traces = sorted(task_dir.glob("*.jsonl"))
    if not traces:
        return True

    by_arm = {t.stem.split("__")[-1]: _requests_by_arm(t) for t in traces}
    responses: dict[str, dict[str, str]] = defaultdict(dict)
    for arm, seen in by_arm.items():
        for key, digest in seen.items():
            responses[key][arm] = digest

    shared = {k: v for k, v in responses.items() if len(v) > 1}
    divergent = {k: v for k, v in shared.items() if len(set(v.values())) > 1}

    console.print(f"[bold]{task_dir.name}[/] — {len(by_arm)} arms, {len(shared)} shared request(s)")
    if not shared:
        console.print(
            "  [yellow]no request was made by more than one arm in a comparable form; "
            "parity is untested here, not established[/]"
        )
        return True
    if divergent:
        for key, digests in divergent.items():
            console.print(f"  [red]diverged[/] {key}")
            for arm, digest in sorted(digests.items()):
                console.print(f"      {arm:<24} {digest}")
        return False
    console.print("  [green]every shared request returned identical bytes across arms[/]")
    return True


def main() -> None:
    roots = (
        [Path(sys.argv[1])]
        if len(sys.argv) > 1
        else sorted(p for p in (ROOT / "runs").iterdir() if p.is_dir())
    )
    console = Console()
    clean = all(verify(task_dir, console) for task_dir in roots)
    if not clean:
        console.print("\n[red]at least one comparison spanned a change in the API.[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
