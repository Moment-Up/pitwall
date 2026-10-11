"""``pitwall update`` (``run_update``) with a fake GitHub list and a fake machine: no network, no terminal, never the
real Pitwall on this computer (health is stubbed)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from pitwall.install import activate, commands, github, versions
from pitwall.install.github import ReleaseInfo


def rel(tag: str) -> ReleaseInfo:
    r = ReleaseInfo.from_dict({"version": tag, "published_at": "2026-10-12T09:00:00Z", "notes": ["New"]})
    assert r is not None
    return r


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """A release folder running ``tag``, the releases GitHub lists, and the answers to questions."""
    asked: list[str] = []

    def make(tag: str, releases: list[str], kind: str = "release") -> Path:
        root = tmp_path / "Pitwall" / f"pitwall-{tag}"
        root.mkdir(parents=True)
        (root / "RELEASE.txt").write_text(f"Pitwall {tag}\n", encoding="utf-8")
        if kind == "git":
            (root / ".git").mkdir()
        monkeypatch.setattr(versions, "code_root", lambda: root)
        monkeypatch.setattr(github, "fetch_releases", lambda: [rel(t) for t in releases])
        return root

    def ask(_self: object, question: str) -> bool:
        asked.append(question)
        return False  # "Not updated."

    from pitwall.config import Settings

    settings = Settings(_env_file=None, data_dir=tmp_path / "data")  # type: ignore[call-arg]
    monkeypatch.setattr("pitwall.config.get_settings", lambda: settings)
    monkeypatch.setattr(activate.System, "health", lambda _self, _port: None)
    monkeypatch.setattr(activate.System, "ask", ask)
    monkeypatch.setattr(activate.System, "has_terminal", lambda _self: True)
    make.asked = asked  # type: ignore[attr-defined]
    return make


def update(**kw: Any) -> int:
    args: dict[str, Any] = {
        "check": False,
        "as_json": False,
        "yes": False,
        "version": None,
        "pre": False,
        "service": None,
        "wait_idle": 0.0,
        "rollback": False,
        "no_backup": False,
    }
    args.update(kw)
    return commands.run_update(**args)


def test_a_pre_release_user_is_offered_the_next_pre_release_without_pre(
    folder: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """The card says "Update available v0.2.0-test.2" to someone on v0.2.0-test.1; the command it shows (no --pre)
    must find that same release, not print "up to date"."""
    folder("v0.2.0-test.1", ["v0.2.0-test.2", "v0.2.0-test.1", "v0.1.0"])
    assert update() == 0
    out = capsys.readouterr().out
    assert "Latest release: v0.2.0-test.2" in out and "Not updated." in out and "up to date" not in out
    assert folder.asked and "Update to v0.2.0-test.2 now?" in folder.asked[0]


def test_a_stable_user_is_not_offered_pre_releases(folder: Any, capsys: pytest.CaptureFixture[str]) -> None:
    folder("v0.2.0", ["v0.3.0-rc.1", "v0.2.0"])
    assert update() == 0
    assert "Pitwall v0.2.0 is up to date." in capsys.readouterr().out and folder.asked == []


def test_check_prints_the_command_without_cd_inside_the_folder(
    folder: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = folder("v0.2.0", ["v0.3.0", "v0.2.0"])
    monkeypatch.chdir(root)
    assert update(check=True) == 0
    assert "To update: uv run pitwall update\n" in capsys.readouterr().out
    monkeypatch.chdir(root.parent)
    assert update(check=True) == 0
    sep = "; " if sys.platform == "win32" else " && "
    assert f'To update: cd "{root}"{sep}uv run pitwall update' in capsys.readouterr().out


def test_a_git_checkout_gets_the_whole_git_route(folder: Any, capsys: pytest.CaptureFixture[str]) -> None:
    folder("v0.2.0", ["v0.3.0"], kind="git")
    assert update() == 2
    err = capsys.readouterr().err
    assert "git pull, then uv sync --all-extras, rebuild the dashboard and restart Pitwall" in err
    assert err.rstrip().endswith("install.md#a-git-clone")
