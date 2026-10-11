"""``pitwall game``: list / show / set / clear. Every HTTP call goes through ``cli._http``, replaced here by a
scripted fake, so no test ever contacts a real Pitwall (a running service on this machine must never be changed)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from pitwall import cli
from pitwall.config import Settings

runner = CliRunner()


class FakeServer:
    """Replies by (method, path suffix); ``None`` = nothing answers. Records every call."""

    def __init__(self, replies: dict[tuple[str, str], tuple[int, Any]] | None = None) -> None:
        self.replies = replies
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(
        self, method: str, url: str, body: dict[str, Any] | None = None, timeout_s: float = 10.0
    ) -> tuple[int, Any] | None:
        self.calls.append((method, url, body))
        assert url.startswith("http://127.0.0.1:8797/"), url  # the test's port, never the live service's
        if self.replies is None:
            return None
        return next((r for (m, suffix), r in self.replies.items() if m == method and url.endswith(suffix)), None)


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    s = Settings(_env_file=None, data_dir=tmp_path / "data", http_port=8797, llm_enabled=False)  # type: ignore[call-arg]
    monkeypatch.setattr(cli, "get_settings", lambda: s)
    return s


def use(monkeypatch: pytest.MonkeyPatch, server: FakeServer) -> FakeServer:
    monkeypatch.setattr(cli, "_http", server)
    return server


def stored(s: Settings) -> dict[str, Any]:
    path = s.data_dir / "settings.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


HEALTH = (200, {"version": "0.1.0", "connection": {"status": "no_data"}})


def test_no_server_set_writes_the_game_and_its_input(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    server = use(monkeypatch, FakeServer(None))
    r = runner.invoke(cli.app, ["game", "set", "ac:ps4", "--console-ip", "192.168.1.50", "--json"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["selected"] == "ac:ps4" and out["via"] == "file"
    assert [a["action"] for a in out["actions"]] == ["enabled", "set_platform", "set_console_ip"]
    data = stored(settings)
    assert data["game"]["selected"] == "ac:ps4" and data["game"]["source"] == "cli"
    assert data["integrations"]["ac"] == {"enabled": True, "platform": "ps4", "console_ip": "192.168.1.50"}
    assert [c[0] for c in server.calls] == ["GET"]  # only the health probe
    r = runner.invoke(cli.app, ["game", "set", "gt7:ps5", "--no-input"])
    assert r.exit_code == 0 and "Selected Gran Turismo 7 (PS5)" in r.output
    assert "gt7" not in stored(settings)["integrations"]
    bad = runner.invoke(cli.app, ["game", "set", "gt7:ps5", "--console-ip", "8.8.8.8"])
    assert bad.exit_code == 1 and stored(settings)["game"]["selected"] == "gt7:ps5"
    unknown = runner.invoke(cli.app, ["game", "set", "fm7:xbox"])
    assert unknown.exit_code == 2
    r = runner.invoke(cli.app, ["game", "clear"])
    assert r.exit_code == 0 and stored(settings)["game"] == {}


def test_list_and_show_json(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeServer(None))
    r = runner.invoke(cli.app, ["game", "list", "--json"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["selected"] is None
    assert {e["group"] for e in out["entries"]} == {"main"} and len(out["entries"]) == 13
    assert all("fields" not in e for e in out["entries"])
    everything = json.loads(runner.invoke(cli.app, ["game", "list", "--json", "--all"]).output)
    assert len(everything["entries"]) == 23
    text = runner.invoke(cli.app, ["game", "list"]).output
    assert "gt7:ps5" in text and "Built from community docs" in text and "No game selected" in text
    assert runner.invoke(cli.app, ["game", "show"]).exit_code == 1  # nothing selected, no id
    runner.invoke(cli.app, ["game", "set", "gt7:ps5"])
    assert "* gt7:ps5" in runner.invoke(cli.app, ["game", "list"]).output
    show = json.loads(runner.invoke(cli.app, ["game", "show", "--json"]).output)
    assert set(show) == {"entry", "selected", "guide", "input"}
    assert show["selected"] is True and show["entry"]["id"] == "gt7:ps5"
    assert show["entry"]["fields"]["sector"]["status"] == "not_sent"
    assert show["guide"]["id"] == "gt7" and show["input"]["key"] == "gt7" and show["input"]["enabled"] is True
    other = json.loads(runner.invoke(cli.app, ["game", "show", "acc:ps5", "--json"]).output)
    assert other["selected"] is False and other["guide"] is None and other["input"] is None
    text = runner.invoke(cli.app, ["game", "show"]).output
    assert "Not sent by GT7: sector times" in text
    assert runner.invoke(cli.app, ["game", "show", "nope:pc"]).exit_code == 2


def test_a_running_server_is_asked_and_the_file_is_never_written(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    put_reply = (
        200,
        {"state": {"selected": {"id": "gt7:ps5"}}, "actions": [{"key": "gt7", "action": "enabled", "message": "on"}]},
    )
    server = use(monkeypatch, FakeServer({("GET", "/api/health"): HEALTH, ("PUT", "/api/game"): put_reply}))
    r = runner.invoke(cli.app, ["game", "set", "gt7:ps5", "--console-ip", "192.168.1.100", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output) == {"selected": "gt7:ps5", "via": "server", "actions": put_reply[1]["actions"]}
    assert server.calls[-1] == (
        "PUT",
        "http://127.0.0.1:8797/api/game",
        {"id": "gt7:ps5", "console_ip": "192.168.1.100", "ensure_input": True, "source": "cli"},
    )
    assert not (settings.data_dir / "settings.json").exists()
    refused = use(
        monkeypatch,
        FakeServer({("GET", "/api/health"): HEALTH, ("PUT", "/api/game"): (422, {"detail": "console IP must be"})}),
    )
    r = runner.invoke(cli.app, ["game", "set", "gt7:ps5", "--console-ip", "8.8.8.8"])
    assert r.exit_code == 1 and "console IP must be" in r.output
    assert refused.calls[-1][0] == "PUT" and not (settings.data_dir / "settings.json").exists()


def test_an_older_server_is_never_bypassed(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    use(
        monkeypatch,
        FakeServer({("GET", "/api/health"): HEALTH, ("PUT", "/api/game"): (404, {"detail": "Not Found"})}),
    )
    r = runner.invoke(cli.app, ["game", "set", "f1_25:ps5"])
    assert r.exit_code == 1
    assert "predates game selection: update it and restart" in r.output
    assert not (settings.data_dir / "settings.json").exists()
    use(monkeypatch, FakeServer({("GET", "/api/health"): HEALTH, ("DELETE", "/api/game"): (404, None)}))
    assert runner.invoke(cli.app, ["game", "clear"]).exit_code == 1
    assert not (settings.data_dir / "settings.json").exists()
