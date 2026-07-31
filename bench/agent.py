"""The agent loop: one task, one cell of the design, one transcript on disk.

Every request and every response is written to JSONL before anything is summarised, so each published
figure can be recomputed by someone who does not trust the summary. Token counts come from the
provider's own `usage`, not from a local tokeniser — what the model was billed for is not something
this repo gets to have an opinion about.

Two numbers are kept apart on purpose. `peak_context` is the largest prompt the run ever sent: the
window actually occupied, which prompt caching does not give back. `prompt_tokens` is their sum
across turns: what the run cost. Conflating them is how the MCP argument usually goes wrong.
"""

from __future__ import annotations

import json
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

from bench import config, tokens
from bench.api import Api
from bench.arms import Disclosure, Handling
from bench.arms import cli as cli_arm
from bench.arms import mcp as mcp_arm
from bench.arms import raw as raw_arm
from bench.execute import call_operation, fetch_url, run_command
from bench.spec import Registry
from bench.tasks import Task

MAX_TURNS = 12
PREFIX = "camara__"

# Free endpoints answer HTTP 200 with `choices: null` and an error object when the upstream provider
# is out of capacity. That is transient and says nothing about the arm being measured, so it is
# retried rather than scored. Every attempt still lands in the trace.
RETRYABLE = ("resourceexhausted", "rate limit", "rate-limit", "overloaded", "timeout", "try again")
BACKOFF_SECONDS = (2, 5, 12, 30, 60)

# How many results a deferred search returns. A client that returned everything on every search
# would not be deferring anything.
BROWSE_LIMIT = 12
SELECT_LIMIT = 5


@dataclass(slots=True)
class Trial:
    """The outcome of one task in one cell, plus everything needed to audit it."""

    task_id: str
    arm: str
    model: str
    success: bool = False
    answer: str = ""
    turns: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    peak_context: int = 0
    tool_output_tokens: int = 0
    upfront_tokens: int = 0
    resolved_models: list[str] = field(default_factory=list)
    aborted: str | None = None
    trace: str = ""


def _strip_prefix(name: str) -> str:
    return name[len(PREFIX) :] if name.startswith(PREFIX) else name


