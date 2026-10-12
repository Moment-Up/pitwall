"""Car health: tyre temperatures against the driver's own warm laps, brakes and engine, lock-ups and wheelspin per lap,
fuel for games that send only a tank level, and attack / defend corners against the cars directly ahead and behind.

One background worker (``carhealth.worker.CarHealthWorker``, the same mechanics as ``strategy.worker``) receives the
player's frames, laps, session info and events, F1 race timing and (in F1 races only) the field samples by lock-free
deque appends; the ingest thread never does more than that. Per session a ``CarHealthEngine`` (``engine``: pure,
deterministic, no I/O) feeds the monitors and publishes two small live blocks, ``car_health`` and ``racecraft``
(``view``), and proactive calls (``calls``) that go to the radio through the existing scheduler kinds (``radio``).
Nothing is persisted and nothing here calls an LLM.

Why there are no fixed temperature windows: no game publishes its tyre, brake or engine windows (EA's UDP spec, the
GT7 and Forza community docs), and the real-world figures describe real cars. Real F1 25 surface lap medians were under
75 C on 93 % of 500 wheel-laps; GT7 runs 37-196 C. So temperatures are judged only against this session's own warm
laps, and the only proactive temperature call is cold tyres after a pit stop or a safety car.

Evidence tiers (nothing here is live-validated):

* cold tyres after a stop: recorded (two F2 stops on PS5 with the carcass model on: 30 / 31.5 C at the exit against an
  89 / 86 C baseline, warm again on lap 3 / 4; two F1 stops with tyre blankets at Imola: no call). The safety-car
  restart arm is synthetic only (no real safety-car capture).
* surface-only sessions: the game sends constant inner temperatures (80 C medium and soft, 85 C hard) and fixed
  pressures, so the inner temperature is never used there (recorded).
* brake and engine temperatures: recorded values (engine 103-132 C, brake lap peaks 424-1030 C), no thresholds; shown
  and answered on request only.
* lock-ups (ABS off) and wheelspin per lap: recorded (F2 Bahrain on PS5 with ABS off: 50 lock-ups in 9 laps; wheelspin
  with traction control full, medium and off), with the technique module's slip thresholds.
* Forza fuel (laps of fuel from how fast the tank level falls): community-documented, synthetic tests only. GT7 fuel:
  not enabled (``thresholds.GT7_FUEL_ENABLED``): every owner capture read 100 / 100.
* attack / defend: recorded consistency (Austria over three sessions on two days; Imola's defend pick is "spread").
"""
