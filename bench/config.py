"""Where the harness talks to, and as whom."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOTENV = ROOT / ".env"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
API_KEY_ENV = "OPENROUTER_API_KEY"

# Pinned rather than routed: `openrouter/auto` and `openrouter/free` choose a model per request, so
# two cells could run on different models and the comparison would stop being about exposure.
#
# Paid, and deliberately so. Free endpoints answer with `ResourceExhausted` under any real load, and
# a trial that dies because it landed on a busy worker says nothing about the arm it was measuring.
# At $0.14/M in and $0.28/M out the whole battery costs less than the time spent retrying.
PRIMARY_MODEL = "deepseek/deepseek-v4-flash"  # 1M context
SECOND_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"  # 262k context, a second tier to compare against

MODELS = (PRIMARY_MODEL, SECOND_MODEL)
MODEL = PRIMARY_MODEL

# Requested on every call, and the same for every cell. A provider is free to ignore it, which is
# why the invariant says "requested" rather than "guaranteed": the traces record what actually came
# back, and repeats are what establish the spread.
SEED = 20260731

# Pinned rather than inherited, because the default varies by provider and this metric is reported.
# Allowing batched calls makes `turns` and `tool_calls` diverge, and the divergence is a finding: an
# eager arm can batch calls to tools it already holds, while a deferred arm cannot batch what it has
# not loaded yet. That asymmetry is real, not an artefact.
PARALLEL_TOOL_CALLS = True

# Temperature is deliberately not pinned. The models in use reason before answering, and a fixed
# temperature neither constrains the reasoning path nor is honoured consistently across providers —
# pinning it would claim a determinism the run does not have.


def load_env(path: Path | str = DOTENV) -> dict[str, str]:
    """Read a `.env` file into the process environment, returning what it set.

    Small enough not to be worth a dependency. Values already present in the environment win, so a
    key exported in a shell or injected by CI is never silently overridden by a stale local file.
    """
    source = Path(path)
    if not source.exists():
        return {}
    applied: dict[str, str] = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        name, value = name.strip(), value.strip().strip("\"'")
        if not name or not value or name in os.environ:
            continue
        os.environ[name] = value
        applied[name] = value
    return applied


def api_key() -> str:
    """The OpenRouter key, or a message that says exactly what to do about its absence."""
    load_env()
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(
            f"{API_KEY_ENV} is not set. Copy .env.example to .env and paste a key from "
            "https://openrouter.ai/keys. Only the run-time half of the benchmark needs one — the "
            "static measurements and the tests run offline."
        )
    return key
