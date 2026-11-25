import pytest

from autokit.cli import main
from autokit.config import load_settings


def test_settings_have_local_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTOKIT_REDIS_URL", raising=False)

    settings = load_settings()

    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.requests_per_second == 2


def test_settings_are_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOKIT_REDIS_URL", "redis://cache:6379/2")
    monkeypatch.setenv("AUTOKIT_RPS", "0.5")

    settings = load_settings()

    assert settings.redis_url == "redis://cache:6379/2"
    assert settings.requests_per_second == 0.5


def test_cli_without_a_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: autokit" in capsys.readouterr().out
