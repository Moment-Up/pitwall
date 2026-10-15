"""``scripts/build_f1db_benchmarks.py``: F1DB CSV -> ``real_f1_benchmarks.json``.

The F1DB release is not committed, so these tests build from a tiny F1DB-shaped CSV set written here (a few rows,
real column names, made-up rows where noted). They check the selection rules, the matching rules and that untrusted
input is refused rather than half-read.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pitwall.adapters.f1.enums import TRACKS
from pitwall.trackdata import real_f1

ROOT = Path(__file__).resolve().parents[2]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_f1db_benchmarks", ROOT / "scripts" / "build_f1db_benchmarks.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_f1db_benchmarks"] = mod
    spec.loader.exec_module(mod)
    return mod


bf = _module()

Table = dict[str, list[dict[str, str]]]


def _q(race: int, pos: int, driver: str, q1: str = "", q2: str = "", q3: str = "", time: str = "") -> dict[str, str]:
    def ms(text: str) -> str:
        if not text:
            return ""
        minutes, rest = text.split(":") if ":" in text else ("0", text)
        return str(round((int(minutes) * 60 + float(rest)) * 1000))

    return {
        "raceId": str(race),
        "positionDisplayOrder": str(pos),
        "positionNumber": str(pos),
        "driverId": driver,
        "time": time,
        "timeMillis": ms(time),
        "q1": q1,
        "q1Millis": ms(q1),
        "q2": q2,
        "q2Millis": ms(q2),
        "q3": q3,
        "q3Millis": ms(q3),
    }


def _fl(race: int, order: int, driver: str, time: str, ms: int, lap: int | None = None, pos: int = 1) -> dict[str, str]:
    return {
        "raceId": str(race),
        "positionDisplayOrder": str(order),
        "positionNumber": str(pos),
        "driverId": driver,
        "lap": "" if lap is None else str(lap),
        "time": time,
        "timeMillis": str(ms),
    }


def _race(rid: int, date: str, gp: str, circuit: str, layout: str, quali: str = "") -> dict[str, str]:
    return {
        "id": str(rid),
        "year": date[:4],
        "date": date,
        "grandPrixId": gp,
        "circuitId": circuit,
        "circuitLayoutId": layout,
        "qualifyingDate": quali,
    }


def tables() -> Table:
    """Austria (spielberg-3, matched), Monaco (length mismatch), Silverstone (sheet cites silverstone-8), Zandvoort
    (effective layout differs from its latest race's), Las Vegas (a wet pole). Times of real races are real; rows
    marked "made up" exist only to exercise a rule."""
    return {
        "layouts": [
            {"id": "spielberg-2", "circuitId": "spielberg", "effective": "false", "length": "5.942"},
            {"id": "spielberg-3", "circuitId": "spielberg", "effective": "true", "length": "4.326"},
            {"id": "monaco-6", "circuitId": "monaco", "effective": "true", "length": "3.337"},
            {"id": "silverstone-8", "circuitId": "silverstone", "effective": "true", "length": "5.891"},
            {"id": "zandvoort-4", "circuitId": "zandvoort", "effective": "false", "length": "4.252"},
            {"id": "zandvoort-5", "circuitId": "zandvoort", "effective": "true", "length": "4.259"},
            {"id": "las-vegas-1", "circuitId": "las-vegas", "effective": "true", "length": "6.201"},
        ],
        "circuits": [{"id": c} for c in ("spielberg", "monaco", "silverstone", "zandvoort", "las-vegas")],
        "races": [
            _race(1, "1987-08-16", "austria", "spielberg", "spielberg-2"),
            _race(2, "2020-07-12", "styria", "spielberg", "spielberg-3"),
            _race(3, "2025-06-29", "austria", "spielberg", "spielberg-3", "2025-06-28"),
            _race(4, "2026-06-28", "austria", "spielberg", "spielberg-3", "2026-06-27"),
            _race(5, "2026-12-20", "austria", "spielberg", "spielberg-3"),  # made up: scheduled, no results yet
            _race(6, "2025-05-25", "monaco", "monaco", "monaco-6", "2025-05-24"),
            _race(7, "2025-07-06", "great-britain", "silverstone", "silverstone-8", "2025-07-05"),
            _race(8, "2025-08-31", "netherlands", "zandvoort", "zandvoort-4"),  # made up: latest race on an old layout
            _race(9, "2025-11-23", "las-vegas", "las-vegas", "las-vegas-1", "2025-11-22"),
        ],
        "qualifying": [
            _q(1, 1, "nelson-piquet", time="1:23.357"),
            _q(2, 1, "lewis-hamilton", "1:17.825", "1:17.938", "1:19.273"),
            _q(3, 1, "lando-norris", "1:04.672", "1:04.410", "1:03.971"),
            _q(3, 2, "charles-leclerc", "1:04.581", "1:04.304", "1:04.492"),
            _q(4, 1, "george-russell", "1:07.398", "1:06.979"),  # made up: no Q3 ran, so Q2 decides
            _q(6, 1, "lando-norris", "1:11.285", "1:10.570", "1:09.954"),
            _q(7, 1, "max-verstappen", "1:25.886", "1:25.316", "1:24.892"),
            _q(9, 1, "lando-norris", "1:55.473", "1:51.379", "1:47.934"),
        ],
        "fastest": [
            _fl(2, 1, "carlos-sainz-jr", "1:05.619", 65619, 68),
            _fl(3, 1, "oscar-piastri", "1:07.924", 67924, 59),
            _fl(4, 1, "kimi-antonelli", "1:10.374", 70374, 59),
            _fl(4, 2, "george-russell", "1:10.374", 70374, 60),  # made up: a shared fastest lap
            _fl(4, 3, "lando-norris", "1:10.400", 70400, 61, pos=3),
            _fl(7, 1, "oscar-piastri", "1:29.337", 89337, 51),
            _fl(9, 1, "max-verstappen", "1:33.365", 93365, 50),
        ],
        "drivers": [
            {"id": d, "name": n}
            for d, n in (
                ("nelson-piquet", "Nelson Piquet"),
                ("lewis-hamilton", "Lewis Hamilton"),
                ("lando-norris", "Lando Norris"),
                ("charles-leclerc", "Charles Leclerc"),
                ("george-russell", "George Russell"),
                ("max-verstappen", "Max Verstappen"),
                ("carlos-sainz-jr", "Carlos Sainz Jr."),
                ("oscar-piastri", "Oscar Piastri"),
                ("kimi-antonelli", "Kimi Antonelli"),
                ("jacques-villeneuve-sr", "Jacques Villeneuve, Sr."),
                ("nico-hulkenberg", "Nico Hülkenberg"),
            )
        ],
        "grands_prix": [
            {"id": g, "fullName": n}
            for g, n in (
                ("austria", "Austrian Grand Prix"),
                ("styria", "Styrian Grand Prix"),
                ("monaco", "Monaco Grand Prix"),
                ("great-britain", "British Grand Prix"),
                ("netherlands", "Dutch Grand Prix"),
                ("las-vegas", "Las Vegas Grand Prix"),
            )
        ],
    }


def write(folder: Path, data: Table) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for key, rows in data.items():
        columns = list(bf.COLUMNS[key])
        with (folder / bf.FILES[key]).open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
            w.writeheader()
            for row in rows:
                w.writerow({c: row.get(c, "") for c in columns})
    return folder


GAME = {
    17: bf.GameLength(4323, "track_sheets/f1/17_austria.toml", ()),
    5: bf.GameLength(3067, "track_sheets/f1/05_monaco.toml", ()),
    7: bf.GameLength(5890, "track_sheets/f1/07_silverstone.toml", ("silverstone-8",)),
    26: bf.GameLength(4258, "track_sheets/f1/26_zandvoort.toml", ()),
    31: bf.GameLength(6200, "track_sheets/f1/31_las_vegas.toml", ()),
    40: bf.GameLength(4323, "track_sheets/f1/40_austria_reverse.toml", ()),
}


def build(tmp_path: Path, data: Table | None = None, game: dict[int, Any] | None = None) -> dict[str, Any]:
    db, hashes = bf.load_f1db(write(tmp_path / "csv", data or tables()))
    doc: dict[str, Any] = bf.build(
        db, GAME if game is None else game, version="v2026.17.0", released="2026-10-11", inputs=hashes
    )
    return doc


# ------------------------------------------------------------------------------------------- selection rules
def test_every_track_id_gets_an_entry_and_the_document_validates(tmp_path: Path) -> None:
    doc = build(tmp_path)
    assert [int(k) for k in doc["tracks"]] == sorted(TRACKS)
    parsed = real_f1.parse_document(json.loads(bf.render(doc)))
    assert set(parsed.benchmarks) == {7, 17, 31}
    assert parsed.source.inputs == tuple(sorted(doc["source"]["inputs"].items()))


def test_matched_track_times(tmp_path: Path) -> None:
    austria = build(tmp_path)["tracks"]["17"]
    assert austria["matched"] and austria["reason"] is None
    assert (austria["f1db_circuit_id"], austria["f1db_layout_id"], austria["layout_length_m"]) == (
        "spielberg",
        "spielberg-3",
        4326,
    )
    assert (austria["game_length_m"], austria["game_length_source"]) == (4323, "track_sheets/f1/17_austria.toml")
    # latest pole: 2026, whose P1 has no Q3 time, so Q2 decided it; dated on qualifying day
    assert austria["pole"]["time_ms"] == 66979 and austria["pole"]["date"] == "2026-06-27"
    assert austria["pole"]["driver"] == "George Russell" and austria["pole"]["grand_prix"] == "Austrian Grand Prix"
    # the scheduled race (no results) does not hide the latest real one; a shared fastest lap keeps the first listed
    assert austria["race_fastest_lap"]["driver"] == "Kimi Antonelli" and austria["race_fastest_lap"]["lap"] == 59
    # lap record: the fastest race lap on this layout (spielberg-2's 1987 times are another layout)
    assert (austria["lap_record"]["time"], austria["lap_record"]["year"]) == ("1:05.619", 2020)
    assert austria["lap_record"]["grand_prix"] == "Styrian Grand Prix"
    s2025 = austria["seasons"]["2025"]
    assert (s2025["pole"]["time"], s2025["pole"]["driver"]) == (
        "1:03.971",
        "Lando Norris",
    )  # Q3, not Leclerc's faster Q2
    assert s2025["race_fastest_lap"]["time_ms"] == 67924
    assert set(austria["seasons"]) == {"2025", "2026"}


def test_a_pole_slower_than_the_race_fastest_lap_is_flagged(tmp_path: Path) -> None:
    doc = build(tmp_path)
    vegas = doc["tracks"]["31"]
    assert vegas["pole"]["slower_than_race_fastest_lap"] is True
    assert doc["tracks"]["17"]["seasons"]["2025"]["pole"]["slower_than_race_fastest_lap"] is False
    assert real_f1.parse_document(doc).benchmarks[31].band_pole() is None


def test_unmatched_reasons(tmp_path: Path) -> None:
    tracks = build(tmp_path)["tracks"]
    monaco = tracks["5"]
    assert not monaco["matched"] and monaco["f1db_layout_id"] == "monaco-6" and monaco["layout_length_m"] == 3337
    assert "differ by 8.1 %" in monaco["reason"] and "truncated" in monaco["reason"]
    assert "pole" not in monaco and "seasons" not in monaco
    assert "not the layout of its latest race there (zandvoort-4)" in tracks["26"]["reason"]
    assert tracks["40"]["reason"] == bf.REVERSE_REASON
    assert tracks["25"]["reason"] == bf.NO_CIRCUIT_REASON
    assert tracks["21"]["reason"] == bf.SHORT_REASON
    assert tracks["0"]["reason"] == "F1DB v2026.17.0 has no circuit 'melbourne'."


def test_tracks_without_a_game_length_stay_unknown(tmp_path: Path) -> None:
    tracks = build(tmp_path, game={})["tracks"]
    assert not tracks["17"]["matched"]
    assert tracks["17"]["reason"] == bf.NO_GAME_LENGTH_REASON.format(layout="spielberg-3")
    assert tracks["17"]["f1db_layout_id"] == "spielberg-3" and tracks["17"]["game_length_m"] is None


def test_a_sheet_citing_another_layout_is_not_matched(tmp_path: Path) -> None:
    game = dict(GAME)
    game[7] = bf.GameLength(5890, "track_sheets/f1/07_silverstone.toml", ("silverstone-7",))
    reason = build(tmp_path, game=game)["tracks"]["7"]["reason"]
    assert reason == "The track sheet cites F1DB layout silverstone-7, but F1DB's current layout is silverstone-8."


def test_two_current_layouts_are_not_guessed_between(tmp_path: Path) -> None:
    data = tables()
    data["layouts"][0]["effective"] = "true"  # spielberg-2 and spielberg-3 both "effective" (made up)
    assert "lists 2 current layouts" in build(tmp_path, data)["tracks"]["17"]["reason"]


def test_sheet_lengths_read_the_packaged_sheets() -> None:
    lengths = bf.sheet_lengths()
    assert len(lengths) == 28
    assert lengths[7] == bf.GameLength(5890, "track_sheets/f1/07_silverstone.toml", ("silverstone-8",))
    assert lengths[13].cited_layouts == ("suzuka-2",)
    assert lengths[17].length_m == 4323 and lengths[5].length_m == 3067


def test_curated_tables_cover_every_track_id() -> None:
    assert set(bf.CIRCUITS) == set(TRACKS)
    assert (bf.REVERSE | bf.SHORT).issubset(TRACKS)
    assert bf.SEASONS == (2025, 2026)


# ------------------------------------------------------------------------------------------- untrusted input
def _mutate(change: Callable[[Table], None]) -> Table:
    data = tables()
    change(data)
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["layouts"][1].update(id="Spielberg 3"), "is not an F1DB id"),
        (lambda d: d["layouts"][1].update(length="4,326"), "circuit length"),
        (lambda d: d["layouts"][1].update(length="99.000"), "circuit length"),
        (lambda d: d["layouts"][1].update(effective="yes"), "true/false"),
        (lambda d: d["layouts"].append(dict(d["layouts"][1])), "duplicate id"),
        (lambda d: d["races"][2].update(year="2024"), "dated 2025-06-29 in year 2024"),
        (lambda d: d["races"][2].update(date="2025-02-30", year="2025"), "not a real date"),
        (lambda d: d["races"][2].update(circuitLayoutId="monaco-6"), "of another circuit"),
        (lambda d: d["races"][2].update(id="-3"), "integer"),
        (lambda d: d["qualifying"][2].update(q3="1:03.970"), "does not match q3Millis"),
        (lambda d: d["qualifying"][2].update(q3Millis="63971.0"), "integer"),
        (lambda d: d["qualifying"][2].update(q3="1:3.971"), "not a lap time"),
        (lambda d: d["qualifying"][2].update(q3Millis="5"), "integer in"),
        (lambda d: d["qualifying"][2].update(q3=""), "not a lap time"),
        (lambda d: d["qualifying"].append(_q(3, 1, "charles-leclerc", q3="1:04.000")), "two different P1 times"),
        (lambda d: d["qualifying"].append(_q(99, 1, "lando-norris", q3="1:04.000")), "unknown races"),
        (lambda d: d["fastest"][0].update(driverId="<script>"), "is not an F1DB id"),
        (lambda d: d["fastest"][0].update(lap="x"), "integer"),
        (lambda d: d["drivers"][0].update(name="Nelson <b>Piquet</b>"), "unexpected character"),
        (lambda d: d["drivers"][0].update(name=" Nelson Piquet"), "plain name"),
        (lambda d: d["drivers"][0].update(name="x" * 81), "plain name"),
        (lambda d: d["drivers"][0].update(name="Nelson‮Piquet"), "unexpected character"),
        (lambda d: d["grands_prix"][0].update(fullName="Austrian GP\n"), "plain name"),
    ],
)
def test_bad_values_stop_the_build(tmp_path: Path, change: Callable[[Table], None], message: str) -> None:
    with pytest.raises(bf.InputError, match=message):
        build(tmp_path, _mutate(change))


def test_unknown_driver_or_grand_prix_of_a_used_time_stops_the_build(tmp_path: Path) -> None:
    data = tables()
    data["drivers"] = [d for d in data["drivers"] if d["id"] != "carlos-sainz-jr"]
    with pytest.raises(bf.InputError, match="unknown driver 'carlos-sainz-jr'"):
        build(tmp_path, data)


def test_sub_minute_times_and_commas_in_names_are_read(tmp_path: Path) -> None:
    data = tables()
    data["fastest"].append(_fl(1, 1, "jacques-villeneuve-sr", "58.790", 58790, 3))
    db, _ = bf.load_f1db(write(tmp_path / "csv", data))
    assert db.fastest[1].time_ms == 58790
    assert db.drivers["jacques-villeneuve-sr"] == "Jacques Villeneuve, Sr."
    assert db.drivers["nico-hulkenberg"] == "Nico Hülkenberg"
    assert db.poles[1].time_ms == 83357  # an old format's single qualifying time


def test_csv_shape_problems(tmp_path: Path) -> None:
    folder = write(tmp_path / "csv", tables())
    layouts = folder / bf.FILES["layouts"]
    original = layouts.read_text(encoding="utf-8")

    layouts.write_text(original.replace('"length"', '"len"').replace("length", "len"), encoding="utf-8")
    with pytest.raises(bf.InputError, match="missing columns"):
        bf.load_f1db(folder)

    layouts.write_text(original + "monaco-7,monaco,false\n", encoding="utf-8")
    with pytest.raises(bf.InputError, match="wrong number of fields"):
        bf.load_f1db(folder)

    layouts.write_text(original + "monaco-7,monaco,false,3.337,extra\n", encoding="utf-8")
    with pytest.raises(bf.InputError, match="wrong number of fields"):
        bf.load_f1db(folder)

    layouts.write_text(original + f'"{"a" * (bf.MAX_FIELD_CHARS + 10)}",monaco,false,3.337\n', encoding="utf-8")
    with pytest.raises(bf.InputError, match="unreadable CSV"):
        bf.load_f1db(folder)
    assert csv.field_size_limit() != bf.MAX_FIELD_CHARS  # the process-wide limit is restored

    layouts.write_text(original + '"monaco-7,monaco,false,3.337\n', encoding="utf-8")
    with pytest.raises(bf.InputError, match="unreadable CSV"):
        bf.load_f1db(folder)

    layouts.write_bytes(original.encode() + b"\xff\xfe,monaco,false,3.337\n")
    with pytest.raises(bf.InputError, match="unreadable CSV"):
        bf.load_f1db(folder)

    layouts.write_text("id,id,circuitId,effective,length\n", encoding="utf-8")
    with pytest.raises(bf.InputError, match="duplicate column names"):
        bf.load_f1db(folder)

    layouts.unlink()
    with pytest.raises(bf.InputError, match="missing"):
        bf.load_f1db(folder)
    with pytest.raises(bf.InputError, match="not a folder"):
        bf.load_f1db(tmp_path / "nowhere")


def test_oversized_files_are_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = write(tmp_path / "csv", tables())
    monkeypatch.setattr(bf, "MAX_FILE_BYTES", 100)
    with pytest.raises(bf.InputError, match="larger than 100 bytes"):
        bf.load_f1db(folder)


# ------------------------------------------------------------------------------------------- command line
def test_main_writes_checks_and_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = write(tmp_path / "csv", tables())
    out = tmp_path / "out.json"
    args = [str(folder), "--version", "v2026.17.0", "--released", "2026-10-11", "--out", str(out)]
    assert bf.main([*args, "--check"]) == 1  # no file yet: drift
    assert bf.main(args) == 0
    first = out.read_text(encoding="utf-8")
    assert json.loads(first)["source"]["version"] == "v2026.17.0"
    assert bf.main([*args, "--check"]) == 0  # rebuilds are byte-identical (no timestamp)
    assert out.read_text(encoding="utf-8") == first
    printed = capsys.readouterr().out
    assert "17 Austria" in printed and "spielberg-3" in printed and "track ids matched to F1DB v2026.17.0" in printed
    out.write_text(first.replace("Lando Norris", "Someone Else"), encoding="utf-8")
    assert bf.main([*args, "--check"]) == 1


def test_main_refuses_bad_input_without_writing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = write(tmp_path / "csv", _mutate(lambda d: d["layouts"][1].update(id="BAD ID")))
    out = tmp_path / "out.json"
    assert bf.main([str(folder), "--version", "v2026.17.0", "--released", "2026-10-11", "--out", str(out)]) == 1
    assert not out.exists()
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    "extra",
    [["--version", "2026.17", "--released", "2026-10-11"], ["--version", "v2026.17.0", "--released", "11/10/2026"]],
)
def test_main_validates_its_arguments(tmp_path: Path, extra: list[str]) -> None:
    with pytest.raises(SystemExit):
        bf.main([str(tmp_path), *extra])


def test_the_attribution_names_the_source_licence_and_changes() -> None:
    text = bf.attribution("v2026.17.0")
    assert (
        "F1DB v2026.17.0" in text
        and "CC BY 4.0" in text
        and bf.LICENCE_URL in text
        and "Selected and converted" in text
    )
