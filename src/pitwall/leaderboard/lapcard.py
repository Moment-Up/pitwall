"""The lap card (format only, for a future opt-in online board; docs/leaderboard.md): one lap as a small, versioned
JSON object. Built locally by ``GET /api/leaderboard/lapcard/<lap_id>``; nothing is sent anywhere.

What a card carries: its board key (``keys``; None for a lap at an unknown track), the lap time and sectors, the day
it was driven (never the time of day), the game and its version, the assists, the evidence behind it (clean, valid,
track limits checked, not synthetic, not a replay, a profile owns it) and, only when asked for, the SHA-256 of the
session's capture file (the capture itself is never part of a card: it holds every raw packet, other players' names
included). The driver is
named only by ``online_name``, a separate display name that is empty until an online board exists and the owner sets
one: never the household profile name, never a PSN / Xbox / Steam id.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from pitwall.leaderboard import board as B
from pitwall.leaderboard import keys as K
from pitwall.storage.repo import is_replay_source

FORMAT = "pitwall.lapcard"
VERSION = 1
_HASH_CHUNK = 1 << 20


def _ms(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


def track_known(track_id: object) -> bool:
    """A track a board can key on (``repo._board_laps_cte``): an id that is not unknown, -1 or synthetic."""
    if not isinstance(track_id, str) or not track_id:
        return False
    return not (track_id.startswith(("unknown", "synthetic:")) or track_id.endswith(":-1"))


def evidence(lap: Mapping[str, Any], track_identified: bool) -> dict[str, Any]:
    """The checks a family board applies (``repo._board_laps_cte``), each as a flag; ``counts`` when the lap counts
    on the local board, with the ``reasons`` when it does not. ``valid`` is None when the game does not report lap
    validity (GT7, AC, Forza: ``track_limits_checked`` false). ``track_identified`` (a named track, not GT7's
    "Unidentified GT7 circuit") is information for an online board; a local board keys on the track id alone."""
    game = str(lap.get("game") or "")
    valid = lap.get("valid")
    replay = is_replay_source(str(lap.get("source") or ""))
    checks = {
        "timed": _ms(lap.get("lap_time_ms")) is not None,
        "clean": bool(lap.get("clean")),
        "valid": valid if isinstance(valid, bool) else None,
        "track_limits_checked": B.track_limits_checked(game),
        "synthetic": bool(lap.get("synthetic")),
        "replay": replay,
        "owned": bool(lap.get("owned")),
        "track_known": track_known(lap.get("track_id")),
        "track_identified": track_identified,
    }
    reasons = []
    if not checks["timed"]:
        reasons.append("the lap has no time")
    if not checks["clean"]:
        reasons.append("not a clean lap (invalid, incomplete, flashback, pit or start lap)")
    if checks["valid"] is False:
        reasons.append("the game marked the lap invalid")
    if checks["synthetic"]:
        reasons.append("synthetic data, not a game")
    if replay:
        reasons.append("a replay of a recording, not driving")
    if not checks["owned"]:
        reasons.append("no driver profile owns the session")
    if not checks["track_known"]:
        reasons.append("the track is not known")
    return {**checks, "counts": not reasons, "reasons": reasons}


def capture_sha256(path: object) -> str | None:
    """SHA-256 of a capture file, or None when there is no readable file (moved, deleted, never recorded)."""
    if not isinstance(path, str) or not path:
        return None
    p = Path(path)
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            while chunk := f.read(_HASH_CHUNK):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def lap_card(
    lap: Mapping[str, Any],
    key: K.BoardKey,
    *,
    pitwall_version: str,
    track_identified: bool,
    capture_hash: str | None = None,
) -> dict[str, Any]:
    """The card of one lap (``repo.board_lap`` row and its board key)."""
    set_unix = lap.get("set_unix")
    day = datetime.fromtimestamp(float(set_unix)).date().isoformat() if isinstance(set_unix, int | float) else None
    platform = lap.get("platform")
    version = lap.get("game_version")
    packet_format = lap.get("packet_format")
    labels = B.labels(key, lap)
    return {
        "format": FORMAT,
        "version": VERSION,
        "board": {"key": key.encode(), **key.fields()} if track_known(lap.get("track_id")) else None,
        "labels": {k: labels[k] for k in ("game", "track", "layout", "car", "category", "conditions", "assists_text")},
        "lap_ms": _ms(lap.get("lap_time_ms")),
        "sectors_ms": [_ms(lap.get(f"s{i}_ms")) for i in (1, 2, 3)],
        "date": day,
        "game": {
            "id": key.game,
            "version": version if isinstance(version, str) else None,
            "platform": platform if isinstance(platform, str) and platform not in ("", "unknown") else None,
            "packet_format": packet_format if isinstance(packet_format, int) else None,
        },
        "pitwall_version": pitwall_version,
        "assists": dict(key.assists) if key.assists else None,
        "evidence": evidence(lap, track_identified),
        "capture_sha256": capture_hash,
        "online_name": "",
    }
