"""``pitwall validate`` on a temporary data folder holding the shared example run."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pitwall.cli import app
from pitwall.config import get_settings
from pitwall.validate.store import ValidationStore

EXAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "validation" / "example-run.json"
RUN_ID = "20261012-193012-a3f1"


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("PITWALL_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    run = json.loads(EXAMPLE.read_text(encoding="utf-8"))["run"]
    ValidationStore(tmp_path).save_run(RUN_ID, json.dumps(run).encode())
    yield tmp_path
    get_settings.cache_clear()


def test_list_show_report(data_dir: Path) -> None:
    r = CliRunner().invoke(app, ["validate", "list"])
    assert r.exit_code == 0, r.output
    assert RUN_ID in r.output and "active" in r.output and "pass 1" in r.output and "live" in r.output
    r = CliRunner().invoke(app, ["validate", "show", "latest"])
    assert r.exit_code == 0 and "Braking calls land on time" in r.output and "6 calls measured, 8 needed" in r.output
    r = CliRunner().invoke(app, ["validate", "report", RUN_ID])
    assert r.exit_code == 0 and r.output.startswith(f"# Pitwall validation run {RUN_ID}")
    assert "(in progress)" in r.output and "| How are my tyres? |" in r.output
    assert "This report never changes capability statuses" in r.output
    r = CliRunner().invoke(app, ["validate", "report", "latest", "--json"])
    rep = json.loads(r.output)
    assert rep["format"] == 1 and rep["in_progress"] is True and rep["tiers"]["live"] > 0


def test_report_out_and_redaction(data_dir: Path) -> None:
    out = data_dir / "report.md"
    r = CliRunner().invoke(app, ["validate", "report", "latest", "--out", str(out), "--redact-transcripts"])
    assert r.exit_code == 0 and out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "| How are my tyres? |" not in text and "| [transcript removed] |" in text  # the steps keep their copy
    r = CliRunner().invoke(app, ["validate", "report", "latest", "--json", "--redact-transcripts"])
    rep = json.loads(r.output)
    rows = [row for it in rep["items"] for t in it["evidence_tables"] if t["title"] == "Questions" for row in t["rows"]]
    assert rows and all(row[2] == "[transcript removed]" for row in rows)


def test_unknown_runs_and_catalog(data_dir: Path) -> None:
    assert CliRunner().invoke(app, ["validate", "show", "20000101-000000-0000"]).exit_code == 1
    assert CliRunner().invoke(app, ["validate", "report", "../etc"]).exit_code == 1
    folder = data_dir / "validation" / "20261013-100000-0000"
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(json.dumps({"format": 99}), encoding="utf-8")
    r = CliRunner().invoke(app, ["validate", "show", "20261013-100000-0000"])
    assert r.exit_code == 1 and "unknown format" in r.output
    r = CliRunner().invoke(app, ["validate", "catalog"])
    assert r.exit_code == 0 and "gt7_ps5" in r.output
    r = CliRunner().invoke(app, ["validate", "catalog", "cues_timing"])
    assert "How it is measured" in r.output and "Braking calls: Off" in r.output
    assert CliRunner().invoke(app, ["validate", "catalog", "nope"]).exit_code == 1


def test_empty_data_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PITWALL_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        assert "No validation runs yet" in CliRunner().invoke(app, ["validate", "list"]).output
        assert CliRunner().invoke(app, ["validate", "show"]).exit_code == 1
    finally:
        get_settings.cache_clear()


def test_show_says_when_there_is_no_evidence(data_dir: Path) -> None:
    run = json.loads(EXAMPLE.read_text(encoding="utf-8"))["run"]
    bare = {**run, "id": "20261013-100000-0001", "evidence": {}}
    ValidationStore(data_dir).save_run(bare["id"], json.dumps(bare).encode())
    r = CliRunner().invoke(app, ["validate", "show", bare["id"]])
    assert r.exit_code == 0 and "Evidence: none" in r.output
    r = CliRunner().invoke(app, ["validate", "show", RUN_ID])
    assert "Evidence: live " in r.output
