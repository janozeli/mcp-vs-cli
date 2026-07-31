"""One place that decides how every run is executed, so the arms differ only where they should.

Spike-stage. See SPIKE.md.

Every arm gets the same harness, the same isolation, the same prompt and unrestricted `bash`. What
differs is only what has been *installed* on top: an MCP extension, a binary on `PATH`, or nothing.
That is the whole point of moving to a stock harness — the arm should be an installation, not a code
path.

Three things here are not conveniences, they are the measurement:

**Compaction is disabled.** pi compacts context automatically. Left on, a benchmark about context
cost measures pi's compactor. Its own `getContextUsage()` even reports `tokens: null` until a
post-compaction assistant response exists, so the metric is compaction-aware and would go quiet
exactly when it mattered.

**Retries are disabled.** Retry tokens are not the arm's cost.

**The machine is shut out.** `HOME`/`USERPROFILE` point at a directory this file creates, holding
the settings above, so no globally installed extension, skill or MCP server can join the run. A
first attempt without this carried the operator's own extensions into the context and was worth
about 29,000 tokens per turn. Discovery of context files, skills, prompt templates and themes is
switched off for the same reason — running inside this repository would otherwise inject its own
`CLAUDE.md` into every cell.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from bench.arms import OBJECTIVE  # noqa: E402

PI = REPO / "spike" / "node_modules" / ".bin" / "pi.exe"
MCP_SERVER = REPO / "spike" / "camara_mcp.py"

# Written into the isolated home. These two defaults are the ones that would silently corrupt a
# context measurement, so they are set here rather than assumed.
SETTINGS: dict[str, Any] = {
    "compaction": {"enabled": False},
    "retry": {"enabled": False},
    "quietStartup": True,
    "enableAnalytics": False,
    "enableInstallTelemetry": False,
}

# Applied to every run, without exception. If an arm needs one of these changed, it is no longer the
# same experiment and the difference has to be declared.
ISOLATION = [
    "--print",
    "--mode", "json",
    "--no-session",
    "--no-extensions",       # explicit -e paths still load
    "--no-context-files",    # or this repository's own CLAUDE.md joins every cell
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--no-approve",
    "--offline",             # no startup network calls to muddy the timing
]


@dataclass(frozen=True, slots=True)
class Arm:
    """What is installed on top of the common harness."""

    key: str
    tools: tuple[str, ...]
    extensions: tuple[Path, ...] = ()
    mcp_servers: dict[str, str] = field(default_factory=dict)
    path_additions: tuple[Path, ...] = ()
    why: str = ""


ARMS: dict[str, Arm] = {
    "baseline": Arm(
        key="baseline",
        tools=("bash",),
        why="a shell and nothing else: the price of having no documentation at all",
    ),
    "mcp": Arm(
        key="mcp",
        tools=("bash", "mcp"),
        extensions=(REPO / "spike" / ".pi" / "npm" / "node_modules" / "pi-mcp-adapter",),
        mcp_servers={"camara": str(REPO / "spike" / "camara-mcp.cmd")},
        why="the user installed an MCP server; the adapter decides how it reaches the model",
    ),
    "cli": Arm(
        key="cli",
        tools=("bash",),
        path_additions=(REPO / "spike" / "bin",),
        why="the user installed a CLI; the shell it already had is how it gets called",
    ),
}


@dataclass(slots=True)
class Turn:
    """One assistant message, as the provider reported it."""

    input: int
    output: int
    reasoning: int
    cache_read: int
    cache_write: int
    cost: float

    @property
    def context(self) -> int:
        """What the model actually carried. pi reports `input` net of cache reads."""
        return self.input + self.cache_read


@dataclass(slots=True)
class Result:
    arm: str
    answer: str
    turns: list[Turn]
    tool_calls: list[str]
    raw: Path | None = None

    @property
    def peak_context(self) -> int:
        return max((t.context for t in self.turns), default=0)

    @property
    def total_input(self) -> int:
        return sum(t.context for t in self.turns)

    @property
    def total_output(self) -> int:
        return sum(t.output for t in self.turns)

    @property
    def total_reasoning(self) -> int:
        return sum(t.reasoning for t in self.turns)

    @property
    def cost(self) -> float:
        return sum(t.cost for t in self.turns)


def _isolated_home(root: Path) -> Path:
    """A home directory this process owns, holding the settings that make the run measurable."""
    home = root / "home"
    agent = home / ".pi" / "agent"
    agent.mkdir(parents=True, exist_ok=True)
    (agent / "settings.json").write_text(json.dumps(SETTINGS, indent=2) + "\n", encoding="utf-8")
    return home


def _mcp_config(root: Path, arm: Arm) -> None:
    if not arm.mcp_servers:
        return
    servers = {name: {"command": command, "args": []} for name, command in arm.mcp_servers.items()}
    (root / ".mcp.json").write_text(
        json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8"
    )


def _parse(stdout: str) -> tuple[list[Turn], list[str], str]:
    turns: list[Turn] = []
    calls: list[str] = []
    answer = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue  # a banner, or anything else pi decides to print
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "tool_execution_start":
            calls.append(str(event.get("toolName")))
        if event.get("type") != "message_end":
            continue
        message = event.get("message") or {}
        usage = message.get("usage") or {}
        if usage.get("totalTokens"):
            turns.append(
                Turn(
                    input=int(usage.get("input") or 0),
                    output=int(usage.get("output") or 0),
                    reasoning=int(usage.get("reasoning") or 0),
                    cache_read=int(usage.get("cacheRead") or 0),
                    cache_write=int(usage.get("cacheWrite") or 0),
                    cost=float((usage.get("cost") or {}).get("total") or 0.0),
                )
            )
        for part in message.get("content") or []:
            if part.get("type") == "text" and part.get("text"):
                answer = part["text"]
    return turns, calls, answer


def run(
    question: str,
    arm: Arm,
    *,
    model: str,
    provider: str,
    api_key: str,
    workdir: Path,
    thinking: str | None = None,
    timeout: int = 900,
    keep_raw: bool = True,
) -> Result:
    """Run one question through one arm, with every other variable held here."""
    workdir.mkdir(parents=True, exist_ok=True)
    home = _isolated_home(workdir)
    _mcp_config(workdir, arm)

    command = [str(PI), *ISOLATION]
    command += ["--provider", provider, "--model", model, "--api-key", api_key]
    command += ["--system-prompt", OBJECTIVE]
    command += ["--tools", ",".join(arm.tools)]
    if thinking:
        command += ["--thinking", thinking]
    for extension in arm.extensions:
        command += ["--extension", str(extension)]
    command.append(question)

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PI_OFFLINE"] = "1"
    if arm.path_additions:
        env["PATH"] = os.pathsep.join([*(str(p) for p in arm.path_additions), env.get("PATH", "")])

    completed = subprocess.run(
        command, cwd=workdir, env=env, capture_output=True, text=True, timeout=timeout
    )
    turns, calls, answer = _parse(completed.stdout)

    raw = None
    if keep_raw:
        raw = workdir / f"{arm.key}.jsonl"
        raw.write_text(completed.stdout, encoding="utf-8")
        (workdir / f"{arm.key}.stderr").write_text(completed.stderr, encoding="utf-8")

    return Result(arm=arm.key, answer=answer.strip(), turns=turns, tool_calls=calls, raw=raw)
