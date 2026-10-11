"""Evidence report of a validation run: ``ValidationReport`` JSON (contract) and a Markdown rendering (pure).

The report never changes a capability status: it lists *candidates* for the maintainer as text, with a fixed
disclaimer. Units are in column headers; unknown values are ``null`` in JSON and "-" in Markdown, which uses the
minus sign U+2212. Transcripts are the driver's own words and are included unless ``redact`` is set.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from pitwall.validate.catalog import BY_ID, ValidationItem
from pitwall.validate.model import FORMAT, ItemState, Run, dump

DISCLAIMER = (
    "This report never changes capability statuses. Review it, then update src/pitwall/capabilities.py and "
    "docs/status.md by hand."
)
REDACTED = "[transcript removed]"
MINUS = "\u2212"

RESULT_WORDS = {
    "pass": "pass",
    "fail": "fail",
    "needs_review": "to check",
    "not_run": "not run",
    "skipped": "skipped",
}
AUTO_WORDS = {
    "pass": "pass",
    "fail": "fail",
    "inconclusive": "inconclusive",
    "no_evidence": "no evidence",
    "not_live": "not live",
    "unavailable": "unavailable",
    "driver_only": "your call",
}
CLS_WORDS = {
    "on_time": "on time",
    "late": "late",
    "early": "early",
    "unmeasured": "not measured",
    "dropped": "dropped",
    "clean": "clean",
    "tight": "tight",
    "overlap": "overlap",
    "off_track": "off track",
}
OS_NAMES = {"darwin": "macOS", "win32": "Windows", "linux": "Linux"}

Table = dict[str, Any]
Row = list[str | int | float | None]


def _table(title: str, columns: Sequence[str], rows: Sequence[Row]) -> Table:
    return {"title": title, "columns": list(columns), "rows": [list(r) for r in rows]}


def _lap_time(ms: int | None) -> str | None:
    if ms is None:
        return None
    m, s = divmod(ms / 1000.0, 60)
    return f"{int(m)}:{s:06.3f}"


def _when(t: float | None) -> str | None:
    if t is None:
        return None
    return time.strftime("%H:%M:%S", time.localtime(t))


# ------------------------------------------------------------------------------------------------ evidence tables
def evidence_tables(run: Run, item_id: str, redact: bool = False) -> list[Table]:
    ev = run.evidence
    if item_id == "cues_timing":
        own = [c for c in ev.cues if c.kind == "brake" and not c.heads_up]
        heads = [c for c in ev.cues if c.heads_up]
        markers = [c for c in ev.cues if c.kind == "marker" and not c.heads_up]
        out = [
            _table(
                "Calls",
                [
                    "Lap",
                    "Corner",
                    "Word vs point (m)",
                    "Driver braked vs point (m)",
                    "Word to brake (s)",
                    "Outcome",
                    "Tier",
                ],
                [
                    [
                        c.lap,
                        c.corner,
                        c.heard_vs_point_m,
                        c.onset_vs_point_m,
                        c.onset_vs_word_s,
                        c.drop_reason if c.cls == "dropped" else CLS_WORDS.get(c.cls, c.cls),
                        c.tier,
                    ]
                    for c in own
                ],
            )
        ]
        if markers:
            out.append(
                _table(
                    "Corner markers",
                    ["Lap", "Corner", "Target (m)", "Word vs aim (m)", "Outcome"],
                    [[c.lap, c.corner, round(c.target_m, 1), c.error_m, CLS_WORDS.get(c.cls, c.cls)] for c in markers],
                )
            )
        if heads:
            out.append(
                _table(
                    "AI-field heads-ups (no reference lap)",
                    ["Lap", "Zone", "Target (m)", "Driver braked vs point (m)", "Outcome", "Tier"],
                    [[c.lap, c.corner, round(c.target_m, 1), c.onset_vs_point_m, c.outcome, c.tier] for c in heads],
                )
            )
        return out
    if item_id == "radio_ptt":
        return [
            _table(
                "Questions",
                ["Time", "Source", "Transcript", "Answered by", "To playback (s)", "Heard right", "Tier"],
                [
                    [
                        _when(p.t_unix),
                        p.source,
                        (REDACTED if redact and p.transcript else p.transcript) or "(not heard)",
                        p.answer_source,
                        None if p.to_playback_ms is None else round(p.to_playback_ms / 1000, 2),
                        None if p.heard_right is None else ("yes" if p.heard_right else "no"),
                        p.tier,
                    ]
                    for p in ev.ptt
                ],
            )
        ]
    if item_id == "radio_speak_windows":
        return [
            _table(
                "Messages",
                ["Lap", "Kind", "Started at (m)", "Max brake", "Max steering", "Gap to braking (s)", "Result", "Tier"],
                [
                    [
                        (p.start_frame or {}).get("lap", p.lap),
                        p.kind,
                        (p.start_frame or {}).get("lap_distance_m"),
                        p.max_brake,
                        p.max_abs_steering,
                        p.gap_to_brake_s,
                        CLS_WORDS.get(p.cls, p.cls) + (" (cut)" if p.cut else ""),
                        p.tier,
                    ]
                    for p in ev.proactive
                ],
            )
        ]
    if item_id == "radio_kokoro":
        return [
            _table(
                "Messages",
                ["Time", "Kind", "Voice", "Synthesis (ms)", "Fallback reason", "Heard", "Tier"],
                [
                    [
                        _when(s.t_unix),
                        s.kind,
                        s.engine,
                        None if s.synth_ms is None else round(s.synth_ms),
                        s.fallback_reason,
                        "yes" if s.started else "no",
                        s.tier,
                    ]
                    for s in ev.synth
                ],
            )
        ]
    if item_id in ("ipad_home_screen", "ipad_glance", "ipad_endurance"):
        from pitwall.validate.evidence import client_summary

        now = run.ended_unix or time.time()
        rows: list[Row] = []
        for c in run.client_states:
            s = client_summary(c, now)
            fps = s["fps"] or {}
            rows.append(
                [
                    s["device"],
                    "Home Screen" if s["standalone"] else "browser",
                    s["origin_kind"],
                    s["safari_version"],
                    s["wake_on_streak_s"],
                    s["hidden_transitions"],
                    s["gaps"],
                    s["reloads"],
                    fps.get("median"),
                    fps.get("windows"),
                ]
            )
        return [
            _table(
                "Devices",
                [
                    "Device",
                    "Opened from",
                    "Origin",
                    "Safari",
                    "Longest streak (s)",
                    "Hidden",
                    "Gaps",
                    "Reloads",
                    "Median fps",
                    "Fps windows",
                ],
                rows,
            )
        ]
    if item_id == "ipad_one_message":
        picked = {lap.lap_id: lap.picked_ids for lap in ev.laps}
        return [
            _table(
                "Coaching points spoken",
                ["Lap", "Point", "On the card", "Tier"],
                [
                    [
                        p.lap,
                        p.observation_id,
                        None if p.lap_id not in picked else ("yes" if p.observation_id in picked[p.lap_id] else "no"),
                        p.tier,
                    ]
                    for p in ev.proactive
                    if p.kind == "coaching" and p.started
                ],
            )
        ]
    if item_id in ("ac_ps5", "gt7_ps5"):
        game = "ac" if item_id == "ac_ps5" else "gt7"
        sessions = [s for s in ev.sessions if s.game == game]
        out = [
            _table(
                "Sessions",
                ["Started", "Track", "Laps timed", "Clean", "Best", "Variant", "Coaching points", "Tier"],
                [
                    [
                        _when(s.started_unix),
                        s.track_name or s.track_id or ("streaming, not driving" if not s.laps else None),
                        sum(1 for lap in s.laps if lap.get("lap_time_ms") is not None),
                        sum(1 for lap in s.laps if lap.get("clean")),
                        _lap_time(
                            min(
                                (lap["lap_time_ms"] for lap in s.laps if lap.get("lap_time_ms") is not None),
                                default=None,
                            )
                        ),
                        s.extra.get("packet_variant"),
                        s.n_observations,
                        s.tier,
                    ]
                    for s in sessions
                ],
            ),
            _table(
                "Laps",
                ["Started", "Lap", "Time", "Clean", "Flags"],
                [
                    [
                        _when(s.started_unix),
                        lap.get("lap_number"),
                        _lap_time(lap.get("lap_time_ms")),
                        "yes" if lap.get("clean") else "no",
                        ", ".join(lap.get("flags") or []) or None,
                    ]
                    for s in sessions
                    for lap in s.laps
                ],
            ),
        ]
        phases = [p for p in ev.input_phases if p.item_id == item_id]
        if phases:
            out.append(
                _table(
                    "Input check",
                    [
                        "Phase",
                        "Samples",
                        "Steer mean",
                        "Steer min",
                        "Steer max",
                        "Throttle max",
                        "Brake max",
                        "Gear min",
                        "Raw steer range",
                        "Rotation (°)",
                    ],
                    [
                        [
                            p.phase,
                            p.samples,
                            p.steer_mean,
                            p.steer_min,
                            p.steer_max,
                            p.throttle_max,
                            p.brake_max,
                            p.gear_min,
                            None
                            if not p.steer_raw_range
                            else f"{p.steer_raw_range[0]:.1f} .. {p.steer_raw_range[1]:.1f}",
                            p.rotation_deg,
                        ]
                        for p in phases
                    ],
                )
            )
        return out
    if item_id == "game_selection":
        return [
            _table(
                "Game choice",
                ["Time", "Chosen", "Detected", "Banner", "Tier"],
                [
                    [_when(t.t_unix), t.selected_id, t.detected_id, "on" if t.mismatch else "off", t.tier]
                    for t in ev.game
                ],
            )
        ]
    if item_id == "driver_switch":
        return [
            _table(
                "Switches",
                [
                    "Time",
                    "From",
                    "To",
                    "Laps after it on the old session",
                    "Laps after",
                    "Same game session",
                    "Braking calls after",
                    "OK",
                ],
                [
                    [
                        _when(s.t_unix),
                        None if s.from_driver_id is None else f"Driver #{s.from_driver_id}",
                        None if s.to_driver_id is None else f"Driver #{s.to_driver_id}",
                        s.laps_before_after_switch,
                        s.laps_after,
                        None if s.same_game_uid is None else ("yes" if s.same_game_uid else "no"),
                        s.cue_reason_after or ("armed" if s.cue_ref_lap_id is not None else None),
                        None if s.ok is None else ("yes" if s.ok else "no"),
                    ]
                    for s in ev.switches
                ],
            )
        ]
    return []


# ------------------------------------------------------------------------------------------------ report JSON
def run_summary(run: Run) -> dict[str, Any]:
    counts = {k: 0 for k in RESULT_WORDS}
    for it in run.items:
        counts[it.result] = counts.get(it.result, 0) + 1
    tc = run.evidence.tier_counts()
    return {
        "id": run.id,
        "label": run.label,
        "status": run.status,
        "started_unix": run.started_unix,
        "ended_unix": run.ended_unix,
        "current_item": run.current_item,
        "counts": counts,
        "tiers": [t for t, n in tc.items() if n > 0],
    }


def _informs(item: ValidationItem | None) -> list[dict[str, Any]]:
    if item is None:
        return []
    return [{"status_md": i.status_md, "capability_row": i.capability_row} for i in item.informs]


def build_report(run: Run, now: float, redact: bool = False) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for st in run.items:
        cat = BY_ID.get(st.id)
        marks = [dump(m) for m in st.marks]  # notes are typed about the test, not transcripts: kept when redacting
        items.append(
            {
                "id": st.id,
                "title": cat.title if cat else st.id,
                "group": cat.group if cat else "dashboard",
                "result": st.result,
                "marks": marks,
                "auto": dump(st.auto),
                "informs": _informs(cat),
                "evidence_tables": evidence_tables(run, st.id, redact),
            }
        )
        if cat is not None and cat.informs:
            # one candidate per test (its suggestion once), naming every status line it informs
            rows = [i.capability_row for i in cat.informs if i.capability_row]
            candidates.append(
                {
                    "item_id": st.id,
                    "status_md": "; ".join(i.status_md for i in cat.informs),
                    "capability_row": "; ".join(rows) if rows else None,
                    "suggestion": cat.candidate,
                    "met": st.result == "pass",
                }
            )
    return {
        "format": FORMAT,
        "generated_unix": now,
        "in_progress": run.status == "active",
        "run": {**run_summary(run), "server": dump(run.server), "notes": run.notes},
        "tiers": run.evidence.tier_counts(),
        "items": items,
        "candidates": candidates,
        "disclaimer": DISCLAIMER,
    }


# ------------------------------------------------------------------------------------------------ Markdown
def md_value(v: Any) -> str:
    if v is None or v == "":
        return "-"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return str(v).replace("-", MINUS) if v < 0 else str(v)
    if isinstance(v, float):
        s = f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 10 else f"{v:.1f}"
        return s.replace("-", MINUS)
    return str(v).replace("|", "\\|").replace("\n", " ")


def _date(t: float) -> str:
    lt = time.localtime(t)
    return f"{lt.tm_mday} {time.strftime('%b %Y %H:%M', lt)}"


def _driver_cell(st: ItemState, per_driver: bool) -> str:
    if not st.marks:
        return "-"
    words = {"worked": "worked", "didnt": "didn't work"}
    if per_driver:
        return ", ".join(
            f"{'Driver #' + str(m.driver_id) if m.driver_id is not None else 'Driver'} {words[m.verdict]}"
            for m in st.marks
        )
    return words[st.marks[-1].verdict]


def _md_table(t: Table) -> list[str]:
    lines = [f"**{t['title']}**", "", "| " + " | ".join(t["columns"]) + " |", "|" + "---|" * len(t["columns"])]
    if not t["rows"]:
        return [*lines, "| " + " | ".join(["-"] * len(t["columns"])) + " |", ""]
    for r in t["rows"]:
        lines.append("| " + " | ".join(md_value(v) for v in r) + " |")
    return [*lines, ""]


def render_markdown(report: dict[str, Any], run: Run) -> str:
    r = report["run"]
    server = r["server"]
    engines = [str(e).capitalize() for e in (server.get("tts"), server.get("stt")) if e and e != "none"]
    voice = (
        (f"voice on ({', '.join(engines)})" if engines else "voice on (text only)")
        if server.get("voice_enabled")
        else "voice off"
    )
    commit = f" ({server['git_commit']})" if server.get("git_commit") else ""
    when = (
        f"Finished {_date(r['ended_unix'])}"
        if r.get("ended_unix") and r["status"] != "active"
        else f"Started {_date(r['started_unix'])} (in progress)"
    )
    if r["status"] == "aborted":
        when = f"Aborted {_date(r['ended_unix'] or r['started_unix'])}"
    tiers = report["tiers"]
    other = sum(n for t, n in tiers.items() if t != "live")
    os_name = OS_NAMES.get(server.get("os", ""), server.get("os"))
    lines = [
        f"# Pitwall validation run {r['id']}",
        "",
        f"{when} · pitwall {server.get('pitwall_version')}{commit} · {os_name} · {voice} · "
        f"LLM {'on' if server.get('llm_enabled') else 'off'}",
        "",
        f"Evidence: {tiers.get('live', 0)} live records · {other} from replays, synthetic, loopback or unknown streams",
        "",
    ]
    if r.get("label"):
        lines += [f"Label: {md_value(r['label'])}", ""]
    lines += ["| Test | Result | Driver | Pitwall saw | Key evidence |", "|---|---|---|---|---|"]
    by_id = {it.id: it for it in run.items}
    for it in report["items"]:
        st = by_id[it["id"]]
        cat = BY_ID.get(it["id"])
        key = "; ".join(it["auto"]["reasons"][:2]) or "-"
        auto_v = it["auto"]["verdict"]
        lines.append(
            f"| {md_value(it['title'])} | {RESULT_WORDS.get(it['result'], it['result'])} | "
            f"{_driver_cell(st, bool(cat and cat.per_driver))} | {AUTO_WORDS.get(auto_v, auto_v)} | "
            f"{md_value(key)} |"
        )
    lines.append("")
    for it in report["items"]:
        st = by_id[it["id"]]
        cat = BY_ID.get(it["id"])
        lines += [f"## {it['title']}", ""]
        if cat is not None:
            steps = " ".join(f"{i}. {s.text}" for i, s in enumerate(cat.steps, 1))
            lines += [f"Steps the driver followed: {steps}", ""]
        if st.skip_reason is not None or it["result"] == "skipped":
            lines += [f"Skipped: {st.skip_reason or '-'}", ""]
        auto = it["auto"]
        lines.append(
            f"Pitwall saw: **{AUTO_WORDS.get(auto['verdict'], auto['verdict'])}**"
            + (f" (evidence tier: {auto['tier']})" if auto.get("tier") else "")
        )
        lines.append("")
        for reason in auto["reasons"]:
            lines.append(f"- {md_value(reason)}")
        if auto["reasons"]:
            lines.append("")
        if auto["checks"]:
            lines.append("Checks:")
            for c in auto["checks"]:
                tag = {"met": "[met]", "not_met": "[not met]", "unknown": "[-]"}[c["status"]]
                extra = f" (target {c['target']}{', heuristic' if c['heuristic'] else ''})" if c.get("target") else ""
                lines.append(f"- {tag} {c['label']}: {md_value(c.get('value'))}{extra}")
            lines.append("")
        for m in st.marks:
            who = f"Driver #{m.driver_id}" if m.driver_id is not None else "Driver"
            said = "worked" if m.verdict == "worked" else "didn't work"
            att = ", ".join(f"{k}: {'yes' if v else 'no'}" for k, v in m.attestations.items())
            ext = ", ".join(f"{k}: {v}" for k, v in m.extra.items())
            details = "; ".join(x for x in (att, ext) if x)
            lines.append(f"- {who} said {said} ({m.source}){': ' + details if details else ''}")
            if m.notes:
                lines.append(f"  - Note: {md_value(m.notes)}")
        if st.marks:
            lines.append("")
        for t in it["evidence_tables"]:
            lines += _md_table(t)
    lines += ["## What this run can support (for the maintainer)", ""]
    for c in report["candidates"]:
        mark = "supported by this run" if c["met"] else "not supported yet"
        row = f" Capability row: {c['capability_row']}." if c.get("capability_row") else ""
        lines.append(f"- **{c['status_md']}** ({mark}).{row} {c['suggestion']}")
    lines += ["", f"> {report['disclaimer']}", ""]
    return "\n".join(lines)
