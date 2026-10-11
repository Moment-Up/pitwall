"""AI engineer: intent recognition, grounding validation, graceful LLM failure, provider contract, strategy."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from pitwall.ai.engineer import RaceEngineer, detect_intent
from pitwall.ai.facts import FactSheet, fmt_lap
from pitwall.ai.grounding import check_grounding, strip_citations
from pitwall.ai.providers import LLMResult, LLMUnavailable, OpenAICompatibleProvider, ProviderHealth
from pitwall.analysis.strategy import fuel_estimate, pit_window, tyre_estimate


# ---------------------------------------------------------------- intents (voice-command interpretation)
@pytest.mark.parametrize(
    ("q", "intent", "corner"),
    [
        ("Engineer, why am I losing time through Turn 7?", "losing_time", "T7"),
        ("Where should I be braking for Turn 1?", "braking", "T1"),
        ("How are my tyres?", "tyres", None),
        ("Should I change my front wing?", "setup", None),
        ("What's my fuel situation?", "fuel", None),
        ("Compare that lap to my best.", "compare", None),
        ("Give me one thing to work on.", "focus", None),
        ("turn seven", "corner", "T7"),
        ("t3 braking", "braking", "T3"),
        ("what is my tone like", "general", None),
    ],
)
def test_intents(q: str, intent: str, corner: str | None) -> None:
    i = detect_intent(q)
    assert (i.name, i.corner) == (intent, corner)


def test_quiet_command_parses_lap_count() -> None:
    assert detect_intent("Stop talking for a few laps.").quiet_laps == 3
    assert detect_intent("be quiet for 2 laps").quiet_laps == 2
    assert detect_intent("shut up").quiet_laps is None
    assert detect_intent("ok you can talk again").name == "control_resume"


# ---------------------------------------------------------------- grounding
def _sheet() -> FactSheet:
    fs = FactSheet()
    fs.add("session", "Session: f1_25 at Spa, Race. NOTE: none.")
    fs.add("laps", "Best clean lap this session: lap 4 in 1:45.302.", {"lap": 4, "lap_time_s": 105.302})
    fs.add(
        "corners",
        "T3 (right-hander, apex at 1200 m); brake point on average 12.6 m earlier than reference.",
        {"mean_brake_point_delta_m": -12.6},
        corner="T3",
    )
    fs.add(
        "observations",
        "Coaching observation (lap 5, confidence 0.90): T3: braking 13 m early, losing 0.21 s.",
        {"value": -13.0, "impact_s": 0.21},
        corner="T3",
    )
    fs.add("fuel", "Fuel: using 1.62 kg per lap (median of 4 green laps); 20.1 kg in the tank, enough for 12.4 laps.")
    fs.add("tyres", "Tyres: soft, 6 laps old; wear FL 9.1%, FR 10.2%, RL 6.0%, RR 6.3%.")
    fs.add("reference", "Reference lap for comparisons: lap 4 (this session) in 1:45.302.")
    return fs


def test_grounded_answer_accepts_rounding_signs_laptimes_and_corner_names() -> None:
    facts = _sheet().facts
    ans = "You're braking about 13 m early into Turn 3 [F4], losing 0.2 s; best lap 1:45.302 on lap 4 [F2]."
    g = check_grounding(ans, facts)
    assert g.ok, g
    assert g.cited == ["F4", "F2"]


def test_invented_number_is_rejected() -> None:
    g = check_grounding("Brake 25 m later at T3 [F3] and you'll gain 0.5 s.", _sheet().facts)
    assert not g.ok and set(g.ungrounded_numbers) == {"25", "0.5"}


def test_unknown_citation_is_rejected() -> None:
    g = check_grounding("Fuel is fine [F99].", _sheet().facts)
    assert not g.ok and g.unknown_citations == ["F99"]


def test_strip_citations_for_speech() -> None:
    assert strip_citations("Brake 13 m later [F4], [F5]. Good [F2].") == "Brake 13 m later. Good."


def test_fmt_lap() -> None:
    assert fmt_lap(65_626) == "1:05.626" and fmt_lap(59_000) == "59.000s" and fmt_lap(None) == "no time"


# ---------------------------------------------------------------- engineer with a scripted fake LLM
class FakeProvider:
    name = "fake"

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    async def chat(self, messages: list[dict[str, Any]], **_: Any) -> LLMResult:
        self.calls.append(messages)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResult(text=r, model="fake-model", latency_ms=5)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(True, "fake://", "fake-model", "ok")


async def test_grounded_llm_answer_is_used_and_facts_are_only_input() -> None:
    p = FakeProvider(["You're braking 13 m early into T3 [F4]."])
    ans = await RaceEngineer(p).answer("Why am I slow in turn 3?", _sheet())
    assert not ans.fallback and ans.grounded and ans.model == "fake-model"
    assert ans.speech == "You're braking 13 m early into T3."
    user_msg = p.calls[0][-1]["content"]
    assert "FACTS:" in user_msg and "[F4]" in user_msg  # model sees validated facts, not telemetry


async def test_ungrounded_answer_retried_then_replaced_by_deterministic() -> None:
    p = FakeProvider(["Brake 40 m later [F4].", "Brake 35 m later [F4]."])
    ans = await RaceEngineer(p).answer("Where should I brake for turn 3?", _sheet())
    assert ans.fallback and ans.llm_attempts == 2
    assert "unsupported numbers" in ans.grounding_issues[0]
    assert "[F" in ans.cited_text and "[F" not in ans.text and "40" not in ans.text  # citations stay internal
    assert "Answer again using only numbers" in p.calls[1][-1]["content"]


async def test_retry_can_recover() -> None:
    p = FakeProvider(["Brake 40 m later [F4].", "You're 13 m early at T3 [F4]."])
    ans = await RaceEngineer(p).answer("turn 3 braking?", _sheet())
    assert not ans.fallback and ans.llm_attempts == 2


async def test_llm_unavailable_degrades_gracefully() -> None:
    p = FakeProvider([LLMUnavailable("connection refused")])
    ans = await RaceEngineer(p).answer("What's my fuel situation?", _sheet())
    assert ans.fallback and ans.grounded and "1.62 kg per lap" in ans.text


async def test_no_provider_configured() -> None:
    ans = await RaceEngineer(None).answer("How are my tyres?", _sheet())
    assert ans.fallback and "FL 9.1%" in ans.text


async def test_control_commands_never_reach_llm() -> None:
    p = FakeProvider([])
    ans = await RaceEngineer(p).answer("Stop talking for 2 laps", _sheet())
    assert ans.control == {"action": "quiet", "laps": 2} and p.calls == []


# ---------------------------------------------------------------- provider (OpenAI-compatible contract)
def _transport(fail: bool = False) -> httpx.MockTransport:
    def handler(req: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(503, json={"error": "loading"})
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen-test", "meta": {"n_ctx": 32768}}]})
        if req.url.path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok"})
        body = json.loads(req.content)
        assert body["model"] == "qwen-test" and body["messages"][0]["role"] == "user"
        if "response_format" in body:
            assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "model": "qwen-test",
                "choices": [{"message": {"content": " Copy. "}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 2},
            },
        )

    return httpx.MockTransport(handler)


async def test_provider_discovers_model_and_chats() -> None:
    p = OpenAICompatibleProvider("http://llm/v1", transport=_transport())
    r = await p.chat([{"role": "user", "content": "hi"}], json_schema={"type": "object"})
    assert r.text == "Copy." and r.model == "qwen-test" and r.prompt_tokens == 9
    h = await p.health()
    assert h.ok and h.context_tokens == 32768
    await p.aclose()


async def test_provider_circuit_breaker_opens_after_failures() -> None:
    p = OpenAICompatibleProvider("http://llm/v1", model="m", transport=_transport(fail=True), failure_threshold=2)
    for _ in range(2):
        with pytest.raises(LLMUnavailable):
            await p.chat([{"role": "user", "content": "x"}])
    assert p.breaker_open
    with pytest.raises(LLMUnavailable, match="circuit breaker"):
        await p.chat([{"role": "user", "content": "x"}])
    await p.aclose()


# ---------------------------------------------------------------- strategy calculations
def _laps() -> list[dict[str, Any]]:
    out = []
    for n in range(1, 6):
        out.append(
            {
                "lap_number": n,
                "flags": ["pit_out"] if n == 1 else [],
                "meta": {
                    "fuel_start_kg": 50 - (n - 1) * 1.6,
                    "fuel_end_kg": 50 - n * 1.6,
                    "wear_end": [2.0 * n, 2.2 * n, 1.5 * n, 1.6 * n],
                    "tyre_compound": "medium",
                    "tyre_age_laps": n,
                },
            }
        )
    return out


def test_fuel_estimate_and_margin() -> None:
    fe = fuel_estimate(_laps(), fuel_now_kg=16.0, game_estimate_laps=None, laps_remaining_in_race=12)
    assert fe.per_lap_kg == pytest.approx(1.6) and fe.laps_used == 4  # pit-out lap excluded
    assert fe.laps_of_fuel == pytest.approx(10.0) and fe.margin_laps == pytest.approx(-2.0)
    assert fe.margin_kg == pytest.approx(-3.2)


def test_tyre_wear_regression_and_pit_window() -> None:
    te = tyre_estimate(_laps(), limit_pct=70)
    assert te.wear_rate_pct_per_lap == pytest.approx([2.0, 2.2, 1.5, 1.6])
    assert te.limiting_wheel == "front-right"
    assert te.laps_to_limit == pytest.approx((70 - 11.0) / 2.2, abs=0.1)
    fe = fuel_estimate(_laps(), 30.0, None, 40)
    pw = pit_window(current_lap=6, total_laps=50, tyres=te, fuel=fe)
    assert pw and pw["stop_needed_for_tyres"] and pw["window_close_lap"] == 6 + int(te.laps_to_limit or 0)
    assert pit_window(current_lap=6, total_laps=None, tyres=te, fuel=fe) is None


def test_no_data_means_unknown_not_zero() -> None:
    fe = fuel_estimate([], None, None, None)
    assert fe.per_lap_kg is None and fe.laps_of_fuel is None
    te = tyre_estimate([])
    assert te.wear_now_pct is None and te.laps_to_limit is None


# ---------------------------------------------------------------- what the driver sees: clean, natural answers
def _race_analysis() -> Any:
    """A session shaped like the README screenshots' Austria race: best clean lap 64, last completed lap 71 (a
    partial lap 72 flushed at the end), an observation from lap 71 with confidence 1.00, lap 71 compared."""
    from pitwall.analysis.compare import Compatibility, CornerDelta, CornerMetrics, LapComparison
    from pitwall.core.session_analysis import SessionAnalysis

    def lap(n: int, ms: int | None, clean: bool = True, flags: list[str] | None = None) -> dict[str, Any]:
        return {"lap_number": n, "lap_time_ms": ms, "clean": clean, "flags": flags or [], "s1_ms": None}

    laps = [lap(n, 66_400 + 37 * (n % 5)) for n in range(60, 71) if n != 64]
    laps += [lap(64, 65_626), lap(71, 66_126), lap(72, None, False, ["incomplete"])]
    laps.sort(key=lambda x: x["lap_number"])
    m = CornerMetrics("T6", 10.0)
    corner = CornerDelta("T6", 0.31, -12.4, None, -22.1, None, None, -6.0, None, None, None, None, m, m)
    comp = LapComparison(64, 71, 0.5, [], [], [corner], Compatibility(True))
    obs = {
        "corner": "T6",
        "kind": "low_min_speed",
        "lap_number": 71,
        "confidence": 1.0,
        "text": "T6: minimum speed is 22 km/h lower than your reference (151 vs 173 km/h), losing 1.30 s.",
        "consistency": "6 of the last 6 laps",
        "value": -22.0,
        "impact_s": 1.3,
    }
    return SessionAnalysis(
        session={"id": "s1", "game": "f1_25", "track_name": "Austria", "session_type": "race"},
        laps=laps,
        model=None,
        ref_lap_id=1,
        ref_lap={"lap_number": 64, "session_id": "s1", "lap_time_ms": 65_626},
        comparisons={71: comp},
        observations={71: [obs]},
    )


_INTERNAL = re.compile(r"\[F\d+|\(F\d+\)|\bfacts? F\d+|confidence|coaching observation", re.I)


async def test_last_lap_question_is_about_the_last_completed_lap_not_the_best() -> None:
    from pitwall.ai.facts import build_fact_sheet
    from pitwall.ai.radio_phrasing import radio_answer

    sheet = build_fact_sheet(_race_analysis())
    for q in ("How was my last lap?", "What was my last lap time?", "how was that lap", "previous lap?"):
        assert detect_intent(q).name == "last_lap", q
    assert detect_intent("What's my best lap?").name == "lap_times"
    assert detect_intent("show me my last lap times").name == "lap_times"
    ans = await RaceEngineer(None).answer("How was my last lap?", sheet)
    assert ans.intent == "last_lap" and ans.fallback and ans.grounded
    assert ans.text.startswith("Your last lap, lap 71, was a 1:06.126, clean, 0.500s off your best clean lap (lap 64).")
    # the reference is that same best lap: its comparison would repeat the gap ("lap 64: 0.500s slower")
    assert "against your reference lap" not in ans.text and ans.text.count("0.500s") == 1
    assert "Lap 71, T6, against the reference: lost 0.310s, braking 12 m earlier" in ans.text  # where it went
    assert "lap 72" not in ans.text.lower()  # the partial lap at the end of the session is not a lap driven
    assert check_grounding(ans.cited_text, sheet.facts).ok
    # the radio's instant phrasing (voice hub FAST_INTENTS) says the same lap; the best-lap answer is unchanged
    assert radio_answer("last_lap", sheet) == "Last lap, lap 71, a 1:06.126. 0.5 off your best, lap 64."
    assert radio_answer("lap_times", sheet) == "Best lap is a 1:05.626, lap 64."


async def test_best_or_dirty_last_lap_says_so() -> None:
    from pitwall.ai.facts import FactSheet, build_fact_sheet
    from pitwall.ai.radio_phrasing import radio_answer

    sa = _race_analysis()
    sa.laps = [x for x in sa.laps if x["lap_number"] <= 64]
    assert radio_answer("last_lap", build_fact_sheet(sa)) == "Last lap, lap 64, a 1:05.626. That's your best lap."
    sa = _race_analysis()
    sa.laps[-2] = {**sa.laps[-2], "lap_time_ms": 65_100, "clean": False, "flags": ["invalid"]}
    sheet = build_fact_sheet(sa)
    ans = await RaceEngineer(None).answer("How was my last lap?", sheet)
    assert ans.text.startswith("Your last lap, lap 71, was a 1:05.100, not clean (invalid), 0.526s quicker than")
    assert radio_answer("last_lap", sheet) == (
        "Last lap, lap 71, a 1:05.100, not clean. 0.526 quicker than your best clean lap, lap 64."
    )
    empty = await RaceEngineer(None).answer("How was my last lap?", FactSheet())
    assert empty.text.startswith("I don't have enough data") and radio_answer("last_lap", FactSheet()) is None


async def test_last_lap_answer_never_gives_an_incident_corner_as_technique() -> None:
    from pitwall.ai.facts import build_fact_sheet
    from pitwall.analysis.compare import Compatibility, CornerDelta, CornerMetrics, LapComparison

    sa = _race_analysis()
    ref, crawl = CornerMetrics("T3", 9.0, min_speed_kph=120.0), CornerMetrics("T3", 22.6, min_speed_kph=8.0)
    spun = CornerDelta("T3", 13.619, -42.0, None, -112.0, None, None, -80.0, None, None, None, None, ref, crawl)
    m = CornerMetrics("T6", 10.0)
    t6 = CornerDelta("T6", 0.31, -12.4, None, -22.1, None, None, -6.0, None, None, None, None, m, m)
    sa.comparisons = {71: LapComparison(60, 71, 13.9, [], [], [spun, t6], Compatibility(True))}
    sheet = build_fact_sheet(sa)
    assert [f.data["incident"] for f in sheet.facts if f.corner in ("T3", "T6") and f.topic == "compare"] == [
        True,
        False,
    ]
    ans = await RaceEngineer(None).answer("How was my last lap?", sheet)
    assert "T3" not in ans.text and "13.619" not in ans.text and "42 m" not in ans.text  # a spin is not advice
    assert "Lap 71, T6, against the reference: lost 0.310s" in ans.text  # the biggest technique loss instead
    assert "Lap 71 against your reference lap (lap 60): 13.900s slower." in ans.text  # a different reference: kept
    assert check_grounding(ans.cited_text, sheet.facts).ok


@pytest.mark.parametrize(
    "q",
    [
        "Give me one thing to work on.",
        "Where am I losing the most time?",
        "Where should I brake for turn 6?",
        "Give me a summary of this session.",
        "Compare my latest lap to the reference.",
        "How was my last lap?",
        "What's my best lap?",
        "How are my tyres?",
        "Should I change my front wing?",
        "what is my tone like",
    ],
)
async def test_deterministic_answers_show_no_fact_ids_labels_or_confidence(q: str) -> None:
    from pitwall.ai.facts import build_fact_sheet

    sheet = build_fact_sheet(_race_analysis())
    assert any("confidence 1.00" in f.text for f in sheet.facts)  # the LLM still gets the full fact
    ans = await RaceEngineer(None).answer(q, sheet)
    assert not _INTERNAL.search(ans.text) and not _INTERNAL.search(ans.speech), ans.text
    assert ans.text == ans.speech and ans.text.strip()
    assert check_grounding(ans.cited_text, sheet.facts).ok  # still grounded, by its citations
    assert all(f["id"].startswith("F") for f in ans.facts)  # the facts used are still returned (sources)
    assert not any(_INTERNAL.search(f["plain"]) for f in ans.facts)  # and can be shown in the driver's words


async def test_an_llm_answer_of_citations_alone_is_not_an_answer() -> None:
    p = FakeProvider(["[F4]", "(F4)"])
    ans = await RaceEngineer(p).answer("Why am I slow in turn 3?", _sheet())
    assert ans.fallback and ans.grounding_issues == ["empty answer", "empty answer"] and ans.text.startswith("T3")


async def test_llm_answers_are_shown_without_citations_or_internal_labels() -> None:
    p = FakeProvider(["Coaching observation (lap 5, confidence 0.90): T3: braking 13 m early, losing 0.21 s [F4]."])
    ans = await RaceEngineer(p).answer("Why am I slow in turn 3?", _sheet())
    assert not ans.fallback and ans.grounded and ans.cited_text.endswith("[F4].")
    assert ans.text == ans.speech == "T3: braking 13 m early, losing 0.21 s."
    assert [f["id"] for f in ans.facts] == ["F4"]


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        ("Costing you 1.30 seconds [F32].", "Costing you 1.30 seconds."),
        ("Best lap 1:05.626 on lap 4 [F2], [F3]. Fuel is fine (F7).", "Best lap 1:05.626 on lap 4. Fuel is fine."),
        ("Per fact F12, you brake early (confidence 0.85).", "You brake early."),
        (
            "You brake early at T3, with a confidence of 0.9, losing 0.2 s [F3, F4].",
            "You brake early at T3, losing 0.2 s.",
        ),
        ("The F1 25 car at Spa (see facts F2 and F3) is fine.", "The F1 25 car at Spa is fine."),
        ("I am confident: brake at 120 m.", "I am confident: brake at 120 m."),
        ("Coaching observation: T3 is slow. Coaching observation (lap 4): T5 too.", "T3 is slow. T5 too."),
        ("My coaching observation: brake earlier.", "My coaching observation: brake earlier."),
        (
            "Lap 3: 1:05.626 (clean) sectors 21.123 / 22.456 / 22.047.",
            "Lap 3: 1:05.626 (clean) sectors 21.123 / 22.456 / 22.047.",
        ),
    ],
)
def test_display_text_removes_only_bookkeeping(raw: str, shown: str) -> None:
    from pitwall.ai.grounding import display_text

    assert display_text(raw) == shown


@pytest.mark.parametrize(
    ("raw", "shown"),
    [
        # the session fact says "F2": a bare "(F2)" is the car, even though F2 is also a fact id
        ("Your car (F2) is slower in T3 [F3].", "Your car (F2) is slower in T3."),
        ("Fuel is fine (F4).", "Fuel is fine."),  # a fact id the facts never use as a word: a citation
        ("Fuel is fine (see F2).", "Fuel is fine."),  # an explicit citation form
        ("A Formula F9 car would be quicker.", "A Formula F9 car would be quicker."),
        ("Quicker than (F9) here.", "Quicker than (F9) here."),  # no fact F9: not a citation
        ("Confidence: 0.9 - the data is clear.", "The data is clear."),
        ("Lap 3 was fine. Confidence 0.85. Brake earlier at T3.", "Lap 3 was fine. Brake earlier at T3."),
        ("Look at a lap, e.g. lap 3, i.e. the clean one.", "Look at a lap, e.g. lap 3, i.e. the clean one."),
        ("e.g. lap 3 was clean. it was quick.", "E.g. lap 3 was clean. It was quick."),
        ("-0.2 s at T3 [F3].", "-0.2 s at T3."),
    ],
)
def test_display_text_keeps_the_answers_own_words(raw: str, shown: str) -> None:
    from pitwall.ai.facts import Fact
    from pitwall.ai.grounding import display_text

    facts = [
        Fact("F2", "session", "Session: F1 25, Austria, race; car: F2 2025.", {}),
        Fact("F3", "corners", "T3: braking 13 m early.", {}),
        Fact("F4", "fuel", "Fuel: using 1.20 kg per lap.", {}),
    ]
    assert display_text(raw, facts) == shown


# ---------------------------------------------------------------- game capabilities (pitwall.games)
@pytest.mark.parametrize(
    ("q", "intent"),
    [
        ("Do I have any damage?", "damage"),
        ("Is my front wing broken?", "damage"),
        ("How much battery have I got?", "ers"),
        ("Can I use DRS here?", "ers"),
        ("What were my sector times?", "sectors"),
        ("Show me my splits", "sectors"),
        ("Any yellow flags out there?", "flags"),
        ("Is the safety car out?", "flags"),
        ("Is it going to rain?", "weather"),
        ("What's the track temperature?", "weather"),
        ("Should I change my front wing?", "setup"),  # "wing" alone stays a setup question
        ("Is my braking OK in sector two?", "braking"),  # braking wins over the sector it names
        ("how are my tyre temps", "tyres"),
    ],
)
def test_capability_intents(q: str, intent: str) -> None:
    assert detect_intent(q).name == intent


def _game_analysis(game: str, platform: str) -> Any:
    sa = _race_analysis()
    sa.session = {**sa.session, "game": game, "platform": platform, "track_name": "Silverstone"}
    return sa


async def test_ac_sheet_says_what_the_game_does_not_send() -> None:
    from pitwall.ai.engineer import Intent, deterministic_answer
    from pitwall.ai.facts import build_fact_sheet

    sheet = build_fact_sheet(_game_analysis("ac", "ps5"))
    session = next(f for f in sheet.facts if f.topic == "session")
    assert session.text.startswith("Session: Assetto Corsa on PS5 (PS4 version) at Silverstone")
    assert session.data["game_entry"] == "ac:ps5"
    assert not any("not yet known" in f.text for f in sheet.facts)  # fuel never arrives from AC: not "yet"
    game = {f.data["group"]: f for f in sheet.facts if f.topic == "game"}
    assert {"fuel", "tyres", "strategy", "damage", "ers", "sectors", "flags", "weather", "setup"} == set(game)
    assert game["tyres"].say == (
        "Assetto Corsa doesn't send tyre temperatures, tyre wear, tyre pressures or brake temperatures."
    )
    assert game["tyres"].text.startswith("Game capability (Assetto Corsa, PS5 (PS4 version)): ")
    for q, name in (("How are my tyres?", "tyres"), ("What's my fuel?", "fuel"), ("Any damage?", "damage")):
        facts = RaceEngineer._select(Intent(name), sheet)
        det = deterministic_answer(Intent(name), facts, sheet)
        assert check_grounding(det, facts).ok, det
        ans = await RaceEngineer(None).answer(q, sheet)
        assert ans.intent == name and ans.grounded and ans.model is None
    ans = await RaceEngineer(None).answer("How are my tyres?", sheet)
    assert ans.text == "Assetto Corsa doesn't send tyre temperatures, tyre wear, tyre pressures or brake temperatures."


def test_f1_sheet_has_only_the_damage_game_fact() -> None:
    from pitwall.ai.facts import build_fact_sheet

    sheet = build_fact_sheet(_game_analysis("f1_25", "ps5"))
    game = [f for f in sheet.facts if f.topic == "game"]
    assert [f.data["group"] for f in game] == ["damage"]
    assert game[0].say == "F1 25 sends car damage, but Pitwall reads only tyre wear from it so far."
    assert any("not yet known" in f.text for f in sheet.facts if f.topic == "fuel")  # F1 sends fuel: it will come
    unknown_platform = build_fact_sheet(_game_analysis("f1_25", "unknown"))
    s = next(f for f in unknown_platform.facts if f.topic == "session")
    assert s.text.startswith("Session: F1 25 at Silverstone")  # no platform claim when the game did not say


async def test_capability_only_questions_never_reach_the_llm() -> None:
    from pitwall.ai.facts import build_fact_sheet

    p = FakeProvider([])  # any call would pop from an empty list and fail the test
    sheet = build_fact_sheet(_game_analysis("ac", "ps5"))
    for q in ("How are my tyres?", "Is it raining?", "What's my fuel?", "Any damage?", "What are my sector times?"):
        ans = await RaceEngineer(p).answer(q, sheet, use_llm=True)
        assert ans.fallback and ans.model is None and ans.grounded, q
    assert p.calls == []
    gt7 = build_fact_sheet(_game_analysis("gt7", "ps5"))
    p2 = FakeProvider(["Tyre temps look fine [F1]."])
    await RaceEngineer(p2).answer("How are my tyres?", gt7, use_llm=True)  # GT7 sends temps: the LLM may explain
    assert len(p2.calls) == 1
    system = " ".join(p2.calls[0][0]["content"].split())
    assert "If a fact says the game does not send some data" in system and "never estimate it" in system


async def test_capability_answers_are_grounded_for_every_game() -> None:
    from pitwall import games

    questions = {
        "fuel": "What's my fuel?",
        "tyres": "How are my tyres?",
        "strategy": "What's the strategy?",
        "damage": "Any damage?",
        "ers": "How much battery do I have?",
        "sectors": "What are my sector times?",
        "flags": "Any yellow flags?",
        "weather": "Is it going to rain?",
    }
    answered = 0
    for e in games.entries():
        sheet = games.capability_sheet(e)
        for intent, q in questions.items():
            assert detect_intent(q).name == intent
            ans = await RaceEngineer(None).answer(q, sheet)
            assert check_grounding(ans.cited_text, sheet.facts).ok, (e.id, intent, ans.cited_text)
            if games.capability_only(intent, e):
                assert ans.text == games.capability_sentence(e, games.INTENT_FEATURES[intent]), (e.id, intent)
                answered += 1
    assert answered > 50


async def test_a_fact_is_said_once_even_when_two_slots_pick_it() -> None:
    fs = FactSheet()
    fs.add("tyres", "Current tyre surface temps FL 70 C, FR 54 C, RL 83 C, RR 76 C.", {"temps": [70, 54, 83, 76]})
    ans = await RaceEngineer(None).answer("How are my tyres?", fs)  # no wear fact: the temps fact fills both slots
    assert ans.text == "Current tyre surface temps FL 70 C, FR 54 C, RL 83 C, RR 76 C."


@pytest.mark.parametrize(
    ("q", "intent", "corner"),
    [
        # questions answered by the older intents before game selection keep them (review: new rules come last)
        ("Where should I brake at turn 4 in the rain?", "braking", "T4"),
        ("Am I losing time at turn 3 in sector 1?", "losing_time", "T3"),
        ("Which sector am I losing time in?", "losing_time", None),
        ("How was my last lap in the rain?", "last_lap", None),
        ("What setup for rain?", "setup", None),
        ("Was that lap slower because of the yellow?", "last_lap", None),
        ("Where do I use DRS on my best lap?", "lap_times", None),
        # only what no older rule matched
        ("Did I get a yellow flag in sector 2?", "flags", None),
        ("Is my front wing damaged?", "damage", None),
        ("What were my splits?", "sectors", None),
        ("Where is the DRS zone?", "ers", None),
    ],
)
def test_capability_intents_never_take_over_older_questions(q: str, intent: str, corner: str | None) -> None:
    got = detect_intent(q)
    assert (got.name, got.corner) == (intent, corner)


async def test_f1_questions_about_data_it_sends_are_never_canned() -> None:
    """F1 25 sends flags, ERS, sectors and weather: those questions go to the LLM like any other, and the
    deterministic fallback never tells the driver to "complete a few clean laps" (more laps would not help)."""
    from pitwall import games
    from pitwall.ai.facts import build_fact_sheet

    sheet = build_fact_sheet(_game_analysis("f1_25", "ps5"))
    f1 = games.entry_of_sheet(sheet)
    assert f1 is not None and f1.id == "f1_25:ps5"
    for q in ("Any yellow flags?", "Is there a safety car?", "How much battery do I have?", "Where is the DRS zone?"):
        intent = detect_intent(q).name
        assert not games.capability_only(intent, f1), q
        p = FakeProvider(["Nothing in my notes on that yet."])
        ans = await RaceEngineer(p).answer(q, sheet, use_llm=True)
        assert len(p.calls) == 1 and ans.model == "fake-model", q
        det = await RaceEngineer(None).answer(q, sheet)  # the LLM down
        assert "complete a few clean laps" not in det.text and det.grounded, (q, det.text)
    det = await RaceEngineer(None).answer("What setup for rain?", sheet)
    assert det.intent == "setup" and not det.text.startswith("Session:")
