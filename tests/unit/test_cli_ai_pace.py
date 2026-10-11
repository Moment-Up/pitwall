"""``pitwall ai-pace backfill`` refuses while anything answers on the HTTP port (v0.2.0 plan 6.2): opening the database
there would add a second writer under a running server and migrate its database with this code. ``cli._http`` is
replaced by a fake, so no test ever contacts a real Pitwall."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from pitwall import cli
from pitwall.config import Settings

runner = CliRunner()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    s = Settings(_env_file=None, data_dir=tmp_path / "data", http_port=8798, llm_enabled=False)  # type: ignore[call-arg]
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    return s


def _answering(reply: tuple[int, Any] | None) -> Any:
    calls: list[str] = []

    def fake(method: str, url: str, body: dict[str, Any] | None = None, timeout_s: float = 10.0) -> Any:
        assert url.startswith("http://127.0.0.1:8798/"), url  # the test's port, never the live service's
        calls.append(url)
        return reply

    fake.calls = calls  # type: ignore[attr-defined]
    return fake


@pytest.mark.parametrize("reply", [(200, {"connection": {}}), (cli.NO_REPLY, None), (401, None)])
def test_refuses_while_anything_answers(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, reply: tuple[int, Any]
) -> None:
    fake = _answering(reply)
    monkeypatch.setattr(cli, "_http", fake)
    r = runner.invoke(cli.app, ["ai-pace", "backfill", "--captures", str(settings.data_dir), "--dry-run"])
    assert r.exit_code == 1
    assert "stop the service first, or set PITWALL_DATA_DIR to a copy" in r.output
    assert fake.calls and fake.calls[0].endswith("/api/health")
    assert not settings.db_path.exists()  # the database was never opened (nor created, nor migrated)


def test_runs_when_nothing_answers_or_forced(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    settings.data_dir.mkdir(parents=True)
    monkeypatch.setattr(cli, "_http", _answering(None))
    r = runner.invoke(cli.app, ["ai-pace", "backfill", "--captures", str(settings.data_dir), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "no matching sessions in these captures" in r.output
    monkeypatch.setattr(cli, "_http", _answering((200, {"connection": {}})))
    r = runner.invoke(cli.app, ["ai-pace", "backfill", "--captures", str(settings.data_dir), "--dry-run", "--force"])
    assert r.exit_code == 0, r.output
