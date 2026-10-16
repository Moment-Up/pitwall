"""ACC on PC (feat/acc) in everything that keys on the game: ACC's circuits share names with F1 25's (Spa, Monza,
Silverstone...) but never borrow F1 25's track sheets, corner names, outlines, real-F1 benchmarks or boards; a stored
ACC session reads as ACC everywhere (labels, the validation run, race radio's position note).

Pure: hand-built rows and the packaged data; no game data, no server.
"""

from __future__ import annotations

from pitwall import games
from pitwall.adapters.acc import tracks
from pitwall.analysis.track_geometry import OUTLINE_GAMES, outline_key
from pitwall.analysis.track_identity import find_sheet, load_sheets
from pitwall.leaderboard import keys
from pitwall.model.telemetry import Game
from pitwall.raceradio.engine import NOTES
from pitwall.trackdata import real_f1
from pitwall.validate.collector import GAME_INTEGRATION, GAME_NAMES

ACC_SPA = "acc:spa"
F1_SPA = "f1:10"  # F1 25's Spa (adapters.f1.enums.TRACKS; track sheet 10_spa.toml)


def test_acc_circuits_never_borrow_f1_track_identity() -> None:
    f1_spa = find_sheet("f1_25", F1_SPA)
    assert f1_spa is not None and "Spa" in f1_spa.layout  # the F1 sheet exists ...
    assert find_sheet(Game.ACC.value, ACC_SPA) is None  # ... but ACC's Spa is another game's track
    assert find_sheet(Game.ACC.value, F1_SPA) is None  # even an F1 id would need "acc" in the sheet's games
    assert all(Game.ACC.value not in s.games for s in load_sheets("f1"))
    assert Game.ACC.value not in OUTLINE_GAMES and outline_key(Game.ACC.value, ACC_SPA) is None
    assert real_f1.benchmark_for(ACC_SPA, track_length_m=tracks.TRACK_LENGTH_M["spa"]) is None
    assert real_f1.mapping_for(ACC_SPA) is None
    names = games.entry("acc:pc").feature("official_corner_names")  # type: ignore[union-attr]
    assert names.status == "not_implemented" and "numbered from your laps" in names.reason


def test_an_acc_lap_has_its_own_board() -> None:
    """The board key keeps the game and ACC's track id (never F1's Spa board); the assist class is the lap's TC level
    on ACC's own scale (a number, never on / off or F1's words: ACC documents no "off" level); the session category
    comes from the type."""
    session = {
        "game": "acc",
        "track_id": ACC_SPA,
        "track_name": "Spa-Francorchamps",
        "track_length_m": 7004.0,
        "car_id": "acc:car:mclaren_720s_gt3",
        "car_name": "McLaren 720S GT3 2019",
        "session_type": "race",
        "session_type_raw": "Race",
        "weather": {"condition": None, "air_temp_c": 21, "track_temp_c": 28},
        "assists": {},
        "info": {"acc_status": "live"},
    }
    raw = keys.raw_of_session(session, {"traction_control": 3, "abs_active": None})
    k = keys.key_of(raw, 7004)
    assert (k.game, k.track_id, k.car_class, k.equal_performance) == ("acc", ACC_SPA, None, None)
    assert (k.category, k.conditions, k.assists) == ("race", "unknown", (("tc", 3),))
    text = keys.encode(k)
    assert text == "acc~acc:spa~7004~acc:car:mclaren_720s_gt3~-~-~race~unknown~t3" and keys.decode(text) == k
    assert keys.key_of({**raw, "game": "f1_25", "track_id": F1_SPA}, 7004) != k


def test_acc_boards_never_rank_laps_at_different_tc_levels_together() -> None:
    """ACC laps carry their TC level (Graphics.TC) in the lap meta: a lap at TC 0 is never on a TC 3 board, an unknown
    level is its own board, and the chip says the level (never "not reported by this game", never full / medium)."""
    base = {"game": "acc", "track_id": ACC_SPA, "car_id": "acc:car:x", "session_type": "race"}
    k0, k3, unk = (keys.key_of({**base, "lap_tc": v}, 7004) for v in (0, 3, None))
    assert len({k0, k3, unk}) == 3
    assert [keys.assists_code(k) for k in (k0, k3, unk)] == ["t0", "t3", "t?"]
    assert [keys.assists_text(k) for k in (k0, k3, unk)] == [
        "Traction control level 0",
        "Traction control level 3",
        "Traction control unknown",
    ]
    assert keys.assist_chips(k3) == [{"key": "tc", "value": 3, "known": True, "label": "Traction control level 3"}]
    assert k3.assists_reported and k3.fields()["assists"] == {"tc": 3}
    for k in (k0, k3, unk):
        assert keys.decode(keys.encode(k)) == k
    assert keys.key_of({**base, "lap_tc": -1}, 7004).assists == (("tc", None),)  # not a level: unknown
    for bad in ("-", "a1.t3", "t3.t3", "tx"):
        try:
            keys.parse_assists("acc", bad)
        except keys.BadKey:
            continue
        raise AssertionError(bad)
    assert keys.parse_assists("acc", "t11") == (("tc", 11),)


def test_stored_acc_sessions_read_as_acc() -> None:
    assert games.display_label("acc", "pc") == "ACC · PC"
    row = {"game": "acc", "platform": "pc", "info": {}, "car_id": "acc:car:x", "session_type_raw": "Qualifying"}
    assert games.entry_for_session(row).id == "acc:pc"  # type: ignore[union-attr]
    fields = games.session_row_fields(row)
    assert fields["game_entry_id"] == "acc:pc" and fields["car_class"] is None
    assert fields["session_label"] == "Qualifying"
    assert (GAME_INTEGRATION["acc"], GAME_NAMES["acc"]) == ("acc", "Assetto Corsa Competizione")
    assert "not checked on a real recording" in NOTES[Game.ACC]
