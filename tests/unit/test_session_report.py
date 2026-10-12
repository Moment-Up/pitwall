"""The session report (``core/report.py``, plan F7): the game as "F1 25 · PS5", Today's 3 things and the goals the
session reached (from the recap), the AI line, and a report that never fails because the recap did."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from pitwall.core import report as R
from pitwall.core.session_analysis import SessionAnalysis, SessionAnalyzer
from pitwall.drivers import DriverService
from pitwall.games import display_label
from pitwall.motivation.service import MotivationService
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from tests.unit.motivation_data import SeedSession, seed, seed_laps

T = datetime(2026, 10, 10, 19, 15).timestamp()


def test_display_label() -> None:
    assert display_label("f1_25", "ps5") == "F1 25 · PS5"
    assert display_label("f1_25", "xbox") == "F1 25 · Xbox"
    assert display_label("forza_motorsport", "pc") == "Forza Motorsport · PC"
    assert display_label("ac", "ps4") == "Assetto Corsa · PS4"
    # GT7 on PS4 and PS5 sends the same packets: the platform is unknown, never guessed
    assert display_label("gt7", "unknown") == display_label("gt7", None) == "GT7"
    assert display_label("synthetic", "pc") == "Synthetic data"
    assert display_label(None) == display_label("unknown") == "Unknown game"
    assert display_label("some_new_game", "ps5") == "some_new_game · PS5"


def _sa(**session: Any) -> SessionAnalysis:
    s = {
        "id": "s1",
        "game": "f1_25",
        "platform": "ps5",
        "track_name": "Austria",
        "session_type_raw": "race",
        "car_name": "Haas",
        "source": "udp:20777",
        "synthetic": False,
        **session,
    }
    lap = {"id": 7, "lap_number": 1, "lap_time_ms": 70_549, "clean": True, "flags": [], "meta": None}
    return SessionAnalysis(session=s, laps=[lap], model=None, ref_lap_id=None, ref_lap=None)


RECAP: dict[str, Any] = {
    "things": {
        "went_well": {
            "text": "New personal best at Austria in the Haas: 1:10.549 on lap 1, 1.196 s faster than before."
        },
        "work_on": {
            "text": "Turn 4: brake 12 m earlier.",
            "evidence": "Seen on 3 of 4 laps compared with your reference",
        },
        "progress": None,
    },
    "why_empty": {"went_well": None, "work_on": None, "progress": "No progress to show yet"},
    "goals_achieved": [
        {
            "title": "A lap under 1:11.000",
            "scope_text": "Austria · Haas",
            "achieved": {"text": "Reached Sat 10 Oct: 1:10.549 on lap 1"},
        }
    ],
}


def test_game_label_three_things_and_goals_reached() -> None:
    out = R.build_report(_sa(), RECAP)
    md = out["markdown"]
    assert out["game_label"] == "F1 25 · PS5"
    assert "\nGame: F1 25 · PS5 | car Haas | source `udp:20777` | 1 lap, 1 clean\n" in md  # one lap: no "1 laps"
    assert (
        "## Today's 3 things\n\n"
        "- **Went well:** New personal best at Austria in the Haas: 1:10.549 on lap 1, 1.196 s faster than before.\n"
        "- **One to work on (this session):** Turn 4: brake 12 m earlier. "
        "_(Seen on 3 of 4 laps compared with your reference)_\n"
        "- **Progress:** _No progress to show yet._"
    ) in md
    assert "## Goals reached\n\n- A lap under 1:11.000 (Austria · Haas): Reached Sat 10 Oct: 1:10.549 on lap 1" in md
    assert out["three_things"] == RECAP["things"] and len(out["goals_achieved"]) == 1


def test_no_recap_no_three_things_and_one_reason_when_nothing_to_say() -> None:
    md = R.build_report(_sa())["markdown"]
    assert "3 things" not in md and "Goals reached" not in md
    empty = {
        "things": {"went_well": None, "work_on": None, "progress": None},
        "why_empty": dict.fromkeys(("went_well", "work_on", "progress"), "No timed laps in this session"),
    }
    md2 = R.build_report(_sa(), empty)["markdown"]
    assert md2.count("No timed laps in this session") == 1 and "## Today's 3 things" in md2


def test_an_f2_session_names_its_car_and_race() -> None:
    """F2 (carclass): the car as "F2 · Art GP '24" (never the raw "Unknown team" fallback) and the game's "Race 2" as
    the feature race, keeping the game's own name."""
    sa = _sa(
        track_name="Jeddah",
        session_type_raw="Race 2",
        car_id="f1:team:158",
        car_name="Art GP '24",
        info={"formula": "F2", "packet_format": 2025},
    )
    md = R.build_report(sa)["markdown"]
    assert md.startswith("# Session report - Jeddah · Feature race (Race 2)\n")
    assert "| car F2 · Art GP '24 |" in md
    md_f1 = R.build_report(_sa())["markdown"]
    assert md_f1.startswith("# Session report - Austria (race)\n")  # no class label: the old title, unchanged


