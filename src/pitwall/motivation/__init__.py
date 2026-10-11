"""Goals, streaks and summaries for every driver (lane motivation).

Everything here is deterministic and built from the driver's own stored driving: no LLM, no outside data.

* ``model`` - the row shapes (sessions, laps, goals, scopes) and the shared wording helpers.
* ``rules`` - pure rules: clean runs, steady-lap windows, scope matching, race outcomes, personal bests, weeks.
* ``goals`` - goal validation, titles, progress and the moment a goal is reached.
* ``suggest`` - goal suggestions from the driver's history (nothing invented).
* ``badges`` - badges and streaks, worked out in time order.
* ``recap`` - "Today's 3 things" for one session.
* ``digest`` / ``html`` - the weekly digest and its printable page.
* ``service`` - the database-backed service the API, the CLI and the worker share.
* ``worker`` - marks goals reached after live laps and at session end, off every hot path.
* ``facts`` - engineer facts (goals and progress); ``radio`` - the one short radio line for a reached goal.

Only goals are stored (``storage.repo``, table ``goals``). Badges, streaks, recaps and digests are derived when read,
so they can never drift from the laps. A goal is marked reached exactly once, by the worker
(``repo.mark_goal_achieved``); API reads never write.
"""
