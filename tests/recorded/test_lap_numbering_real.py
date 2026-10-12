"""RECORDED tier: lap numbers, pit laps, race starts and the radio's lap wording on real F1 25 output (PS5, v1.26).

The radio's lap summary can only be said after the line, when the game's HUD already shows the next lap, so the
owner heard "Lap 66, 1:13.897" while the HUD said 67 and took the radio to be one lap out. Nothing was renumbered:
Pitwall keeps the game's own ``currentLapNum``. The summary now names the lap by what it was ("That lap", "Opening
lap", "Out-lap", "In-lap", "Final lap"), and these real captures pin the facts that wording rests on.

Fixtures (byte-for-byte excerpts of the owner's sessions, ``scripts/excerpt_capture.py``, names scrubbed):

* ``f1_25_2025_ps5_melbourne_race-start-excerpt.pwcap`` (20261011-011513): the grid 164 m *behind* the timing line,
  lights out, lap 1->2 and lap 2->3. Lap 1 used to count as a clean flying lap (the standing-start check only looked
  past the line), was called a personal best and became the reference lap 2 was coached against.
* ``f1_25_2025_ps5_imola_race-pitstop-excerpt.pwcap`` (20261011-195612): pit entry at 4810 m on lap 14, the line
  crossed in the pit lane, the pit exit at 449 m on lap 15, lap 15->16. Lap 15 used to be flagged ``pit_in`` as well
  as ``pit_out`` (pit lane past 100 m counted as an entry), so the radio called the out lap an in-lap.
* ``f1_25_2025_ps5_austria_race-excerpt.pwcap``: the 3-lap race's start, lap changes and chequered flag.

Expected lap times are the game's own (Session History of the player's car), not Pitwall's. Gaps between excerpt
windows are artefacts, so every lap here is also flagged ``incomplete``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pitwall.adapters.f1 import packets as P
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.analysis.laps import LapFlag, LapTrace
from pitwall.config import Settings
from pitwall.core.lap_processor import LapJob, _lap_summary
from pitwall.core.runtime import Runtime
from pitwall.core.session import SessionManager
from pitwall.ingest.capture import CapturedPacket, CaptureReader
from pitwall.ingest.router import PacketRouter
from pitwall.model.telemetry import CarLapHistory
from pitwall.voice.proactive import lap_messages, lap_summary_text
from tests.conftest import decode_session

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
MELBOURNE = FIXTURES / "f1_25_2025_ps5_melbourne_race-start-excerpt.pwcap"
IMOLA = FIXTURES / "f1_25_2025_ps5_imola_race-pitstop-excerpt.pwcap"
AUSTRIA = FIXTURES / "f1_25_2025_ps5_austria_race-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not (MELBOURNE.exists() and IMOLA.exists()), reason="real PS5 lap-numbering excerpts absent"),
]

DRIVER_IN_LAP, DRIVER_OUT_LAP = 2, 3  # LapData.m_driverStatus (docs/research/f1-udp-spec.md)


def _packets(path: Path) -> list[CapturedPacket]:
    reader = CaptureReader(path)
    assert not reader.meta.synthetic
    return list(reader)


def _game_history(packets: list[CapturedPacket]) -> dict[int, int | None]:
    """The player's lap list as the game reports it (Session History): lap number -> lap time."""
    adapter = F1Adapter(field_hz=0)
    out: dict[int, int | None] = {}
    for p in packets:
        for e in adapter.decode(p.data, p.t_recv_ns):
            if isinstance(e, CarLapHistory) and e.is_player:
                out.update({h.lap_number: h.lap_time_ms for h in e.laps if h.lap_time_ms is not None})
    return out


def _driver_status_by_lap(packets: list[CapturedPacket]) -> dict[int, set[int]]:
    """The game's own driverStatus of the player's car per currentLapNum (raw LapData)."""
    out: dict[int, set[int]] = {}
    size = P.LAYOUT_2025.sizes[P.PacketId.LAP_DATA]
    for p in packets:
        if len(p.data) != size or p.data[6] != P.PacketId.LAP_DATA:
            continue
        idx = P.HEADER.unpack_from(p.data, 0)["playerCarIndex"]
        lap = P.LAP_DATA.unpack_from(p.data, P.HEADER.size + idx * P.LAP_DATA.size)
        out.setdefault(lap["currentLapNum"], set()).add(lap["driverStatus"])
    return out


def _laps(path: Path) -> dict[int, LapTrace]:
    laps, _frames, _info, _adapter = decode_session(_packets(path))
    return {lap.lap_number: lap for lap in laps}


def _said(lap: LapTrace) -> str | None:
    return lap_summary_text(_lap_summary(lap, 0), None, None)


@pytest.mark.parametrize("path", [MELBOURNE, IMOLA], ids=lambda p: p.name)
def test_stored_lap_numbers_and_times_are_the_games_own(path: Path) -> None:
    history = _game_history(_packets(path))
    laps = _laps(path)
    timed = {n: lap.lap_time_ms for n, lap in laps.items() if lap.lap_time_ms is not None}
    assert timed and all(history[n] == ms for n, ms in timed.items()), (timed, history)


