"""ACC circuit lengths by Static ``track`` string - the fallback that turns ``normalizedCarPosition`` into metres.

Why a table: Kunos' "ACC Shared Memory v1.8.12" marks ``SPageFileStatic.trackSplineLength`` as **not used in ACC**,
and no other field of the three pages carries a track length. Ed (Pitwall tester) confirmed it on his PC (Brands
Hatch, 2026-10-13): no float anywhere in a real Static page held a plausible track length. He wrote this table for
his ACC adapter; it is kept as he gave it (keys are ACC's own snake_case track names, inferred from the game's
circuit roster), with his provenance notes.

Confidence varies per entry. Ed checked Spa, Monza and Brands Hatch against public sources on 2026-10-13; every other
length is from general knowledge of the circuit and has **not** been individually verified. A length error scales
every lap distance of that track uniformly (the lap still runs 0 .. length, so laps of one track stay comparable),
but metres shown to the driver are off by the same fraction. The adapter uses ``trackSplineLength`` instead whenever
the game does fill it with a value within ``adapter.TRACK_LENGTH_TOLERANCE`` of this table (see ``adapter.py``), and a
recorded lap should confirm or correct each entry. A track not listed here (a DLC circuit, a renamed one) has no
length: ``lap_distance_m`` stays ``None`` - unknown stays unknown.
"""

from __future__ import annotations

# metres. Checked by Ed 2026-10-13: spa, monza, brands_hatch. Everything else: approximate, unverified.
TRACK_LENGTH_M: dict[str, float] = {
    "spa": 7004.0,  # checked
    "monza": 5793.0,  # checked
    "brands_hatch": 3916.0,  # checked (Wikipedia, GP layout in use since 2003)
    "silverstone": 5891.0,
    "nurburgring": 5148.0,  # GP layout; ACC's Nordschleife/24h combination is a separate, much longer configuration
    "misano": 4226.0,
    "zandvoort": 4259.0,
    "paul_ricard": 5842.0,
    "hungaroring": 4381.0,
    "barcelona": 4655.0,
    "zolder": 4011.0,
    "kyalami": 4522.0,
    "mount_panorama": 6213.0,
    "laguna_seca": 3602.0,
    "suzuka": 5807.0,
    "cota": 5513.0,
    "imola": 4909.0,
    "donington": 4020.0,
    "oulton_park": 4307.0,
    "snetterton": 4779.0,
    "oschersleben": 3696.0,
    "red_bull_ring": 4318.0,
    "watkins_glen": 5552.0,
    "indianapolis": 3934.0,
    "valencia": 4005.0,
}
CHECKED: frozenset[str] = frozenset({"spa", "monza", "brands_hatch"})


def track_length_m(track_name: str | None) -> float | None:
    """Table length for an ACC ``track`` string (case-insensitive), or ``None`` if the track is not listed."""
    if not track_name:
        return None
    return TRACK_LENGTH_M.get(track_name.strip().lower())
