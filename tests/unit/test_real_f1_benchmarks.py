"""``pitwall.trackdata.real_f1``: the shipped real-F1 benchmarks (F1DB, CC BY 4.0) and their lookups."""

from __future__ import annotations

import copy
import json
import logging
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any, get_args

import pytest

from pitwall import carclass, trackdata
from pitwall.adapters.f1.enums import TRACKS
from pitwall.analysis.compare import LAYOUT_LENGTH_TOLERANCE
from pitwall.storage.repo import BESTS_LENGTH_TOLERANCE
from pitwall.trackdata import real_f1
from pitwall.trackdata.real_f1 import BenchmarkError, band_for, benchmark_for, format_lap_ms, mapping_for

# F1 25 tracks whose current F1DB layout matches the game's lap length at F1DB v2026.17.0. A rebuild that changes this
# set is a deliberate, reviewed change (e.g. a recorded Monaco length fixing its track sheet).
MATCHED = {0, 2, 3, 4, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 20, 26, 27, 29, 30, 31, 32, 42}


@pytest.fixture(scope="module")
def shipped() -> real_f1.RealF1Benchmarks:
    return real_f1.load_benchmarks()


@pytest.fixture(scope="module")
def raw_doc() -> dict[str, Any]:
    doc = trackdata.real_f1_benchmarks_document()
    assert isinstance(doc, dict)
    return doc


@pytest.fixture
def clear_caches() -> Iterator[None]:
    real_f1._load_packaged.cache_clear()
    real_f1._packaged_or_none.cache_clear()
    yield
    real_f1._load_packaged.cache_clear()
    real_f1._packaged_or_none.cache_clear()


# ------------------------------------------------------------------------------------------- the shipped file
def test_every_f1_track_id_has_an_entry(shipped: real_f1.RealF1Benchmarks) -> None:
    assert [t.game_track_id for t in shipped.tracks] == sorted(TRACKS)
    for t in shipped.tracks:
        assert t.track_name == TRACKS[t.game_track_id]
        assert t.track_id == f"f1:{t.game_track_id}"
        assert (t.game_track_id in shipped.benchmarks) == t.matched
        assert (t.reason is None) == t.matched


def test_coverage_is_the_reviewed_set(shipped: real_f1.RealF1Benchmarks) -> None:
    assert set(shipped.benchmarks) == MATCHED


def test_matched_layouts_agree_with_the_game_length_of_the_track_sheet(shipped: real_f1.RealF1Benchmarks) -> None:
    sheets = {doc["game_track_id"]: (name, doc) for name, doc in trackdata.sheet_documents("f1")}
    for tid, bench in shipped.benchmarks.items():
        name, doc = sheets[tid]
        assert bench.game_length_m == doc["lap_length_m"]
        assert bench.mapping.game_length_source == name
        assert abs(bench.game_length_m - bench.layout_length_m) <= 0.03 * max(
            bench.game_length_m, bench.layout_length_m
        )
        # a sheet that cites an F1DB layout id cites this one
        cited = " ".join(line for line in doc.get("checked_against", []) if line.startswith("f1db"))
        if "layout " in cited:
            assert f"layout {bench.f1db_layout_id}" in cited


def test_unmatched_tracks_say_why(shipped: real_f1.RealF1Benchmarks) -> None:
    reasons = {t.game_track_id: t.reason or "" for t in shipped.tracks if not t.matched}
    assert set(reasons) == set(TRACKS) - MATCHED
    for tid in (5, 19):  # Monaco (truncated sheet length), Mexico (the game's lap is about 5 % longer)
        assert "differ by" in reasons[tid]
        assert "more than 3 %" in reasons[tid]
    for tid in (39, 40, 41):
        assert reasons[tid].startswith("Reverse layout")
    for tid in (21, 22, 23, 24):
        assert reasons[tid].startswith("Short layout")
    for tid in (1, 8, 18, 28):
        assert reasons[tid].startswith("Not in F1 25")
    assert "no circuit" in reasons[25]  # Hanoi: never raced
    monaco = mapping_for("f1:5")
    assert monaco is not None and monaco.f1db_layout_id == "monaco-6" and monaco.layout_length_m == 3337


