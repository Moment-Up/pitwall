"""Per-driver race radio preferences (drivers.RadioCallPrefs, radio_wording): lenient stored parse, strict API input,
partial PATCH merge, and the wording switch of the coaching limits."""

from __future__ import annotations

import pytest

from pitwall.drivers import (
    Driver,
    DriverPreferences,
    DriverValidationError,
    RadioCallPrefs,
    coaching_limits,
    parse_radio_calls,
    parse_radio_wording,
)


def test_stored_values_are_parsed_leniently() -> None:
    p = DriverPreferences.from_stored(
        {"radio_calls": {"rivals": False, "flags": "no", "bogus": False}, "radio_wording": "SIMPLE"}, "Sam"
    )
    assert p.radio_calls == RadioCallPrefs(rivals=False)  # a non-bool falls back to on, unknown keys are ignored
    assert p.radio_wording == "simple"
    bad = DriverPreferences.from_stored({"radio_calls": "all", "radio_wording": "loud"}, "Sam")
    assert bad.radio_calls == RadioCallPrefs() and bad.radio_wording == "auto"
    assert DriverPreferences.from_stored({}, "Sam").to_dict()["radio_calls"] == RadioCallPrefs().to_dict()


def test_api_input_is_strict() -> None:
    assert parse_radio_calls({"damage": False}) == RadioCallPrefs(damage=False)
    for bad in ({"damage": "off"}, {"weather": False}, ["flags"]):
        with pytest.raises(DriverValidationError):
            parse_radio_calls(bad)
    assert parse_radio_wording("standard") == "standard"
    with pytest.raises(DriverValidationError):
        parse_radio_wording("posh")


def test_wording_overrides_the_skill_levels_simple_words() -> None:
    assert coaching_limits("beginner").simple_wording is True
    assert coaching_limits("beginner", "normal", "standard").simple_wording is False
    assert coaching_limits("advanced", "normal", "simple").simple_wording is True
    assert coaching_limits("advanced", "normal", "auto").simple_wording is False
    d = Driver(1, "Sam", 0.0, DriverPreferences(skill_level="advanced", radio_wording="simple"))
    assert d.coaching.simple_wording is True


def test_service_create_and_partial_update(tmp_path: object) -> None:
    from pathlib import Path

    from pitwall.drivers import DriverService
    from pitwall.storage.db import Database, DbWriter

    db = Database(Path(str(tmp_path)) / "t.sqlite3")
    writer = DbWriter(db)
    try:
        svc = DriverService(db, writer, default_name="James")
        sam = svc.create("Sam", radio_calls={"name": False}, radio_wording="simple")
        assert sam.preferences.radio_calls == RadioCallPrefs(name=False) and sam.preferences.radio_wording == "simple"
        sam = svc.update(sam.id, radio_calls={"rivals": False})
        assert sam.preferences.radio_calls == RadioCallPrefs(name=False, rivals=False)  # merged, not replaced
        sam = svc.update(sam.id, skill_level="beginner")
        assert sam.preferences.radio_calls == RadioCallPrefs(name=False, rivals=False)  # untouched
        with pytest.raises(DriverValidationError):
            svc.update(sam.id, radio_calls={"rivals": "maybe"})
    finally:
        writer.close()


def test_api_patch_merges_and_refuses_bad_values(tmp_path: object) -> None:
    from pathlib import Path
    from types import SimpleNamespace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from pitwall.api.routes_drivers import router
    from pitwall.core.live import LiveState
    from pitwall.drivers import DriverService
    from pitwall.storage.db import Database, DbWriter

    db = Database(Path(str(tmp_path)) / "t.sqlite3")
    writer = DbWriter(db)
    try:
        app = FastAPI()
        app.include_router(router)
        app.state.runtime = SimpleNamespace(db=db, writer=writer, live=LiveState(), drivers=DriverService(db, writer))
        c = TestClient(app)
        r = c.post("/api/drivers", json={"name": "Sam", "radio_calls": {"rivals": False}, "radio_wording": "simple"})
        assert r.status_code == 201
        sam = r.json()
        assert sam["preferences"]["radio_calls"]["rivals"] is False and sam["preferences"]["radio_wording"] == "simple"
        assert sam["coaching"]["simple_wording"] is True
        r = c.patch(f"/api/drivers/{sam['id']}", json={"radio_calls": {"damage": False}})
        calls = r.json()["preferences"]["radio_calls"]
        assert calls["rivals"] is False and calls["damage"] is False and calls["flags"] is True  # merged
        assert c.patch(f"/api/drivers/{sam['id']}", json={"radio_calls": {"damage": "no"}}).status_code == 422
        assert c.patch(f"/api/drivers/{sam['id']}", json={"radio_calls": {"weather": False}}).status_code == 422
        assert c.patch(f"/api/drivers/{sam['id']}", json={"radio_wording": "loud"}).status_code == 422
    finally:
        writer.close()
