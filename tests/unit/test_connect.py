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
    assert connect.display_path(outside) == "/opt/pitwall"


def test_unsupported_games_point_to_github_issues() -> None:
    guides = connect.game_guides("192.168.1.10", Settings(_env_file=None))  # type: ignore[call-arg]
    text = " ".join(n for g in guides for n in g.notes) + " ".join(s.note + s.label for g in guides for s in g.steps)
    assert "developer" not in text and "Projects/pitwall" not in text
    record = next(g for g in guides if any("open an issue" in n for n in g.notes))
    assert any(connect.ISSUES_URL in n for n in record.notes)
    assert connect.ISSUES_URL == "https://github.com/Moment-Up/pitwall/issues"
