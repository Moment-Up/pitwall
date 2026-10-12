"""The rig validation catalogue: what each live test asks the driver to do, and when it is available.

Data only (frozen dataclasses), so a pending check can be added later as an item without new machinery. Copy is
written for someone in the seat: plain British English, numbers as digits, unknown shown as "-". ``informs`` and
``candidate`` name where the evidence belongs in docs/status.md and which capability row it may support, as text:
the kit never edits ``capabilities.py`` (a test enforces that this package does not import it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pitwall.validate import rules as R
from pitwall.validate.model import FORMAT

ItemGroup = Literal["dashboard", "radio", "coaching", "games", "drivers"]
Requires = Literal["hub", "stt", "kokoro", "game_block", "two_drivers"]

GROUPS: tuple[tuple[ItemGroup, str], ...] = (
    ("dashboard", "Dashboard at the wheel"),
    ("radio", "Radio"),
    ("coaching", "Coaching"),
    ("games", "Games"),
    ("drivers", "Drivers"),
)


@dataclass(frozen=True, slots=True)
class Step:
    text: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Attest:
    key: str
    text: str


@dataclass(frozen=True, slots=True)
class Informs:
    status_md: str
    capability_row: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationItem:
    id: str
    group: ItemGroup
    title: str
    short: str  # spoken name in radio replies ("braking calls")
    summary: str
    why: str
    est_minutes: int
    steps: tuple[Step, ...]
    prompt: str
    radio_brief: str  # <= 25 words
    rule_text: str
    informs: tuple[Informs, ...]
    candidate: str  # suggestion for the maintainer when the run supports it
    optional: bool = False
    per_driver: bool = False
    scope: Literal["run", "window"] = "run"
    prerequisites: tuple[str, ...] = ()
    attestations: tuple[Attest, ...] = ()
    input_check: tuple[str, ...] | None = None
    requires: tuple[Requires, ...] = ()


@dataclass(frozen=True, slots=True)
class Availability:
    """What this server can do now (``ValidationKit`` builds it from the hub, live state and driver profiles)."""

    hub: bool = False
    stt: str | None = None
    stt_reason: str | None = None
    tts: str | None = None
    game_block: bool = False
    drivers: int = 1


_H = " (heuristic)"

CATALOG: tuple[ValidationItem, ...] = (
    ValidationItem(
        id="ipad_home_screen",
        group="dashboard",
        title="Home Screen app keeps the screen on",
        short="screen test",
        summary="Drive for five minutes without touching the iPad; the screen must stay on.",
        why="The Home Screen app and its wake lock have only been tried on a desk. A screen that sleeps mid-lap "
        "loses the coach card.",
        est_minutes=10,
        scope="window",
        prerequisites=(
            "Open Pitwall on the iPad from its Home Screen icon (added from the Tailscale address in Safari: "
            "Share › Add to Home Screen).",
        ),
        steps=(
            Step("On the iPad, set Settings › Display & Brightness › Auto-Lock to 2 minutes for this test."),
            Step("Open Drive › Coach."),
            Step("Drive for at least 5 minutes without touching the iPad."),
            Step('Watch that the screen stays on and no "Screen may sleep" chip appears.'),
            Step("Afterwards put Auto-Lock back to what you had."),
        ),
        attestations=(
            Attest("autolock_2min", "Auto-Lock was set to 2 minutes"),
            Attest("did_not_touch", "I did not touch the iPad while driving"),
        ),
        prompt="Did the screen stay on the whole time?",
        radio_brief="Validation: screen test. Drive five minutes without touching the iPad.",
        rule_text="While this test is current the iPad reports every 15 seconds. This passes when the page stayed "
        "visible on a Drive page with "
        "the wake lock on and telemetry live from the console for at least 5 minutes" + _H + ", opened from the "
        "Home Screen icon over HTTPS, with no report more than 45 seconds late. It fails when the page was hidden "
        "or went quiet while you were driving and you say you did not touch the iPad.",
        informs=(Informs("Dashboard v2 › Unverified: Home Screen app, wake lock"),),
        candidate="If you agree with this run, the Dashboard v2 line may say the Home Screen app and wake lock were "
        "checked on the rig, with the date and this run id.",
    ),
    ValidationItem(
        id="ipad_glance",
        group="dashboard",
        title="Glance test at 70 cm (each driver)",
        short="glance test",
        summary="Each driver reads the next corner, the delta and the coaching point from quick glances.",
        why="Glanceability at 70 cm is the main promise of the new dashboard and has not been tried on the rig.",
        est_minutes=10,
        per_driver=True,
        scope="window",
        prerequisites=("iPad on its mount at about 70 cm, the lights as when you race.",),
        steps=(
            Step("Drive 3 laps on Drive › Coach."),
            Step("From quick glances, say the next corner and whether a braking call is coming."),
            Step("Say whether the time gap (delta) shows plus or minus, and its first number."),
            Step("Read the coaching point on a straight."),
            Step("Answer: what did you look at first?", "Corner, delta or something else."),
        ),
        attestations=(
            Attest("read_corner", "I could read the next corner and whether a call was coming"),
            Attest("read_delta", "I could read whether the delta was plus or minus, and its first number"),
            Attest("read_point", "I could read the coaching point on a straight"),
        ),
        prompt="Could you read everything you needed at a glance?",
        radio_brief="Validation: glance test. Three laps on Drive, Coach. Glance at the iPad as you would in a race.",
        rule_text="Only you can judge what you read at a glance. Pitwall shows the laps each driver drove during this "
        "test (3 or more" + _H + ") and whether the iPad was on Drive › Coach.",
        informs=(Informs("Dashboard v2 › glance and family tests (spec 14.5)"),),
        candidate="If every driver said it worked, the glance test (spec 14.5 #1-#2) may be recorded as done for "
        "these drivers.",
    ),
    ValidationItem(
        id="ipad_one_message",
        group="dashboard",
        title="Screen and radio give the same coaching point",
        short="one message test",
        summary="Five laps with the radio live: the coach card and the engineer must give the same point.",
        why="The coach card and the engineer should pick the same coaching point; that has not been seen live.",
        est_minutes=10,
        prerequisites=("Radio live (Drive › Radio › Go live), coaching Normal.",),
        steps=(
            Step("Drive 5 laps."),
            Step("When the engineer gives a coaching point, check the coach card shows the same corner and advice."),
        ),
        prompt="Did the card and the radio always agree?",
        radio_brief="Validation: one message test. Five laps; check the coach card matches what I say.",
        rule_text="For each lap Pitwall knows which points the coach card picked. Every coaching point the radio "
        "started to play must be one of them. This passes after 3 such points with none different; one different "
        "point fails.",
        informs=(Informs("Dashboard v2 › D6 not yet seen live"),),
        candidate="If you agree with this run, D6 (one coaching message) may be marked as seen live.",
    ),
    ValidationItem(
        id="ipad_endurance",
        group="dashboard",
        title="One hour on Drive",
        short="endurance test",
        summary="Keep Drive open for an hour of driving with the radio live.",
        why="Long sessions on the iPad (heat, memory, reloads) have not been tried.",
        est_minutes=65,
        optional=True,
        scope="window",
        steps=(Step("Keep Drive › Coach open for an hour of driving with the radio live."),),
        prompt="Did the screen stay smooth for the whole hour?",
        radio_brief="Validation: endurance test. Keep Drive open for an hour of driving.",
        rule_text="While this test is current and a Drive page is open, the iPad reports its frame rate every 10 "
        "seconds. This passes after an hour (360 reports) with 90 % of them at 45 fps or more" + _H + " and no "
        "reload. Memory use is not available in Safari.",
        informs=(Informs("Dashboard v2 › spec 14.5 #7 (one hour on Drive)"),),
        candidate="If you agree with this run, spec 14.5 #7 may be recorded as done on this iPad.",
    ),
    ValidationItem(
        id="radio_ptt",
        group="radio",
        title="Push-to-talk over Tailscale with an AirPod",
        short="push-to-talk",
        summary="Ask the engineer three questions, from the screen and from your wheel button.",
        why="Speech input on the iPad is still a pending driver test, and the React radio has not been used over "
        "Tailscale HTTPS.",
        est_minutes=10,
        prerequisites=(
            "One AirPod paired with the iPad and in your ear.",
            "Pitwall opened from the Tailscale address (the Home Screen icon is fine).",
        ),
        steps=(
            Step("Drive › Radio › Go live; allow the microphone."),
            Step('Hold the on-screen talk button, ask "How are my tyres?", let go.'),
            Step('Hold your wheel\'s talk button and ask "Where am I losing the most time?"', "F1 25: UDP Action 1."),
            Step("Ask one more question while driving."),
            Step("When you stop, mark each transcript below as heard right or wrong."),
        ),
        attestations=(Attest("airpod_used", "The AirPod was the microphone and the speaker"),),
        prompt="Did the engineer hear you and answer sensibly?",
        radio_brief="Validation: push-to-talk. Ask me two questions, one with your wheel button.",
        rule_text="A round trip is a question heard, answered and starting to play on the iPad. This passes after 2 "
        "round trips" + _H + " on the iPad opened over Tailscale HTTPS, with an AirPod as the microphone (from its "
        "name, or your tick) and at most 1 in 3 questions not heard" + _H + ". Three attempts with no round trip "
        "fail. Quick answers should start within 4 s and engineer answers within 20 s" + _H + ": shown as "
        "warnings.",
        informs=(
            Informs("Phase 5 › Speech input (PTT) on the iPad: pending driver test"),
            Informs("Dashboard v2 › push-to-talk over Tailscale HTTPS"),
        ),
        candidate="If you agree with this run, Phase 5 may say push-to-talk on the iPad was tested live (screen and "
        "wheel), with the date and this run id.",
        requires=("hub", "stt"),
    ),
    ValidationItem(
        id="radio_speak_windows",
        group="radio",
        title="The radio keeps out of braking zones",
        short="speak windows",
        summary="Five laps with the radio live: lap summaries and coaching must start and end on straights.",
        why="Proactive timing has only been tested on generated data.",
        est_minutes=10,
        prerequisites=("Radio live, coaching Normal or Detailed.",),
        steps=(
            Step("Drive 5 or more clean laps and listen."),
            Step(
                "Lap summaries and coaching should start and finish on straights, never into a braking zone or a "
                "corner."
            ),
        ),
        prompt="Did the radio keep out of braking zones and corners?",
        radio_brief="Validation: speak windows. Five laps; notice if I talk into a braking zone.",
        rule_text="For each lap summary or coaching point Pitwall reads your brake and steering while it played, from "
        "the stored lap. Brake at 0.10 or more or steering beyond 0.25" + _H + " is an overlap; ending less than "
        "0.5 s" + _H + " before the next braking is tight. This passes with 6 messages measured on track over 3 "
        "laps"
        + _H
        + ", no overlap and at most 1 tight. Two overlaps, or one into braking of 0.5 or more"
        + _H
        + ", fail.",
        informs=(Informs("Phase 5 › proactive message timing: synthetic only"),),
        candidate="If you agree with this run, the Phase 5 line may say proactive timing was checked live.",
        requires=("hub",),
    ),
    ValidationItem(
        id="radio_kokoro",
        group="radio",
        title="Natural engineer voice heard on track",
        short="natural voice",
        summary="Three laps listening to the natural voice: lap times, coaching and braking calls.",
        why="The neural voice has not been heard in a live session.",
        est_minutes=10,
        prerequisites=(
            "Settings › Radio & voice › Engineer voice: this Mac; Mac voice: bm_fable (or another natural voice).",
        ),
        steps=(
            Step("Drive 3 or more laps with the radio live."),
            Step("Listen to lap times, coaching and braking calls."),
            Step("Note any word or number that sounded wrong."),
        ),
        attestations=(
            Attest("numbers_clear", "Numbers and corner names were clear"),
            Attest("sounded_natural", "The voice sounded natural"),
        ),
        prompt="Did the natural voice sound right on track?",
        radio_brief="Validation: natural voice. Three laps; listen for any word or number that sounds wrong.",
        rule_text="Pitwall counts messages the natural voice rendered that reached the iPad as audio and started "
        "playing. This passes with 5 such messages" + _H + ", at most 20 %" + _H + " in the fallback voice, no "
        "restart of the voice worker, and the iPad set to the Mac's voice.",
        informs=(Informs("Neural radio voice › not heard live yet"),),
        candidate="If you agree with this run, the neural voice line may say it was heard live on the rig.",
        requires=("hub", "kokoro"),
    ),
    ValidationItem(
        id="cues_timing",
        group="coaching",
        title="Braking calls land on time",
        short="braking calls",
        summary="Three laps with calls off, then three to five with calls on: the call must land at or just before "
        "your braking point.",
        why="Live braking calls are tested on generated and recorded data only.",
        est_minutes=20,
        prerequisites=("3 clean laps at this track so you have a reference.", "Radio live."),
        steps=(
            Step("Drive › Radio › Braking calls: Off. Drive 3 laps, braking where you normally do."),
            Step("Set Braking calls: All."),
            Step(
                'Drive 3 to 5 laps. Brake where you normally would; notice whether "brake" lands as you reach '
                "your braking point."
            ),
            Step("Optional: set Focus and drive 2 more laps."),
        ),
        attestations=(Attest("never_after_point", "No call came after my braking point"),),
        prompt="Did the calls land at or just before your braking points?",
        radio_brief="Validation: braking calls. Three laps with braking calls off, then three with them on.",
        rule_text="Each call's key word is measured where the iPad started playing it; more than 5 m past its aim "
        "(the engine's own margin) is late. Your braking is read from the stored lap: the nearest onset within "
        "100 m"
        + _H
        + " of the call's point, by distance, never by corner name. This passes with 8 calls measured"
        + _H
        + " over 3 braking zones"
        + _H
        + ", none late, at most 10 % more than 0.6 s early"
        + _H
        + " and at "
        "most 20 % lost in delivery" + _H + ". Two late calls, or more than 10 % of the calls measured, fail. If you "
        "brake 10 m or more later" + _H + " with calls on than with them off (8 points each), the result is left for "
        "you to check: calls must never delay braking. AI-field heads-ups are counted apart.",
        informs=(Informs("Verified vs unverified › Live braking cues: not yet validated live"),),
        candidate="If you agree with this run, the line may say: validated live on the PS5 (F1 25), with the date "
        "and this run id.",
        requires=("hub",),
    ),
    ValidationItem(
        id="ac_ps5",
        group="games",
        title="Assetto Corsa on the PS5: laps timed and coached",
        short="Assetto Corsa",
        summary="Four or more laps of AC on the PS5 through Pitwall's own client: timed, stored and coached.",
        why="Pitwall's own AC client and service have not run against the console yet.",
        est_minutes=15,
        prerequisites=(
            "Setup › Connect › Assetto Corsa on, platform PS5, the console's address filled in.",
            "AC (PS4 version) running on the PS5.",
        ),
        steps=(
            Step("Start a practice session, one car, one track."),
            Step("Drive out and do at least 4 full laps without pitting."),
            Step("Compare the lap times on Review › Sessions with the game's."),
            Step("Optional, stopped in the pit lane: the input check."),
        ),
        attestations=(Attest("times_match", "Pitwall's lap times match the game's to the millisecond"),),
        prompt="Were your laps timed and coached correctly?",
        radio_brief="Validation: Assetto Corsa. Four full laps without pitting, then compare the lap times.",
        rule_text="Over every live AC session in this run: the handshake answered, 50 packets a second or more"
        + _H
        + ", nothing rejected, 3 timed laps"
        + _H
        + " of which 2 clean"
        + _H
        + ", the track length taken from a "
        "full lap, 3 corners learned and a coaching point, plus your tick that the times match. Five minutes on a "
        "known line with no timed lap, or any rejected packet, fails. The input check records the raw steer at full "
        "lock and whether reverse was seen, for the maintainer.",
        informs=(
            Informs(
                "Other games › Assetto Corsa › Unverified: own client and service",
                "Assetto Corsa (original, PS4 version) · PS5 (backward compatibility)",
            ),
        ),
        candidate="If you agree with this run, the AC PS5 row may say the client and service were run end to end "
        "(laps stored, timed and coached), with the date and this run id.",
        input_check=("centre", "left", "right", "pedals", "reverse"),
    ),
    ValidationItem(
        id="gt7_ps5",
        group="games",
        title="Gran Turismo 7 on the PS5",
        short="Gran Turismo 7",
        summary="Four or more laps of GT7 on one circuit: timed, stored and coached.",
        why="GT7 on the PS5 was run live on 2026-10-11; the session and lap fixes made since have only run on the "
        "recordings of that day.",
        est_minutes=15,
        prerequisites=("Setup › Connect › Gran Turismo 7 on with the PS5's address.",),
        steps=(
            Step("Time Trial or a race on one circuit (not a replay)."),
            Step("Drive 4 or more laps."),
            Step("Compare lap times with the game's."),
            Step("Optional: the input check."),
        ),
        attestations=(Attest("times_match", "Pitwall's lap times match the game's to the millisecond"),),
        prompt="Were your laps timed and coached correctly?",
        radio_brief="Validation: Gran Turismo 7. Four laps on one circuit, then compare the lap times.",
        rule_text="Over every live GT7 session in this run (a session opens when you drive and ends when you leave "
        "the race, a load or a retry; a car reset stays in it): the heartbeat sent without errors, packets from the "
        "console, the packet variant, 50 packets a second or more"
        + _H
        + ", nothing rejected, 3 timed laps on one circuit"
        + _H
        + " of which 2 clean"
        + _H
        + " and a coaching point, plus your tick that the times match. Streaming from menus is shown as streaming, "
        "not driving. The game's best lap is compared with Pitwall's as a warning only.",
        informs=(
            Informs(
                "Verified vs unverified › Gran Turismo 7 (PS5): the session and lap fixes not yet run live",
                "Gran Turismo 7 · PS5 (live_validated)",
            ),
        ),
        candidate="If you agree with this run, the PS5 row's note may say the 2026-10-12 session and lap fixes ran "
        "live (one session per race, every timed lap stored), with the date and this run id; PS4 stays "
        "community_documented.",
        input_check=("centre", "left", "right", "pedals"),
    ),
    ValidationItem(
        id="game_selection",
        group="games",
        title="Game choice and the wrong-game banner",
        short="game choice",
        summary="Choose one game, drive another: a banner must say so, and go when you choose that game.",
        why="The game choice and its banner are new and have not been tried on the rig.",
        est_minutes=10,
        scope="window",
        steps=(
            Step("Setup › Game: choose F1 25 on PS5."),
            Step("Start another enabled game (for example GT7) and drive out."),
            Step("Check that a banner says the data is from another game."),
            Step("Choose that game: the banner must go."),
        ),
        prompt="Did the banner come and go as described?",
        radio_brief="Validation: game choice. Drive another game than the one chosen, then choose it.",
        rule_text="While this test is current Pitwall reads the chosen and the detected game every second. It "
        "passes when a mismatch came on and later went.",
        informs=(Informs("Game selection (the game-selection lane's status entry)"),),
        candidate="If you agree with this run, the game-selection entry may say the banner was checked live.",
        requires=("game_block",),
    ),
    ValidationItem(
        id="driver_switch",
        group="drivers",
        title="Switching drivers mid-session",
        short="driver switch",
        summary="Two drivers share one session: each driver's laps must end up under their own name.",
        why="Splitting a session on a driver switch is verified on generated data only.",
        est_minutes=15,
        scope="window",
        prerequisites=("Two driver profiles.",),
        steps=(
            Step("Driver A drives 2 timed laps."),
            Step("Switch to driver B from the driver button on Drive (pit lane or on track)."),
            Step("Driver B drives 2 laps."),
            Step("Switch back to A."),
        ),
        attestations=(Attest("switched_in_new_ui", "I switched from the new dashboard"),),
        prompt="Did each driver's laps end up under their own name?",
        radio_brief="Validation: driver switch. Two laps each, switching from the driver button on Drive.",
        rule_text="For each switch during this test Pitwall reads the sessions before and after it: laps after the "
        "switch must be stored under the new driver, and the previous driver's braking calls must not stay armed. "
        "It passes with one switch that has laps on both sides.",
        informs=(
            Informs("Driver profiles › split-on-switch: synthetic only"),
            Informs("Dashboard v2 › driver switching from the new UI"),
        ),
        candidate="If you agree with this run, the driver-profiles line may say split-on-switch was verified live.",
        requires=("two_drivers",),
    ),
)

BY_ID: dict[str, ValidationItem] = {it.id: it for it in CATALOG}

VOICE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("start validation", "Starts a run with every available test that is not optional"),
    ("next test", "Moves to the next test (the current one keeps its state)"),
    ("worked", "Marks the current test as worked"),
    ("didn't work", "Marks the current test as didn't work"),
    ("what's the test", "Says the current test and what it asks"),
    ("finish validation", "Finishes the run and saves the report"),
)


def availability(item: ValidationItem, a: Availability) -> tuple[bool, str | None]:
    """(available, reason). Only the item's own ``requires`` are checked."""
    for req in item.requires:
        if req == "hub" and not a.hub:
            return False, "Voice is off on this Mac."
        if req == "stt" and (not a.hub or a.stt in (None, "none")):
            why = (a.stt_reason or "").strip()
            if not why or "switched off" in why or why.startswith("no speech recognition"):
                return False, "Speech recognition is off on this Mac."
            return False, f"Speech recognition is not available on this Mac: {why}."
        if req == "kokoro" and a.tts != "kokoro":
            voice = a.tts if a.tts not in (None, "none") else "off"
            return False, f"The engineer voice on this Mac is {voice}, not the natural voice (Kokoro)."
        if req == "game_block" and not a.game_block:
            return False, "This Mac has no game choice yet."
        if req == "two_drivers" and a.drivers < 2:
            return False, "Add a second driver in Settings › Drivers first."
    return True, None