def test_ai_line_and_synthetic() -> None:
    sa = _sa(game="synthetic", platform="pc", synthetic=True)
    sa.ai_pace = {
        "status": "ok",
        "ai_difficulty": 35,
        "gap_ms": 1200,
        "gap_pct": 1.7,
        "driver_best_ms": 70_549,
        "ai_ref_ms": 69_349,
        "field_rank": 8,
        "field_size": 20,
    }
    md = R.build_report(sa)["markdown"]
    assert "SYNTHETIC DATA" in md and "Game: Synthetic data |" in md
    assert (
        "**Pace vs AI (difficulty 35):** best clean lap 1:10.549 vs the typical AI car's 1:09.349: 1.200s slower" in md
    )
    assert " gap" not in md.lower().replace("gap_", "")  # 5.4: pace against the AI never says "gap"


# ---------------------------------------------------------------------------------------------- with a database
@pytest.fixture
def store(tmp_path: Path) -> Iterator[tuple[Database, DbWriter, int]]:
    db = Database(tmp_path / "report.sqlite3")
    writer = DbWriter(db)
    sam = DriverService(db, writer, default_name="Sam").default_id
    seed(writer, SeedSession("a", sam, T, seed_laps([71_745, 72_100])))
    lap_ids = seed(writer, SeedSession("b", sam, T + 600, seed_laps([71_000, 70_549, 70_900])))

    def goal(c: sqlite3.Connection) -> None:
        gid = repo.insert_goal(
            c,
            driver_id=sam,
            kind="lap_time",
            target=71_000,
            params={},
            game="f1_25",
            track_id="f1:17",
            track_name="Austria",
            track_length_m=4318.0,
            car_id="f1:team:7",
            car_class=None,
            car_name="Haas",
            baseline=71_745,
            source="manual",
            basis=None,
        )
        c.execute("UPDATE goals SET after_lap_id=0 WHERE id=?", (gid,))
        repo.mark_goal_achieved(c, gid, unix=T + 700, session_id="b", lap_id=lap_ids[1], value=70_549)

    writer.call(goal)
    yield db, writer, sam
    writer.close()


def test_session_report_uses_the_recap(store: tuple[Database, DbWriter, int]) -> None:
    db, _writer, _sam = store
    analyzer = SessionAnalyzer(db)
    sa = analyzer.analyse("b")
    assert sa is not None
    out = R.session_report(db, sa, analyzer=analyzer)
    md = out["markdown"]
    assert "Game: F1 25 |" in md  # the seeded session has no platform: the game alone
    assert "- **Went well:** New personal best at Austria in the Haas: 1:10.549 on lap 2" in md
    assert "## Goals reached\n\n- A lap under 1:11.000 (Austria · Haas): Reached " in md
    assert out["three_things"] is not None and out["three_things"]["went_well"]["source"] == "pb"


def test_a_failing_recap_never_fails_the_report(
    store: tuple[Database, DbWriter, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, _writer, _sam = store
    sa = SessionAnalyzer(db).analyse("b")
    assert sa is not None

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("recap failed")

    monkeypatch.setattr(MotivationService, "recap", boom)
    out = R.session_report(db, sa)
    assert "3 things" not in out["markdown"] and out["three_things"] is None and out["markdown"].startswith("# Session")
