"""Rig validation kit: files under <data_dir>/validation (atomic writes, run ids, unreadable files, restarts)."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import orjson
import pytest

from pitwall.core.live import LiveState
from pitwall.validate.kit import ValidationKit
from pitwall.validate.model import FORMAT, run_from_dict
from pitwall.validate.store import ValidationStore, dumps, is_run_id, new_run_id, summary_of

EXAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "validation" / "example-run.json"


def example_run() -> dict[str, Any]:
    return dict(json.loads(EXAMPLE.read_text(encoding="utf-8"))["run"])


@pytest.mark.parametrize(
    ("run_id", "ok"),
    [
        ("20261012-193012-a3f1", True),
        ("20261012-193012-A3F1", False),
        ("20261012-193012-a3f", False),
        ("../../etc/passwd", False),
        ("20261012-193012-a3f1/..", False),
        ("2026101a-193012-a3f1", False),
        ("２０２６1012-193012-a3f1", False),  # full-width digits are digits to str.isdigit, not to the kit
        ("", False),
    ],
)
def test_run_ids(run_id: str, ok: bool) -> None:
    assert is_run_id(run_id) is ok
    assert is_run_id(new_run_id())


def test_paths_never_leave_the_validation_folder(tmp_path: Path) -> None:
    store = ValidationStore(tmp_path)
    with pytest.raises(ValueError):
        store.run_dir("../escape")
    with pytest.raises(ValueError):
        store.write_bytes("20261012-193012-a3f1", "../../x.json", b"{}")
    with pytest.raises(ValueError):
        store.write_bytes("20261012-193012-a3f1", "notes.txt", b"{}")


def test_atomic_round_trip_and_summary(tmp_path: Path) -> None:
    store = ValidationStore(tmp_path)
    data = example_run()
    run = run_from_dict(data)
    path = store.save_run(run.id, dumps(run.to_dict()))
    assert path == tmp_path / "validation" / run.id / "run.json"
    assert not list(path.parent.glob("*.tmp"))
    again = run_from_dict(store.load_run(run.id))
    assert again.to_dict() == run.to_dict()
    assert again.evidence.cues[0].onset_vs_point_m == 2.1 and again.items[1].marks[0].notes.startswith("Wheel")
    s = summary_of(again.to_dict())
    assert s["counts"] == {"pass": 1, "fail": 0, "needs_review": 2, "not_run": 1, "skipped": 0} and s["tiers"] == [
        "live"
    ]
    assert store.find_active() == run.id


def test_unknown_format_and_unreadable_files_are_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    store = ValidationStore(tmp_path)
    good = example_run()
    good["status"] = "finished"
    store.save_run(good["id"], orjson.dumps(good))
    bad_format = {**good, "id": "20261013-100000-0000", "format": FORMAT + 1}
    store.save_run(bad_format["id"], orjson.dumps(bad_format))
    store.save_run("20261014-100000-0000", b"{not json")
    with caplog.at_level(logging.WARNING):
        runs = store.list_runs()
    assert [r["id"] for r in runs] == [good["id"]]
    assert "unknown format" in caplog.text and "unreadable" in caplog.text
    with pytest.raises(ValueError, match="unknown format"):
        run_from_dict(bad_format)
    assert store.find_active() is None


class _Drivers:
    active_id = 1

    def list_drivers(self) -> list[Any]:
        return [object()]

    def subscribe(self, fn: Any) -> None:
        pass

    def unsubscribe(self, fn: Any) -> None:
        pass


def fake_runtime(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        live=LiveState(),
        drivers=_Drivers(),
        input_status=lambda: [],
        settings=SimpleNamespace(data_dir=tmp_path, llm_enabled=False),
    )


async def test_restart_resumes_the_active_run_with_a_gap_event(tmp_path: Path) -> None:
    store = ValidationStore(tmp_path)
    data = example_run()
    data["last_saved_unix"] = 1791834620.0
    store.save_run(data["id"], orjson.dumps(data))
    rt = fake_runtime(tmp_path)
    kit = ValidationKit(rt.settings, rt, None, asyncio.get_running_loop())
    try:
        assert kit.run is not None and kit.run.id == data["id"]
        last = kit.run.timeline[-1]
        assert last.kind == "restart" and last.text.startswith("Service restarted: no evidence between")
        assert kit.collector is not None
        with pytest.raises(Exception, match="already active"):
            kit.start_run(None, None, None)
    finally:
        await kit.close()
    saved = run_from_dict(store.load_run(data["id"]))
    assert saved.status == "active" and saved.timeline[-1].kind == "restart"


async def test_a_sender_heard_this_instant_is_fresh(tmp_path: Path) -> None:
    """Regression (found replaying over loopback): ``last_seen_s == 0.0`` is the freshest sender, not a missing one."""
    rt = fake_runtime(tmp_path)
    rt.input_status = lambda: [
        {"key": "f1", "enabled": True, "sources": [{"ip": "127.0.0.1", "packets_per_s": 60.0, "last_seen_s": 0.0}]}
    ]
    kit = ValidationKit(rt.settings, rt, None, asyncio.get_running_loop())
    try:
        kit.start_run(None, None, False)
        assert kit.collector is not None
        kit.collector._sample_inputs()
        assert kit.collector.sender == "loopback" and kit.collector.tier_now() == "loopback"
    finally:
        await kit.close()


def test_fast_save_writes_the_same_json(tmp_path: Path) -> None:
    """``Run.json_obj`` (orjson serialises the dataclasses itself) gives exactly the JSON of ``to_dict``."""
    run = run_from_dict(example_run())
    assert orjson.loads(dumps(run.json_obj())) == orjson.loads(dumps(run.to_dict()))
    assert dumps(run.json_obj()) == dumps(run.to_dict())  # same key order too
