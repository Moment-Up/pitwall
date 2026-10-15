"""Family leaderboard (local): boards per exact key, the record index, record history, lap cards.

* ``keys`` - the board key (game + track + layout + car + session category + conditions + assist class), its
  string form and its words (pure).
* ``board`` - boards, the record index, record history and record takes from the repo rows (pure).
* ``service`` - the database side, shared by the API (``api/routes_leaderboard.py``), the motivation badges and
  worker, and the engineer facts.
* ``lapcard`` - the versioned lap card format (docs/leaderboard.md); built locally, never sent anywhere.
* ``facts`` - the engineer's family record fact.

Nothing here goes online: no network calls, no uploads. Household driver names stay on this machine.
"""
