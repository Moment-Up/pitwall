"""Opt-in online names in "who's ahead?" answers (raceradio.names, race-radio spec P2): off by default; when on, the
name is in that one spoken answer only - never in history, observers, logs, the snapshot, facts, status or storage."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import build_fact_sheet
from pitwall.api.routes_race import router
from pitwall.core.live import LiveState
from pitwall.raceradio.worker import RaceRadioWorker
from pitwall.settings_store import SettingsStore
from pitwall.voice.hub import RadioClient, RadioHub
from pitwall.voice.scheduler import RadioScheduler
from pitwall.voice.speech import to_speech
from pitwall.voice.types import AudioClip
from tests.unit.raceradio_helpers import PLAYER, car, frame, info, participant, participants, timing
from tests.unit.test_ai import _game_analysis
from tests.unit.test_voice_hub import FakeStt, FakeTts

CANARY = "Zz_Canary_42"


class FallbackTts(FakeTts):
    def __init__(self) -> None:
        self.fallback: list[str] = []
        self.neural: list[str] = []

    def synthesize(self, text: str) -> AudioClip:
        self.neural.append(text)
        return super().synthesize(text)

    def synthesize_fallback(self, text: str) -> AudioClip:
        self.fallback.append(text)
        return super().synthesize(text)


def live_race() -> LiveState:
    live = LiveState()
    live.reset_session("s1", "test", False, "f1_25")
    w = RaceRadioWorker(live, start=False)
    w.submit("s1", info(0.0))
    w.submit("s1", participants(0.0, [participant(2, ai=False, driver=None, team=8, name=CANARY),
                                      participant(4, ai=True, driver=54, team=8, name="Driver 05")]))  # fmt: skip
    for i in range(20):
        t = i * 0.5
        w.submit("s1", frame(t, lap=3, pos=5))
        w.submit("s1", timing(t, [car(2, 4, lap=3), car(PLAYER, 5, lap=3, gap_ms=1500), car(4, 6, lap=3, gap_ms=900)]))
    w.process_pending()
    assert live.race is not None and live.race_roster is not None
    return live


async def ask(hub: RadioHub, sent: list[Any], question: str) -> dict[str, Any]:
    n = len(sent)
    hub.ask_text(question)
    end = time.monotonic() + 3.0
    while time.monotonic() < end:
        await asyncio.sleep(0.01)
        new = [m for m in sent[n:] if isinstance(m, dict) and m.get("type") == "say" and m["kind"] == "answer"]
        if new:
            return new[0]
    raise AssertionError("no answer")


async def test_off_by_default_then_only_in_the_one_answer(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    live = live_race()
    sa = _game_analysis("f1_25", "ps5")
    sa.session = {**sa.session, "id": "s1"}
    tts = FallbackTts()
    hub = RadioHub(
        live,
        RaceEngineer(None),
        FakeStt(),
        tts,
        RadioScheduler("normal"),
        fact_sheet=lambda: build_fact_sheet(sa, live.snapshot()),
        to_speech=to_speech,
    )
    observed: list[tuple[str, dict[str, Any]]] = []
    hub.add_observer(lambda kind, payload: observed.append((kind, payload)))
    hub.start()
    sent: list[Any] = []

    async def send(item: Any) -> None:
        sent.append(item)

    await hub.connect(RadioClient(send=send))
    off = await ask(hub, sent, "Who's ahead?")
    assert off["text"] == "The McLaren is ahead, P4, 1.5 seconds."  # a human's car: its team, never its name
    behind = await ask(hub, sent, "who is behind me")
    assert behind["text"] == "Norris is behind, P6, 0.9 seconds."  # an official AI name
    live.race_online_names = True
    on = await ask(hub, sent, "Who's ahead?")
    assert on["text"] == f"{CANARY} is ahead, P4, 1.5 seconds." and on["meta"]["personal"] is True
    assert tts.fallback and not any(CANARY in t for t in tts.neural)  # the name never went to the neural engine
    still = await ask(hub, sent, "who is behind me?")
    assert still["text"] == "Norris is behind, P6, 0.9 seconds."  # official names win
    blobs = [
        json.dumps(list(hub.history)),
        json.dumps(hub.status(), default=str),
        json.dumps([p for _k, p in observed], default=str),
        json.dumps(live.snapshot(include_static=True), default=str),
        json.dumps([f.text for f in build_fact_sheet(sa, live.snapshot()).facts]),
        caplog.text,
        repr(live.race_roster),
    ]
    assert not any(CANARY in b for b in blobs)
    assert "[online name] is ahead" in blobs[0]
    await hub.stop()


def test_settings_api(tmp_path: Any) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = SimpleNamespace(store=store, live=LiveState())
    c = TestClient(app)
    assert c.get("/api/race/settings").json() == {"online_names": False}
    assert c.put("/api/race/settings", json={"online_names": True}).json() == {"online_names": True}
    assert store.get("race_radio") == {"online_names": True}
    assert c.put("/api/race/settings", json={"online_names": "yes"}).status_code == 422
    assert c.put("/api/race/settings", json={"online_names": False, "x": 1}).status_code == 422
