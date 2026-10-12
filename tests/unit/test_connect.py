"""Connect page guides: text the driver reads names this install, not the author's machine."""

from __future__ import annotations

from pathlib import Path

import pytest

from pitwall import compat, connect
from pitwall.config import Settings


@pytest.fixture(autouse=True)
def _mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compat.sys, "platform", "darwin")  # the wording under test is the macOS one ("this Mac")


def test_probe_step_names_the_directory_pitwall_runs_from() -> None:
    root = connect.install_dir()
    assert root is not None and (root / "scripts" / "probe_ac.py").is_file()
    assert root == Path(connect.__file__).resolve().parents[2]
    label = connect.ac_guide("192.168.1.20").extras[0].label
    assert label == f"Probe once, on track (Terminal on this Mac, in {connect.display_path(root)})"


def test_probe_step_without_the_repository_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connect, "install_dir", lambda: None)  # an installed package: no scripts/ next to it
    assert connect.ac_guide().extras[0].label == "Probe once, on track (Terminal on this Mac, in the pitwall folder)"


def test_display_path_abbreviates_the_home_folder(tmp_path: Path) -> None:
    assert connect.display_path(Path.home() / "a" / "b") == "~/a/b"
    outside = Path("/opt/pitwall")
    assert connect.display_path(outside) == str(outside)  # outside the home folder: as the OS writes it


def test_unsupported_games_point_to_github_issues() -> None:
    guides = connect.game_guides("192.168.1.10", Settings(_env_file=None))  # type: ignore[call-arg]
    text = " ".join(n for g in guides for n in g.notes) + " ".join(s.note + s.label for g in guides for s in g.steps)
    assert "developer" not in text and "Projects/pitwall" not in text
    record = next(g for g in guides if any("open an issue" in n for n in g.notes))
    assert any(connect.ISSUES_URL in n for n in record.notes)
    assert connect.ISSUES_URL == "https://github.com/Moment-Up/pitwall/issues"


def test_the_f1_push_to_talk_step_uses_the_effective_action_and_the_researched_path() -> None:
    """Setup › Controls: the Connect guide names the UDP Action(s) wheel push-to-talk listens to and EA's menu path
    (Controls > your wheel's preset > UDP Custom Actions); without a layout the deploy setting applies."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    f1 = next(g for g in connect.game_guides("192.168.1.10", s) if g.id == "f1_25")
    step = f1.extras[0]
    assert step.label == connect.PTT_MENU_PATH == "Controls > (your wheel's preset) > UDP Custom Actions"
    assert step.value == "UDP Action 1"
    ptt = {"udp_actions": [3, 1], "from": "layout", "label": "Right thumb button"}
    f1 = next(g for g in connect.game_guides("192.168.1.10", s, ptt_info=ptt) if g.id == "f1_25")
    assert f1.extras[0].value == "UDP Action 3 or 1" and "Right thumb button" in f1.extras[0].note
    info = connect.connect_info(s, None, "tok", [], ptt)
    f1d = next(g for g in info["guides"] if g["id"] == "f1_25")
    assert f1d["extras"][0]["value"] == "UDP Action 3 or 1"