def default_items(a: Availability) -> list[str]:
    return [it.id for it in CATALOG if not it.optional and availability(it, a)[0]]


def item_json(item: ValidationItem, a: Availability) -> dict[str, Any]:
    ok, reason = availability(item, a)
    return {
        "id": item.id,
        "group": item.group,
        "title": item.title,
        "summary": item.summary,
        "why": item.why,
        "est_minutes": item.est_minutes,
        "optional": item.optional,
        "per_driver": item.per_driver,
        "scope": item.scope,
        "prerequisites": list(item.prerequisites),
        "steps": [{"text": s.text, "detail": s.detail} for s in item.steps],
        "attestations": [{"key": x.key, "text": x.text} for x in item.attestations],
        "prompt": item.prompt,
        "radio_brief": item.radio_brief,
        "input_check": None if item.input_check is None else list(item.input_check),
        "informs": [{"status_md": i.status_md, "capability_row": i.capability_row} for i in item.informs],
        "rule_text": item.rule_text,
        "available": ok,
        "unavailable_reason": reason,
    }


def catalog_json(a: Availability) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "groups": [{"id": g, "title": t} for g, t in GROUPS],
        "items": [item_json(it, a) for it in CATALOG],
        "voice_commands": [{"phrase": p, "does": d} for p, d in VOICE_COMMANDS],
    }


# The contract constants this catalogue's copy quotes (kept in one place so a test can compare them).
QUOTED = {
    "wake_min_s": R.WAKE_MIN_S,
    "gap_s": R.GAP_S,
    "cue_min_measured": R.CUE_MIN_MEASURED,
    "onset_window_m": R.ONSET_WINDOW_M,
}