def test_source_carries_version_licence_and_attribution(shipped: real_f1.RealF1Benchmarks) -> None:
    src = shipped.source
    assert (src.name, src.version, src.released, src.licence) == ("F1DB", "v2026.17.0", "2026-10-11", "CC BY 4.0")
    assert src.licence_url == "https://creativecommons.org/licenses/by/4.0/"
    assert "F1DB v2026.17.0" in src.attribution and "CC BY 4.0" in src.attribution
    assert src.release_url.endswith("/releases/tag/v2026.17.0")
    assert src.changes.startswith("Selected by Pitwall")
    assert len(src.inputs) == 7 and all(len(sha) == 64 for _, sha in src.inputs)
    assert "F1 25 is not the real car" in shipped.caveat
    assert real_f1.source() == src


def test_known_historical_times(shipped: real_f1.RealF1Benchmarks) -> None:
    austria = shipped.benchmarks[17]
    assert austria.f1db_layout_id == "spielberg-3"
    s2025 = austria.season(2025)
    assert s2025 is not None and s2025.pole is not None and s2025.race_fastest_lap is not None
    assert (s2025.pole.time_ms, s2025.pole.driver, s2025.pole.date) == (63971, "Lando Norris", "2025-06-28")
    assert (s2025.race_fastest_lap.time_ms, s2025.race_fastest_lap.driver) == (67924, "Oscar Piastri")
    assert s2025.race_fastest_lap.lap == 59
    rec = austria.lap_record
    assert rec is not None
    assert (rec.time_text, rec.driver, rec.year, rec.grand_prix) == (
        "1:05.619",
        "Carlos Sainz Jr.",
        2020,
        "Styrian Grand Prix",
    )
    assert shipped.benchmarks[7].f1db_layout_id == "silverstone-8"


def test_times_are_consistent(shipped: real_f1.RealF1Benchmarks) -> None:
    for bench in shipped.benchmarks.values():
        assert bench.pole is not None and bench.race_fastest_lap is not None and bench.lap_record is not None
        assert bench.pole.session == "qualifying" and bench.pole.lap is None
        assert bench.race_fastest_lap.session == bench.lap_record.session == "race"
        assert bench.lap_record.time_ms <= bench.race_fastest_lap.time_ms
        assert bench.seasons, bench.track_name
        latest_year = max(s.year for s in bench.seasons)
        assert bench.pole.year == latest_year  # the latest pole is the latest season's (2025 or 2026)
        for season in bench.seasons:
            for t in (season.pole, season.race_fastest_lap):
                assert t is None or (t.year == season.year and t.date.startswith(str(season.year)))


def test_a_wet_pole_is_flagged_and_never_used_for_bands(shipped: real_f1.RealF1Benchmarks) -> None:
    vegas = shipped.benchmarks[31]
    assert vegas.pole is not None and vegas.race_fastest_lap is not None
    assert vegas.pole.slower_than_race_fastest_lap  # 1:47.934 (wet qualifying) vs 1:33.365 in the race
    assert vegas.band_pole() is None
    assert vegas.band_pole(2025) is None
    flagged = [
        b.track_id
        for b in shipped.benchmarks.values()
        for s in b.seasons
        if s.pole and s.pole.slower_than_race_fastest_lap
    ]
    assert flagged == ["f1:31"]
    austria = shipped.benchmarks[17]
    assert austria.band_pole(2025) == austria.season(2025).pole  # type: ignore[union-attr]
    assert austria.band_pole(2024) is None  # not a season on file


def test_tolerance_matches_the_board_layout_rule() -> None:
    assert real_f1.LENGTH_TOLERANCE == LAYOUT_LENGTH_TOLERANCE == BESTS_LENGTH_TOLERANCE


def test_generation_seasons_cover_the_car_generations() -> None:
    assert set(real_f1.GENERATION_SEASON) == set(get_args(carclass.Generation))


# ------------------------------------------------------------------------------------------- lookups
def test_benchmark_for_takes_the_stored_id_or_the_number() -> None:
    bench = benchmark_for("f1:7")
    assert bench is not None and bench is benchmark_for(7)
    assert bench.track_id == "f1:7" and bench.game_track_id == 7 and bench.track_name == "Silverstone"


