from __future__ import annotations

from pathlib import Path

import pytest

from bench import config


def test_dotenv_is_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOME_KEY", raising=False)
    monkeypatch.delenv("QUOTED", raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "# a comment",
                "",
                "SOME_KEY=abc123",
                'QUOTED="with quotes"',
                "EMPTY=",
                "malformed line without equals",
            ]
        ),
        encoding="utf-8",
    )
    applied = config.load_env(env)
    assert applied == {"SOME_KEY": "abc123", "QUOTED": "with quotes"}


def test_the_environment_wins_over_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A key exported in the shell or injected by CI must not be clobbered by a stale local file.
    monkeypatch.setenv("SOME_KEY", "from-the-shell")
    env = tmp_path / ".env"
    env.write_text("SOME_KEY=from-the-file\n", encoding="utf-8")
    assert config.load_env(env) == {}


def test_a_missing_file_is_not_an_error(tmp_path: Path) -> None:
    assert config.load_env(tmp_path / "nope") == {}


def test_missing_key_explains_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.API_KEY_ENV, "")
    monkeypatch.setattr(config, "DOTENV", Path("does-not-exist"))
    with pytest.raises(RuntimeError, match="\\.env\\.example"):
        config.api_key()


def test_models_are_pinned_not_routed() -> None:
    # A router picks a model per request, which would let two cells run on different models.
    assert all(not m.startswith("openrouter/") for m in config.MODELS)
    assert config.MODEL in config.MODELS


def test_what_is_pinned_is_pinned_and_nothing_else_is_claimed() -> None:
    assert isinstance(config.SEED, int)
    # Pinned because turn counts are reported and the provider default varies.
    assert config.PARALLEL_TOOL_CALLS is True
    # Temperature is not pinned on purpose; asserting its absence keeps the decision deliberate.
    assert not hasattr(config, "TEMPERATURE")
