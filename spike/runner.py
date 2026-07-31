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

import contextlib
import json
import os
import subprocess
import sys
import time
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
#
# RPC rather than `--print --mode json`, for one reason: it can be asked `get_session_stats`, whose
# `contextUsage` is the estimate pi itself uses for compaction and its own footer. Summing per-turn
# usage is a derivation of ours; this is the number the harness believes. Its `tokens` also include
# usage reported by tools and by compaction, which per-turn parsing misses.
ISOLATION = [
    "--mode",
    "rpc",
    "--no-session",
    "--no-extensions",  # explicit -e paths still load
    "--no-context-files",  # or this repository's own CLAUDE.md joins every cell
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--no-approve",
    "--offline",  # no startup network calls to muddy the timing
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
class Stats:
    """What pi says about the session, rather than what we computed from its events."""

    input: int
    output: int
    cache_read: int
    cache_write: int
    total: int
    cost: float
    context_tokens: int | None
    context_window: int | None
    context_percent: float | None
    tool_calls: int

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> Stats:
        tokens = data.get("tokens") or {}
        usage = data.get("contextUsage") or {}
        return cls(
            input=int(tokens.get("input") or 0),
            output=int(tokens.get("output") or 0),
            cache_read=int(tokens.get("cacheRead") or 0),
            cache_write=int(tokens.get("cacheWrite") or 0),
            total=int(tokens.get("total") or 0),
            cost=float(data.get("cost") or 0.0),
            context_tokens=usage.get("tokens"),
            context_window=usage.get("contextWindow"),
            context_percent=usage.get("percent"),
            tool_calls=int(data.get("toolCalls") or 0),
        )


@dataclass(slots=True)
class Result:
    arm: str
    answer: str
    turns: list[Turn]
    tool_calls: list[str]
    stats: Stats | None = None
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
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")


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
    """Run one question through one arm, with every other variable held here.

    The conversation happens over RPC: the prompt goes in on stdin, events come back on stdout, and
    once the agent settles we ask it for its own accounting rather than trusting ours.
    """
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

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PI_OFFLINE"] = "1"
    if arm.path_additions:
        env["PATH"] = os.pathsep.join([*(str(p) for p in arm.path_additions), env.get("PATH", "")])

    deadline = time.monotonic() + timeout
    lines: list[str] = []
    stats: Stats | None = None

    process = subprocess.Popen(
        command,
        cwd=workdir,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    assert process.stdin and process.stdout

    def send(payload: dict[str, Any]) -> None:
        process.stdin.write(json.dumps(payload) + "\n")  # type: ignore[union-attr]
        process.stdin.flush()  # type: ignore[union-attr]

    try:
        send({"type": "prompt", "message": question})
        asked_for_stats = False
        for line in process.stdout:
            lines.append(line)
            if time.monotonic() > deadline:
                break
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # The agent has settled; now ask it what it thinks the session cost.
            if event.get("type") == "agent_end" and not asked_for_stats:
                asked_for_stats = True
                send({"type": "get_session_stats"})
                continue
            if event.get("type") == "response" and event.get("command") == "get_session_stats":
                if event.get("success"):
                    stats = Stats.from_payload(event.get("data") or {})
                break
    finally:
        with contextlib.suppress(OSError):
            process.stdin.close()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
        stderr = process.stderr.read() if process.stderr else ""

    stdout = "".join(lines)
    turns, calls, answer = _parse(stdout)

    raw = None
    if keep_raw:
        raw = workdir / f"{arm.key}.jsonl"
        raw.write_text(stdout, encoding="utf-8")
        (workdir / f"{arm.key}.stderr").write_text(stderr, encoding="utf-8")

    return Result(arm=arm.key, answer=answer.strip(), turns=turns, tool_calls=calls, stats=stats, raw=raw)