@pytest.mark.parametrize(
    "track_id", ["f1:-1", "f1:", "f1:7x", "F1:7", "synthetic:coaching-demo", "gt7:7", "", None, -1, True, 999, "f1:999"]
)
def test_benchmark_for_non_f1_or_unknown_ids_is_none(track_id: Any) -> None:
    assert benchmark_for(track_id) is None


@pytest.mark.parametrize("tid", [5, 19, 25, 39, 40, 41, 1, 21])
def test_unmatched_tracks_have_no_benchmark(tid: int) -> None:
    assert benchmark_for(tid) is None
    m = mapping_for(tid)
    assert m is not None and not m.matched and m.reason


def test_session_length_guard() -> None:
    assert benchmark_for("f1:7", track_length_m=5890.0) is not None
    assert benchmark_for("f1:7", track_length_m=5890.0 * 1.029) is not None
    assert benchmark_for("f1:7", track_length_m=5890.0 * 1.04) is None  # another layout of the same id
    assert benchmark_for("f1:7", track_length_m=3000.0) is None
    for unknown in (None, 0.0, -5.0, math.nan, math.inf):
        assert benchmark_for("f1:7", track_length_m=unknown) is not None  # unknown is no veto


def test_season_for_generation() -> None:
    bench = benchmark_for("f1:17")
    assert bench is not None
    s25, s26 = bench.season_for_generation("f1_2025"), bench.season_for_generation("f1_2026")
    assert s25 is not None and s25.year == 2025 and s26 is not None and s26.year == 2026
    assert s26.pole is not None and s25.pole is not None and s26.pole.time_ms > s25.pole.time_ms
    for unknown in ("f1", "f2", "other", "", None):
        assert bench.season_for_generation(unknown) is None
    madrid = benchmark_for("f1:42")  # first raced in 2026
    assert madrid is not None and madrid.season_for_generation("f1_2025") is None


def test_coverage_lists_every_track() -> None:
    assert [m.game_track_id for m in real_f1.coverage()] == sorted(TRACKS)


# ------------------------------------------------------------------------------------------- bands, formatting
@pytest.mark.parametrize(
    ("lap", "band"),
    [
        (90_000, "gold"),
        (100_000, "gold"),
        (103_000, "gold"),
        (103_001, "silver"),
        (105_000, "silver"),
        (105_001, "bronze"),
        (110_000, "bronze"),
        (110_001, None),
        (200_000, None),
    ],
)
def test_band_for_thresholds(lap: int, band: str | None) -> None:
    assert band_for(lap, 100_000) == band


@pytest.mark.parametrize(
    ("lap", "ref"), [(None, 1.0), (1.0, None), (0, 100), (100, 0), (-1, 100), (math.nan, 100), (100, math.inf)]
)
def test_band_for_unknown_is_none(lap: Any, ref: Any) -> None:
    assert band_for(lap, ref) is None


def test_format_lap_ms() -> None:
    assert format_lap_ms(84892) == "1:24.892"
    assert format_lap_ms(58790) == "0:58.790"
    assert format_lap_ms(600_000) == "10:00.000"


