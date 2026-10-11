"""Race strategy engineer: deterministic race strategy from the game's own timing, off the ingest path.

Inputs (``pitwall.model.telemetry``): the player's ``CarFrame`` / ``LapCompletion``, ``SessionInfo``, ``GameEvent``
and, from F1 only, ``RaceTiming`` (every car's position, gaps and pit state, <= 2 Hz) and ``TyreSetsInfo`` (the
player's tyre sets, the game's tyre model). ``core.session.SessionManager`` hands each item to the
``StrategyWorker`` with one lock-free deque append; the worker thread runs one ``StrategyEngine`` per session.

Outputs:

1. a ``strategy`` block in every live snapshot (``StrategyView``, ``view.py``; Drive > Car);
2. engineer facts and instant radio answers (``facts.py``, ``phrasing.py``);
3. rate-limited proactive radio calls (``calls.py`` -> ``live.notify("strategy_call")`` -> ``radio.py`` ->
   ``RadioScheduler`` speak windows);
4. per-lap records and pit stops in SQLite (schema v3), shown as Review > Strategy (``timeline.py``).

No LLM anywhere. Unknown stays unknown (``None``), every number carries a tier: ``measured`` (from this session's
data), ``game`` (the game's own estimate, e.g. TyreSets life and lap deltas) or ``heuristic`` (a rule of thumb,
marked ``[H]`` in the code). Evidence: decoding, gaps, fuel, tyre wear, TyreSets, forecast and AI pit-stop timing
are tested on recorded PS5 races; safety car / VSC, rain, the inters/wets crossover and the player's own stop are
synthetic only. Nothing here is live-validated yet.
"""