def test_melbourne_lap_one_from_a_grid_behind_the_line_is_a_standing_start() -> None:
    laps = _laps(MELBOURNE)
    lap1 = laps[1]
    d, v, t = lap1.channels["distance_m"], lap1.channels["speed_kph"], lap1.channels["lap_time_ms"]
    assert d[0] == pytest.approx(-164.2, abs=0.1) and v[0] == 0 and t[0] == 0  # the game's grid slot, timer at 0
    assert LapFlag.STANDING_START in lap1.flags and not lap1.clean
    assert lap1.lap_time_ms == 106_805  # timed by the game like any lap: never dropped from the numbering
    assert LapFlag.STANDING_START not in laps[2].flags
    assert _said(lap1) == "Opening lap, 1:46.805."
    assert _said(laps[2]) == "That lap, 1:35.749."


def test_imola_pit_stop_in_lap_and_out_lap() -> None:
    packets = _packets(IMOLA)
    status = _driver_status_by_lap(packets)
    assert DRIVER_IN_LAP in status[14] and DRIVER_OUT_LAP in status[15]  # the game's own in lap / out lap
    laps = _laps(IMOLA)
    assert LapFlag.PIT_IN in laps[14].flags and LapFlag.PIT_OUT not in laps[14].flags
    assert LapFlag.PIT_OUT in laps[15].flags and LapFlag.PIT_IN not in laps[15].flags
    assert (laps[14].lap_time_ms, laps[15].lap_time_ms) == (94_412, 105_838)
    assert _said(laps[14]) == "In-lap, 1:34.412."
    assert _said(laps[15]) == "Out-lap, 1:45.838."


# ---------------------------------------------------------------- the radio, replayed through the real pipeline
def _replay_radio(path: Path, data_dir: Path) -> Iterator[tuple[dict[str, Any], int | None, list[str]]]:
    """Replay ``path`` through the real pipeline (adapter, router, sessions, lap processor, live state) with the
    analysis run inline, and build each lap's radio messages as ``RadioHub._enqueue_lap`` does. Yields (lap summary,
    the lap number of the game's first player frame after the lap notification, the radio texts)."""
    rt = Runtime(Settings(data_dir=data_dir, llm_enabled=False, voice_enabled=False))

    class _Inline:  # the analysis worker, run on the replay thread: the note comes with the packet that ended the lap
        def submit(self, job: LapJob) -> None:
            rt.processor.process(job)

        def submit_ai_pace(self, job: object) -> None:
            pass

    waiting: list[tuple[dict[str, Any], list[str], object]] = []  # (lap, radio texts, live frame at the note)

    def on_note(kind: str, payload: dict[str, Any]) -> None:
        if kind != "lap":
            return
        snap = rt.live.snapshot()
        clean = [x["lap_time_ms"] for x in snap["laps"] if x.get("clean") and x.get("lap_time_ms")]
        best = min(clean, default=None)
        msgs = lap_messages(
            payload["lap"], payload["observations"], best, snap["reference"], "normal", 0.0, coach=payload.get("coach")
        )
        waiting.append((payload["lap"], [m.text for m in msgs], rt.live.frame))

    rt.live.subscribe(on_note)
    sessions = SessionManager(rt.writer, rt.live, _Inline(), source=f"replay:{path.name}")  # type: ignore[arg-type]
    router = PacketRouter([F1Adapter(field_hz=0)], sessions, rt.live)
    try:
        for p in CaptureReader(path):
            router.handle(p)
            f = rt.live.frame
            while waiting and f is not None and f is not waiting[0][2]:
                lap, texts, _ = waiting.pop(0)
                yield lap, f.lap_number, texts
        router.finish()
        for lap, texts, _ in waiting:
            yield lap, None, texts
    finally:
        rt.close()


@pytest.mark.parametrize("path", [AUSTRIA, MELBOURNE, IMOLA], ids=lambda p: p.name)
def test_radio_names_the_finished_lap_while_the_game_shows_the_next(path: Path, tmp_path: Path) -> None:
    said: dict[int, str] = {}
    for lap, hud, texts in _replay_radio(path, tmp_path):
        n = lap["lap_number"]
        if not texts:
            continue  # no lap time (an excerpt's last, unfinished lap): nothing is said
        if lap.get("final"):
            assert hud in (n, None)  # at the chequered flag the game keeps the final lap's number
        else:
            assert hud == n + 1, (n, hud)  # the lap just finished is the one before the HUD's
        for text in texts:
            assert not text.startswith(f"Lap {n}"), text
        said[n] = texts[0]
    if path == AUSTRIA:
        assert said == {
            1: "Opening lap, 1:28.524.",
            2: "That lap, 1:18.351.",
            3: "Final lap, 1:28.352.",
        }
    elif path == MELBOURNE:
        assert said == {1: "Opening lap, 1:46.805.", 2: "That lap, 1:35.749."}
    else:
        assert said == {14: "In-lap, 1:34.412.", 15: "Out-lap, 1:45.838."}