# ------------------------------------------------------------------------------------------- validation
def _break(raw_doc: dict[str, Any], path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    doc = copy.deepcopy(raw_doc)
    node = doc
    for key in path[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


_DELETE = object()
_AUSTRIA_POLE_2025 = ("tracks", "17", "seasons", "2025", "pole")


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("schema_version",), 2, "schema_version"),
        (("length_tolerance",), 0.5, "length_tolerance"),
        (("seasons",), [2025, "2026"], "seasons"),
        (("source", "licence"), "CC BY-SA 4.0", "CC BY 4.0"),
        (("source", "attribution"), "F1DB v2026.17.0 data", "must name"),
        (("source", "inputs"), {"evil.sh": "0" * 64}, "input file name"),
        (("source", "inputs"), {}, "no input files"),
        (("source", "version"), "2026.17", "unexpected form"),
        (("caveat",), "", "non-empty"),
        (("tracks",), {}, "no tracks"),
        (("tracks", "7", "game_track_id"), 8, "filed under"),
        (("tracks", "7", "game_track_id"), True, "integer"),
        (("tracks", "7", "reason"), "because", "no reason"),
        (("tracks", "7", "f1db_layout_id"), None, "circuit, layout"),
        (("tracks", "7", "f1db_layout_id"), "Silverstone 8", "unexpected form"),
        (("tracks", "7", "game_length_m"), 7000, "differ by more than 3 %"),
        (("tracks", "7", "game_length_source"), None, "without its source"),
        (("tracks", "5", "pole"), {"time_ms": 70000}, "carries no times"),
        (("tracks", "5", "reason"), None, "must say why"),
        (("tracks", "7", "pole", "time"), "1:24.000", "does not match"),
        (("tracks", "7", "pole", "time_ms"), 5, "integer in"),
        (("tracks", "7", "pole", "date"), "2019-07-05", "is not in"),
        (("tracks", "7", "pole", "date"), "2025-13-40", "ISO date"),
        (("tracks", "7", "pole", "session"), "race", "expected 'qualifying'"),
        (("tracks", "7", "pole", "lap"), 3, "no race lap"),
        (("tracks", "7", "race_fastest_lap", "slower_than_race_fastest_lap"), True, "only a pole"),
        (("tracks", "7", "lap_record", "time_ms"), 99_999, "faster than the lap record"),
        (("tracks", "7", "lap_record", "driver"), _DELETE, "missing"),
        (("tracks", "17", "seasons", "2024"), {"pole": None, "race_fastest_lap": None}, "season '2024'"),
        (("tracks", "17", "seasons", "2025"), {"pole": None, "race_fastest_lap": None}, "empty season"),
        ((*_AUSTRIA_POLE_2025, "year"), 2026, "is not in 2026"),
    ],
)
def test_parse_document_rejects(raw_doc: dict[str, Any], path: tuple[Any, ...], value: Any, message: str) -> None:
    doc = _break(raw_doc, path, value)
    if path == ("tracks", "7", "lap_record", "time_ms"):
        doc["tracks"]["7"]["lap_record"]["time"] = format_lap_ms(99_999)
    with pytest.raises(BenchmarkError, match=message):
        real_f1.parse_document(doc)


def test_a_season_time_from_another_year_is_rejected(raw_doc: dict[str, Any]) -> None:
    doc = copy.deepcopy(raw_doc)
    doc["tracks"]["17"]["seasons"]["2025"]["pole"] = copy.deepcopy(doc["tracks"]["17"]["seasons"]["2026"]["pole"])
    with pytest.raises(BenchmarkError, match="filed under 2025"):
        real_f1.parse_document(doc)


def test_load_benchmarks_from_a_path(tmp_path: Path, raw_doc: dict[str, Any]) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(raw_doc), encoding="utf-8")
    assert set(real_f1.load_benchmarks(good).benchmarks) == MATCHED
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="not valid JSON"):
        real_f1.load_benchmarks(bad)


def test_a_broken_packaged_file_means_unknown_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, clear_caches: None, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(trackdata, "real_f1_benchmarks_document", lambda: {"schema_version": 1})
    with caplog.at_level(logging.ERROR, logger="pitwall.trackdata.real_f1"):
        assert benchmark_for("f1:7") is None
        assert mapping_for("f1:7") is None
        assert real_f1.coverage() == ()
        assert real_f1.source() is None
    assert sum("real F1 benchmarks unavailable" in r.message for r in caplog.records) == 1  # logged once
    with pytest.raises(BenchmarkError):
        real_f1.load_benchmarks()


def test_unreadable_packaged_json_is_a_benchmark_error(monkeypatch: pytest.MonkeyPatch, clear_caches: None) -> None:
    def broken() -> Any:
        return json.loads("{")

    monkeypatch.setattr(trackdata, "real_f1_benchmarks_document", broken)
    with pytest.raises(BenchmarkError, match="not valid JSON"):
        real_f1.load_benchmarks()
    assert benchmark_for(7) is None
