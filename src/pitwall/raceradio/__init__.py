"""Race radio: race control, the start and countdown, position and rivals, penalties and damage, said in speak windows.

Deterministic, no LLM, off the ingest path. ``core.session.SessionManager`` hands the player's ``CarFrame`` /
``LapCompletion``, ``SessionInfo``, ``GameEvent`` (no button events), and from F1 ``RaceTiming`` and ``Participants``
to the ``RaceRadioWorker`` with one lock-free deque append per item; the worker thread runs one ``RaceRadioEngine`` per
session for every game. The engine is clocked by the items' host receive time (``t_recv_ns``): the F1 session clock
reads 0 during the start lights and runs backwards after a flashback [measured], and a capture keeps receive times, so
replays and tests are reproducible.

Outputs:

1. a ``race`` block in every live snapshot (``RaceView``, ``model.race_view``; ``GET /api/race/live``), at most twice
   a second and at once after a call;
2. proactive calls: ``live.notify("race_call", RaceCall.to_dict())`` -> the radio hub's ``raceradio.radio.race_message``
   (the seated driver's group toggles and wording) -> the one radio policy (``voice.scheduler``: kind RACE has its own
   per-lap allowance; flags, penalties and damage are alerts);
3. the red flag as the first real urgent call: ``live.notify(voice.urgent.URGENT_NOTE, ...)``, spoken at once, past
   quiet mode, intensity and speak windows;
4. deterministic answers ("who's ahead?", penalties, damage, sector deltas, position in any game: ``answers``).

Groups (per-driver toggles, ``drivers.RadioCallPrefs``): flags, start, position, rivals, penalties, damage, name.

Names (``roster``): proactive calls say only official AI driver names from EA's driver table (``enums.DRIVERS``), else
a team or a race number. Online IDs - and the real players' IDs that F1 World AI cars carry [measured] - are personal:
never in a call, a fact, a log, the database or a snapshot.

Evidence (docs/status.md): recorded on the owner's PS5 F1 25 and GT7 captures for yellow, blue, position, lap 1, the
start lights, laps to go, the finish, warnings, time penalties, damage and punctures, retirements, fastest laps and GT7
position; synthetic only for the safety car and VSC, the red flag, drive-through / stop-go / DSQ / black flag /
reminders, minutes left, ERS/DRS faults and Forza. Nothing is live-validated yet. Every threshold marked ``[H]`` is a
rule of thumb to tune after the first live races (``scripts/race_radio_check.py`` gives the numbers).
"""
