"""A public repo must not carry credentials, and a leaked key in git history cannot be taken back.

This scans tracked files only — anything git would actually publish. It runs in the normal test
gate, so the cost of noticing is one second and the cost of not noticing is a rotated key and a
rewritten history.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Prefixes of credentials this project could plausibly touch. Each pattern requires the payload that
# follows the prefix, so the patterns written here do not match themselves.
PATTERNS = {
    "OpenRouter key": re.compile(r"sk-or-v1-[0-9a-f]{32,}"),
    "Anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_-]{24,}"),
    "OpenAI key": re.compile(r"sk-proj-[A-Za-z0-9_-]{24,}"),
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
}

# Files where a match is the file doing its job.
ALLOWED = {"tests/test_no_secrets.py"}


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def test_no_credentials_in_tracked_files() -> None:
    findings: list[str] = []
    for relative in tracked_files():
        if relative in ALLOWED:
            continue
        path = ROOT / relative
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{relative}: looks like a {label}")
    assert not findings, "credentials found in tracked files:\n" + "\n".join(findings)


def test_the_scanner_actually_fires() -> None:
    """A scanner that never matches anything would pass this suite forever while protecting nothing."""
    # Assembled at runtime so this file does not itself contain a credential-shaped string.
    fake = "sk-or-" + "v1-" + "0123456789abcdef" * 4
    assert PATTERNS["OpenRouter key"].search(fake)


def test_dotenv_is_ignored() -> None:
    result = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, ".env must be gitignored before any key is put in it"


@pytest.mark.parametrize("name", [".env", ".env.local", "runs"])
def test_secret_and_output_paths_stay_untracked(name: str) -> None:
    assert name not in tracked_files()
