"""Rig validation kit: the catalogue (copy, availability, JSON shape) and the radio commands."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pitwall.validate.catalog import BY_ID, CATALOG, GROUPS, Availability, availability, catalog_json, default_items

EXAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "validation" / "example-run.json"
AMERICAN = re.compile(r"\b(color|center|favorite|behavior|analyze|meter|tire|license|gray)s?\b", re.IGNORECASE)
FULL = Availability(hub=True, stt="parakeet", tts="kokoro", game_block=True, drivers=2)


def _copy(item: object) -> list[str]:
    out: list[str] = []
    for v in vars(type(item)).get("__slots__", ()):  # frozen slots dataclass: walk its fields
        x = getattr(item, v)
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, tuple):
            for y in x:
                out += [y] if isinstance(y, str) else _copy(y)
    return out


def test_ids_groups_steps_and_briefs() -> None:
    ids = [it.id for it in CATALOG]
    assert len(ids) == len(set(ids)) == 13
    groups = {g for g, _ in GROUPS}
    for it in CATALOG:
        assert it.group in groups and it.steps and it.prompt and it.rule_text and it.informs
        assert len(it.radio_brief.split()) <= 25, it.id
        keys = [a.key for a in it.attestations]
        assert len(keys) == len(set(keys))
        for text in _copy(it):
            assert not AMERICAN.search(text), (it.id, text)
            assert "capabilities.py" not in text or it.id == "", text


def test_availability_per_requirement() -> None:
    assert all(availability(it, FULL)[0] for it in CATALOG)
    none = Availability()
    reasons = {it.id: availability(it, none)[1] for it in CATALOG}
    assert reasons["radio_ptt"] == reasons["cues_timing"] == "Voice is off on this Mac."
    off = Availability(hub=True, stt="none", stt_reason="speech recognition is switched off on the server", tts="none")
    assert availability(BY_ID["radio_ptt"], off)[1] == "Speech recognition is off on this Mac."
    assert availability(BY_ID["radio_kokoro"], off)[1] == (
        "The engineer voice on this Mac is off, not the natural voice (Kokoro)."
    )
    assert availability(BY_ID["game_selection"], none)[1] == "This Mac has no game choice yet."
    assert reasons["driver_switch"] == "Add a second driver in Settings › Drivers first."
    assert reasons["ipad_home_screen"] is None and reasons["gt7_ps5"] is None
    no_stt = Availability(hub=True, stt="none", stt_reason="Parakeet needs Apple silicon", tts="say")
    ok, why = availability(BY_ID["radio_ptt"], no_stt)
    assert not ok and "Parakeet needs Apple silicon" in (why or "")
    assert not availability(BY_ID["radio_kokoro"], no_stt)[0]
    assert availability(BY_ID["radio_speak_windows"], no_stt)[0]
    assert "ipad_endurance" not in default_items(FULL)  # optional items are off by default
    assert "game_selection" not in default_items(Availability(hub=True, stt="parakeet", tts="kokoro", drivers=2))


def test_catalog_json_matches_the_contract() -> None:
    cat = catalog_json(FULL)
    assert cat["format"] == 1 and [g["id"] for g in cat["groups"]] == [
        "dashboard",
        "radio",
        "coaching",
        "games",
        "drivers",
    ]
    keys = {
        "id",
        "group",
        "title",
        "summary",
        "why",
        "est_minutes",
        "optional",
        "per_driver",
        "scope",
        "prerequisites",
        "steps",
        "attestations",
        "prompt",
        "radio_brief",
        "input_check",
        "informs",
        "rule_text",
        "available",
        "unavailable_reason",
    }
    for it in cat["items"]:
        assert set(it) == keys
        assert all(set(s) == {"text", "detail"} for s in it["steps"])
        assert all(set(i) == {"status_md", "capability_row"} for i in it["informs"])
    assert {v["phrase"] for v in cat["voice_commands"]} >= {"start validation", "finish validation"}
    json.dumps(cat)


def test_example_fixture_uses_catalogue_ids() -> None:
    ex = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert all(i in BY_ID for i in ex["run"]["selected_items"])


def test_radio_ptt_names_the_effective_wheel_action() -> None:
    """Setup › Controls: the radio_ptt step names the UDP Action(s) wheel push-to-talk listens to now, filled in by the
    kit from the effective push-to-talk (the catalogue keeps a placeholder, never a fixed "UDP Action 1")."""
    step = BY_ID["radio_ptt"].steps[2]
    assert step.detail == "F1 25: {ptt}."
    default = next(i for i in catalog_json(FULL)["items"] if i["id"] == "radio_ptt")
    assert default["steps"][2]["detail"] == "F1 25: UDP Action 1."
    mine = next(i for i in catalog_json(FULL, "UDP Action 3 or 1")["items"] if i["id"] == "radio_ptt")
    assert mine["steps"][2]["detail"] == "F1 25: UDP Action 3 or 1."
    assert all("{ptt}" not in (s["detail"] or "") for i in catalog_json(FULL)["items"] for s in i["steps"])


def test_wheel_buttons_item() -> None:
    it = BY_ID["wheel_buttons"]
    assert it.group == "games" and not it.requires and it.scope == "run"
    assert "validated" not in it.summary.lower() and "F1 25" in it.title
    assert availability(it, Availability())[0]  # needs nothing on this Mac but F1 25 data