def _fold(text: str) -> str:
    """Lowercase and strip accents, so `orgaos` finds `Órgãos`."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _search(
    registry: Registry, query: str, loaded: set[str], filtering: bool = False
) -> tuple[str, list[str]]:
    """Resolve a `tool_search` query, as a deferring client would.

    Browsing returns names; only `select:` returns schemas. Charging a full schema for every keyword
    guess would price the search's design rather than the format, and this format is being compared
    against a `--help` that costs one flat listing to browse.
    """
    raw = query.strip()
    candidates = [_strip_prefix(n.strip()) for n in raw.split(",") if n.strip()]
    names_in_registry = {op.name for op in registry}
    # A query that already names tools exactly is a request to load them. Making the model spell
    # `select:` first punished it for reading the index it was given, which cost a whole turn.
    if raw and all(name in names_in_registry for name in candidates):
        raw = "select:" + ",".join(candidates)

    if raw.lower().startswith("select:"):
        wanted = [_strip_prefix(n.strip()) for n in raw.split(":", 1)[1].split(",") if n.strip()]
        names, unknown = [], []
        for name in wanted[:SELECT_LIMIT]:
            try:
                registry.by_name(name)
            except KeyError:
                unknown.append(name)
                continue
            names.append(name)
        if not names:
            return f"No such tools: {', '.join(unknown)}. Search by keyword first.", []
        loaded.update(names)
        definitions = [
            mcp_arm.tool_definition(registry.by_name(n), prefix=PREFIX, filtering=filtering) for n in names
        ]
        note = f"\nNot found: {', '.join(unknown)}." if unknown else ""
        return json.dumps(definitions, ensure_ascii=False) + note, names

    terms = [t.strip().lower() for t in raw.replace(",", " ").split() if t.strip()]
    scored: list[tuple[int, str]] = []
    for op in registry:
        haystack = _fold(f"{op.name} {op.summary} {op.group}")
        score = sum(1 for term in terms if _fold(_strip_prefix(term)) in haystack)
        if score:
            scored.append((score, op.name))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    matches = [name for _, name in scored[:BROWSE_LIMIT]]
    if not matches:
        # A dead end would charge the arm a turn for asking in the wrong language: this corpus is
        # documented in Portuguese and the questions arrive in English. Fall back to the groups, so
        # a miss still leaves somewhere to go.
        groups = ", ".join(f"{g} ({len(ops)})" for g, ops in registry.groups().items())
        return (
            f"Nothing matched {query!r}. The tools are grouped as: {groups}. "
            "Search by a group name, or by a term from the API's own vocabulary.",
            [],
        )

    lines = [f"{PREFIX}{name} — {registry.by_name(name).summary}".rstrip() for name in matches]
    lines.append("")
    lines.append(f"Load with `select:{PREFIX}<name>` (comma-separated for several).")
    return "\n".join(lines), []


def _tools_for_turn(
    registry: Registry, fmt: str, disclosure: Disclosure, loaded: set[str], filtering: bool
) -> list[dict[str, Any]]:
    if fmt == "raw":
        return raw_arm.tools_for(registry, disclosure=disclosure, filtering=filtering)
    if fmt == "cli":
        return cli_arm.tools_for(registry, disclosure=disclosure, filtering=filtering)
    if disclosure == "eager":
        return mcp_arm.tool_definitions(registry, prefix=PREFIX, filtering=filtering)
    # Deferred: the search tool, plus whatever the model has pulled in so far.
    definitions = [mcp_arm.search_tool_definition()]
    definitions.extend(
        mcp_arm.tool_definition(registry.by_name(name), prefix=PREFIX, filtering=filtering)
        for name in sorted(loaded)
    )
    return definitions


def _system_prompt(registry: Registry, fmt: str, disclosure: Disclosure) -> str:
    if fmt == "raw":
        return raw_arm.system_prompt(registry, disclosure=disclosure)
    if fmt == "cli":
        return cli_arm.system_prompt(registry, disclosure=disclosure)
    return mcp_arm.system_prompt(registry, disclosure=disclosure, prefix=PREFIX)


def run_trial(
    task: Task,
    *,
    fmt: str,
    disclosure: Disclosure,
    registry: Registry,
    api: Api,
    client: OpenAI,
    handling: Handling = "whole",
    expected: str | float | None = None,
    model: str = config.MODEL,
    trace_dir: Path | None = None,
    max_turns: int = MAX_TURNS,
) -> Trial:
    """Run one task in one cell, writing a full transcript as it goes.

    `expected` is the value a live solve produced for this run. Without it the task's last observed
    value is used, which is a fallback and not a guarantee — the API may have moved since.
    """
    filtering = handling == "filtered"
    deferred = fmt == "mcp" and disclosure != "eager"
    arm = f"{fmt}/{disclosure}/{handling}"
    trial = Trial(task_id=task.id, arm=arm, model=model)

    system = _system_prompt(registry, fmt, disclosure)
    loaded: set[str] = set()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": task.question},
    ]

    trace_path: Path | None = None
    if trace_dir is not None:
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = trace_dir / f"{task.id}__{fmt}-{disclosure}-{handling}.jsonl"
        trace_path.write_text("", encoding="utf-8")
        trial.trace = str(trace_path)

    def record(event: dict[str, Any]) -> None:
        if trace_path is not None:
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    trial.upfront_tokens = tokens.count_json(
        _tools_for_turn(registry, fmt, disclosure, loaded, filtering)
    ) + tokens.count_text(system)

    for turn in range(1, max_turns + 1):
        tools = _tools_for_turn(registry, fmt, disclosure, loaded, filtering)
        request = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": config.TEMPERATURE,
        }
        record({"turn": turn, "request": request})
        raw, failure = _complete_with_retry(client, request, record, turn)
        if raw is None:
            trial.aborted = f"provider error on turn {turn}: {failure}"
            return trial
        record({"turn": turn, "response": raw})

        trial.turns = turn
        trial.resolved_models.append(str(raw.get("model", model)))
        usage = raw.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        trial.prompt_tokens += prompt_tokens
        trial.completion_tokens += int(usage.get("completion_tokens") or 0)
        trial.peak_context = max(trial.peak_context, prompt_tokens)

        choice = raw["choices"][0]["message"]
        calls = choice.get("tool_calls") or []
        messages.append({k: v for k, v in choice.items() if k in {"role", "content", "tool_calls"}})

        if not calls:
            trial.answer = (choice.get("content") or "").strip()
            # Graded against what the API said in this run, when the caller solved it live.
            trial.success = task.check(trial.answer, expected)
            return trial

        for call in calls:
            name = call["function"]["name"]
            try:
                arguments = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            trial.tool_calls += 1

            try:
                output, resolved = _dispatch(
                    registry, api, fmt, name, arguments, loaded, filtering, deferred
                )
            except httpx.HTTPError as exc:
                # Never fabricate a response. With nothing stored behind it, a response that did not
                # arrive is gone for good, and a run built on invented data is worse than no run.
                trial.aborted = f"api unreachable on turn {turn}: {type(exc).__name__}: {exc}"
                record({"turn": turn, "tool_call": call, "error": trial.aborted})
                return trial

            output_tokens = tokens.count_text(output)
            trial.tool_output_tokens += output_tokens
            # The output text is stored, not just its size. Nothing caches these responses, so the
            # trace is the only record that this one ever existed — invariant 4 now rests on it. The
            # resolved request is stored beside it, because that is the only form in which the three
            # formats' calls can be compared afterwards.
            record(
                {
                    "turn": turn,
                    "tool_call": call,
                    "request": resolved,
                    "output_tokens": output_tokens,
                    "output": output,
                }
            )
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})

    trial.aborted = f"gave up after {max_turns} turns"
    return trial


def _complete(client: OpenAI, request: dict[str, Any]) -> dict[str, Any]:
    """Send exactly the dict that was traced.

    The request is built once and both sent and recorded, so the transcript cannot drift from what
    the provider actually received. `usage.include` asks OpenRouter for the underlying provider's
    own token counts rather than its estimate.
    """
    create: Any = client.chat.completions.create
    completion = create(**request, extra_body={"usage": {"include": True}})
    result: dict[str, Any] = completion.model_dump()
    return result


def _error_of(raw: dict[str, Any]) -> str | None:
    """A completion that carries no choices is an error, whatever status code it arrived with."""
    if raw.get("choices"):
        return None
    error = raw.get("error") or {}
    message = error.get("message") if isinstance(error, dict) else None
    return str(message or "response contained no choices")


def _is_transient(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in RETRYABLE)


def _complete_with_retry(
    client: OpenAI,
    request: dict[str, Any],
    record: Any,
    turn: int,
) -> tuple[dict[str, Any] | None, str | None]:
    """Retry transient upstream failures, and record every attempt.

    A capacity error from a free endpoint is noise about the provider, not signal about the arm. It
    would be dishonest to score a cell lower because its trial happened to land on a busy worker.
    """
    last: str = "unknown error"
    for attempt, pause in enumerate((0, *BACKOFF_SECONDS)):
        if pause:
            time.sleep(pause)
        try:
            raw = _complete(client, request)
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            record({"turn": turn, "attempt": attempt, "error": last})
            if not _is_transient(last):
                return None, last
            continue

        failure = _error_of(raw)
        if failure is None:
            if attempt:
                record({"turn": turn, "attempt": attempt, "note": "recovered after retry"})
            return raw, None

        last = failure
        record({"turn": turn, "attempt": attempt, "response": raw, "error": failure})
        if not _is_transient(failure):
            return None, failure

    return None, f"gave up after {len(BACKOFF_SECONDS)} retries: {last}"


def _dispatch(
    registry: Registry,
    api: Api,
    fmt: str,
    name: str,
    arguments: dict[str, Any],
    loaded: set[str],
    filtering: bool = False,
    deferred: bool = False,
) -> tuple[str, str | None]:
    """Returns what the model sees, and the resolved request that produced it.

    The second value is what makes the formats comparable afterwards: each spells a call its own
    way, and only the resolved request is the same object across all three.
    """
    if fmt == "raw":
        if name != "http_get":
            return f"error: no such tool {name!r}", None
        result = fetch_url(
            api,
            str(arguments.get("url", "")),
            jq_expression=arguments.get("_jq") if filtering else None,
        )
        return result.text, result.request
    if fmt == "cli":
        if name != "run_cli":
            return f"error: no such tool {name!r}", None
        command = str(arguments.get("command", ""))
        result = run_command(registry, api, command, allow_pipe=filtering)
        return result.text, result.request
    if name == "tool_search":
        text, _ = _search(registry, str(arguments.get("query", "")), loaded, filtering)
        return text, None
    if deferred and _strip_prefix(name) not in loaded:
        # A deferred client cannot execute a tool it never sent a definition for. Running it anyway
        # turned this cell into "eager without paying for the schemas", which is not a configuration
        # anyone can actually deploy -- and it let a model that had merely read the index skip the
        # round trip the cell exists to measure.
        return (
            f"error: {name} is not loaded. Load its definition first with "
            f"tool_search(query='select:{name}').",
            None,
        )
    result = call_operation(registry, api, name, arguments, prefix=PREFIX)
    return result.text, result.request


def summarise(trial: Trial) -> dict[str, Any]:
    return asdict(trial)
