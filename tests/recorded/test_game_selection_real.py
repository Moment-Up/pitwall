"""RECORDED tier: game selection against real captures (F1 25 on PS5, Assetto Corsa PS4 build on a PS5).

Only decoding facts are asserted: what the real packets say (platform, UDP format, sector times, which data AC
sends) resolves to the expected catalogue entry, and a real stream of another game than the selected one is a
mismatch. These never change a capability status (``capabilities.py`` holds the evidence).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pitwall import games
from pitwall.adapters.f1.adapter import F1Adapter
from pitwall.ai.facts import build_fact_sheet
from pitwall.config import Settings
from pitwall.core.runtime import Runtime
from pitwall.core.session import SessionManager
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.ingest.capture import CaptureReader
from pitwall.ingest.router import PacketRouter
from pitwall.model.telemetry import Platform
from pitwall.storage import repo
from tests.conftest import decode_session

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "recorded"
AUSTRIA = ROOT / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
MONZA = ROOT / "f1_25_2025_ps5_monza_race-excerpt.pwcap"
AC = ROOT / "ac_ps5_ks_silverstone_probe-excerpt.pwcap"

pytestmark = [
    pytest.mark.recorded,
    pytest.mark.skipif(not (AUSTRIA.exists() and MONZA.exists() and AC.exists()), reason="recorded excerpts absent"),
]


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[Runtime]:
    rt = Runtime(Settings(_env_file=None, data_dir=tmp_path, llm_enabled=False, voice_enabled=False))  # type: ignore[call-arg]
    yield rt
    rt.close()


@pytest.mark.parametrize("capture", [AUSTRIA, MONZA], ids=["austria", "monza"])
def test_f1_ps5_captures_resolve_to_f1_25_ps5_with_sectors(capture: Path) -> None:
    laps, frames, info, _adapter = decode_session(list(CaptureReader(capture)))
    assert info.platform is Platform.PS5 and info.extra["packet_format"] == 2025
    entry_id = games.resolve(info.game.value, info.platform.value, games.variant_of(info.game.value, 2025))
    assert entry_id == "f1_25:ps5"
    e = games.entry(entry_id)
    assert e is not None and e.feature("sectors").status == "supported"
    assert {f.sector for f in frames} - {None}  # the game reports the sector on every frame
    timed = [lap for lap in laps if lap.lap_time_ms]
    if capture is AUSTRIA:  # three timed laps; the Monza excerpt is part of one lap (no line crossing)
        assert len(timed) == 3
    assert all(lap.sector_times_ms and lap.sector_times_ms[0] for lap in timed)


def test_real_f1_stream_with_forza_selected_is_a_game_mismatch(runtime: Runtime) -> None:
    runtime.store.replace(games.SECTION, games.new_selection("forza_motorsport:pc", "dashboard").section())
    sessions = SessionManager(runtime.writer, runtime.live, runtime.worker, source="udp:20796")
    router = PacketRouter([F1Adapter()], sessions, runtime.live)
    for pkt in CaptureReader(AUSTRIA):  # no socket: the router as the UDP thread would call it
        router.handle(pkt)
        s = runtime.live.session
        if s is not None and s.platform is not Platform.UNKNOWN:
            break  # the participants packet has said which platform sends
    g = runtime.live.snapshot()["game"]
    assert runtime.live.last_detected_game == "f1_25"
    assert g["detected"]["entry_id"] == "f1_25:ps5" and g["detected"]["real"] is True
    assert g["effective_id"] == "f1_25:ps5"
    assert g["mismatch"] == {
        "kind": "game",
        "selected_id": "forza_motorsport:pc",
        "detected_id": "f1_25:ps5",
        "text": "Receiving F1 25, but Forza Motorsport (2023) on PC is selected.",
    }
    router.finish()


def test_ac_ps5_capture_resolves_to_ac_ps5_and_its_sheet_says_what_ac_does_not_send(runtime: Runtime) -> None:
    reader = CaptureReader(AC)
    assert reader.meta.game_hint == "ac-remote" and reader.meta.extra["platform"] == "ps5"
    assert runtime.start_replay(AC, speed=None).done.wait(60)
    runtime.worker.join()
    runtime.writer.flush()
    with runtime.db.read() as c:
        sid = repo.latest_session_id(c)
        assert sid is not None
        row = repo.get_session(c, sid)
    e = games.entry_for_session(row)
    assert e is not None and e.id == "ac:ps5"
    sa = SessionAnalyzer(runtime.db).analyse(sid)
    assert sa is not None
    sheet = build_fact_sheet(sa)
    tyres = next(f for f in sheet.facts if f.topic == "game" and f.data["group"] == "tyres")
    assert tyres.say == "Assetto Corsa doesn't send tyre temperatures, tyre wear, tyre pressures or brake temperatures."
    assert not any("not yet known" in f.text for f in sheet.facts)
