"""Command-line interface: ``uv run pitwall --help``."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import socket
import sys
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from pitwall.compat import recv_clock_ns, this_machine
from pitwall.config import Settings, get_settings

app = typer.Typer(add_completion=False, help="Pitwall - AI sim racing coach & race engineer", no_args_is_help=True)


def _windows_safe_output() -> None:
    """Windows: stdout/stderr redirected to a file or pipe use the ANSI code page (cp1252), which cannot encode
    some characters in reports and names; replace those instead of crashing the command."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def _logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # no packets are sent for UDP connect
            return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="HTTP bind address")] = None,
    port: Annotated[int | None, typer.Option(help="HTTP port")] = None,
    udp: Annotated[bool, typer.Option(help="Listen for live game telemetry")] = True,
    verbose: bool = False,
) -> None:
    """Run the dashboard/API server and the live telemetry listener."""
    import uvicorn

    from pitwall.api.app import create_app

    _logging(verbose)
    s = get_settings()
    if host:
        s.http_host = host
    if port:
        s.http_port = port
    token = s.resolve_access_token()
    typer.echo(f"Dashboard ({this_machine()}):   http://127.0.0.1:{s.http_port}/")
    typer.echo(f"Dashboard (LAN device): http://{_lan_ip()}:{s.http_port}/?token={token}")
    if udp:
        typer.echo(f"Game telemetry:         UDP {_lan_ip()}:{s.f1_udp_port}  (set this IP/port in the game)")
    # proxy_headers=False: uvicorn would otherwise rewrite request.client from X-Forwarded-For for loopback
    # peers, hiding that a request came through Tailscale Serve. The access policy needs the true TCP peer.
    uvicorn.run(
        create_app(s, start_udp=udp), host=s.http_host, port=s.http_port, log_level="warning", proxy_headers=False
    )


@app.command()
def simulate(
    scenario: str = "coaching-demo",
    packet_format: Annotated[int, typer.Option("--format", help="UDP format 2025 or 2026")] = 2025,
    out: Path | None = None,
) -> None:
    """Write a SYNTHETIC F1 capture with known injected driving errors (for development without a game)."""
    from pitwall.sim.scenarios import SCENARIOS, write_synthetic_capture

    s = get_settings()
    sc = SCENARIOS[scenario]()
    sc.packet_format = packet_format
    path = out or s.capture_dir / f"synthetic-{scenario}-{packet_format}.pwcap"
    t0 = time.perf_counter()
    truth = write_synthetic_capture(path, sc, scenario)
    typer.echo(f"wrote {path} ({path.stat().st_size // 1024} KB, {time.perf_counter() - t0:.1f}s) - SYNTHETIC data")
    typer.echo("ground-truth lap times (ms): " + json.dumps(truth.lap_times_ms))


@app.command()
def replay(
    path: Path,
    speed: Annotated[float, typer.Option(help="1.0 = real time; 0 = as fast as possible")] = 0.0,
    verbose: bool = False,
) -> None:
    """Replay a capture through the full pipeline into the database (headless)."""
    from pitwall.core.runtime import Runtime
    from pitwall.storage import repo

    _logging(verbose)
    rt = Runtime(get_settings())
    try:
        r = rt.start_replay(path, speed=speed or None)
        r.done.wait()
        rt.worker.join()
        rt.writer.flush()
        with rt.db.read() as c:
            sid = repo.latest_session_id(c)
            laps = repo.list_laps(c, sid) if sid else []
            obs = repo.list_observations(c, sid) if sid else []
        typer.echo(f"replayed {r.sent} packets -> session {sid}: {len(laps)} laps, {len(obs)} observations")
        for o in reversed(obs):
            typer.echo(f"  lap {o['lap_number']}: {o['text']}")
    finally:
        rt.close()


@app.command()
def send(
    path: Path,
    host: str = "127.0.0.1",
    port: int = 20777,
    speed: Annotated[float, typer.Option(help="Playback speed; 1.0 = original timing")] = 1.0,
) -> None:
    """Stream a capture over real UDP (emulates a console sending telemetry; exercises the live path)."""
    from pitwall.ingest.capture import CaptureReader

    reader = CaptureReader(path)
    if reader.meta.synthetic:
        typer.echo("note: this capture is SYNTHETIC")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    t0_cap: int | None = None
    t0 = recv_clock_ns()  # same clock as the capture's timestamps (QueryPerformanceCounter on Windows)
    n = 0
    for pkt in reader:
        if t0_cap is None:
            t0_cap = pkt.t_recv_ns
        due = t0 + (pkt.t_recv_ns - t0_cap) / speed
        wait = (due - recv_clock_ns()) / 1e9
        if wait > 0.001:
            time.sleep(wait)
        sock.sendto(pkt.data, (host, port))
        n += 1
    typer.echo(f"sent {n} packets to udp://{host}:{port}")


@app.command()
def sessions(limit: int = 20) -> None:
    """List recorded sessions."""
    from pitwall.storage import repo
    from pitwall.storage.db import Database

    db = Database(get_settings().db_path)
    with db.read() as c:
        for s in repo.list_sessions(c, limit):
            syn = " SYNTHETIC" if s["synthetic"] else ""
            best = f"{s['best_clean_ms'] / 1000:.3f}s" if s["best_clean_ms"] else "-"
            typer.echo(
                f"{s['id']}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(s['started_unix']))}  "
                f"{s['game']:8} {s['track_name'] or '?':28} laps={s['lap_count']:3} best={best}{syn}"
            )


@app.command()
def report(session_id: Annotated[str | None, typer.Argument()] = None) -> None:
    """Print a Markdown session report (latest session by default)."""
    from pitwall.core.report import build_report
    from pitwall.core.session_analysis import SessionAnalyzer
    from pitwall.storage import repo
    from pitwall.storage.db import Database

    db = Database(get_settings().db_path)
    with db.read() as c:
        sid = session_id or repo.latest_session_id(c)
    if sid is None:
        typer.echo("no sessions recorded", err=True)
        raise typer.Exit(1)
    sa = SessionAnalyzer(db).analyse(sid)
    if sa is None:
        typer.echo(f"session {sid} not found", err=True)
        raise typer.Exit(1)
    typer.echo(build_report(sa)["markdown"])


@app.command()
def ask(
    question: str,
    session_id: Annotated[str | None, typer.Option("--session")] = None,
    llm: Annotated[bool, typer.Option(help="Use the local LLM (otherwise deterministic answer)")] = True,
    show_facts: bool = False,
) -> None:
    """Ask the AI race engineer a question about a recorded session."""
    from pitwall.ai.engineer import RaceEngineer
    from pitwall.ai.facts import build_fact_sheet
    from pitwall.ai.providers import OpenAICompatibleProvider
    from pitwall.core.session_analysis import SessionAnalyzer
    from pitwall.storage import repo
    from pitwall.storage.db import Database

    s = get_settings()
    db = Database(s.db_path)
    with db.read() as c:
        sid = session_id or repo.latest_session_id(c)
    if sid is None:
        typer.echo("no sessions recorded", err=True)
        raise typer.Exit(1)
    sa = SessionAnalyzer(db).analyse(sid)
    assert sa is not None
    sheet = build_fact_sheet(sa)
    from pitwall.motivation.facts import add_motivation_facts  # lane motivation

    add_motivation_facts(sheet, db, sa)

    use_llm = llm and s.llm_enabled  # PITWALL_LLM_ENABLED=false: deterministic answers, no request to the endpoint
    if llm and not s.llm_enabled:
        typer.echo("[LLM disabled (llm_enabled = false): deterministic answer]", err=True)

    async def run() -> None:
        provider = (
            OpenAICompatibleProvider(s.llm_base_url, s.llm_model, s.llm_api_key, timeout_s=s.llm_timeout_s)
            if use_llm
            else None
        )
        try:
            engineer = RaceEngineer(provider, s.llm_max_tokens, s.llm_temperature)
            ans = await engineer.answer(question, sheet, use_llm=use_llm)
        finally:
            if provider is not None:
                await provider.aclose()
        typer.echo(f"\n{ans.text}\n")
        src = "deterministic fallback" if ans.fallback else f"LLM {ans.model}"
        typer.echo(
            f"[intent={ans.intent} corner={ans.corner} source={src} grounded={ans.grounded} "
            f"latency={ans.latency_ms} ms attempts={ans.llm_attempts}]"
        )
        if ans.grounding_issues:
            typer.echo(f"[grounding issues: {ans.grounding_issues}]")
        if show_facts:
            for f in ans.facts:
                typer.echo(f"  [{f['id']}] {f['text']}")

    asyncio.run(run())


# --- feat/technique ----------------------------------------------------------------------------------------------
@app.command()
def technique(
    session_id: Annotated[str | None, typer.Argument(help="Session id, or 'latest' (default)")] = None,
    ref: Annotated[int | None, typer.Option("--ref", help="Reference lap id (default: the session's own)")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the API's TechniqueSession JSON")] = False,
    car_format: Annotated[
        str | None, typer.Option("--car-format", help="f1_2025 or f1_2026 when the game's generic car is ambiguous")
    ] = None,
) -> None:
    """Racing line, brake/throttle technique, handling balance and setup suggestions for a recorded session."""
    from pitwall.carsetup.recommend import SetupRequestError, parse_car_format
    from pitwall.core.session_analysis import SessionAnalyzer
    from pitwall.storage import repo
    from pitwall.storage.db import Database
    from pitwall.technique.session import NoTrackModel, TechniqueAnalyzer, TechniqueNotFound

    s = get_settings()
    db = Database(s.db_path)
    with db.read() as c:
        sid = repo.latest_session_id(c) if session_id in (None, "latest") else session_id
    if sid is None:
        typer.echo("no sessions recorded", err=True)
        raise typer.Exit(1)
    ta = TechniqueAnalyzer(db, SessionAnalyzer(db), lambda: _stored_rig(s.data_dir / "settings.json"))
    try:
        st = ta.analyse(sid, ref)
    except TechniqueNotFound as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    except NoTrackModel as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    try:
        fmt = parse_car_format(car_format) if car_format else None
    except SetupRequestError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from e
    setup = ta.setup(st, fmt)
    if as_json:
        typer.echo(json.dumps(st.to_dict(setup), indent=1))
        return
    for line in technique_report(st, setup):
        typer.echo(line)


def _stored_rig(path: Path) -> Any:
    """The rig profile from settings.json, read-only (never moves or rewrites the file); None when unreadable."""
    from pitwall.rig.recommend import RigProfile

    if not path.exists():
        return RigProfile.from_stored({})  # never saved: the defaults, as the server uses them
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rig = data.get("rig") if isinstance(data, dict) else None
    return RigProfile.from_stored(rig if isinstance(rig, dict) else {})


def technique_report(st: Any, setup: Any) -> list[str]:
    from pitwall.technique.session import SessionTechnique
    from pitwall.technique.setup_map import SetupEngineer

    assert isinstance(st, SessionTechnique)
    out = [
        f"Session {st.session_id} ({st.session.get('track_name') or '?'})"
        + (" SYNTHETIC" if st.session.get("synthetic") else "")
        + (f" - reference lap {st.ref_lap_number}" if st.ref_lap_number is not None else " - no reference lap"),
        f"Pedals: {st.pedals.note}",
        *[f"Assists: {n}" for n in st.assists.notes],
    ]
    for key, av in st.available.items():
        if not av.ok:
            out.append(f"{key}: not available - {av.reason}")
    for c in st.corners:
        out.append(f"{c.long_name} ({c.direction or '?'}, {c.speed_class or '?'}, apex {c.apex_m:.0f} m)")
        if c.line is not None:
            pts = [
                f"{k} {p.median_offset_m:+.2f} m ({p.laps} laps)"
                for k, p in c.line.points.items()
                if p is not None and p.median_offset_m is not None
            ]
            side = "tighter +/wider -" if c.line.inside_known else "off the line, side unknown"
            out.append(f"  line vs reference ({side}): " + (", ".join(pts) or "-"))
        for lc in c.laps:
            notes = " ".join(n.text + (" [muted: braking assist]" if n.muted else "") for n in lc.notes) or "-"
            out.append(f"  lap {lc.lap_number}{' (incident)' if lc.incident else ''}: {notes}")
        if c.balance is not None:
            bits = [
                f"{p} {s.recurring or '-'} (U{s.understeer}/N{s.neutral}/O{s.oversteer}, {s.verdict or 'no verdict'})"
                for p, s in c.balance.items()
                if s.laps
            ]
            if bits:
                out.append("  balance: " + ", ".join(bits))
        for h in c.habits[:2]:
            out.append(f"  habit: {h.text}")
    out.append("Symptoms:" if st.symptoms else "Symptoms: none recurring")
    out.extend(f"  [{x.verdict}] {x.text}" for x in st.symptoms)
    out.extend(f"  [lock-ups] {x.text}" for x in st.lockups)
    if isinstance(setup, SetupEngineer):
        out.append("Setup to try (one change at a time):" if setup.suggestions else "Setup to try: none")
        for sg in setup.suggestions:
            blocked = f" - blocked: {sg.blocked}" if sg.blocked else ""
            out.append(f"  {sg.symptom_id} #{sg.rank}: {sg.label} {sg.from_value} -> {sg.to_value}{blocked}")
        if setup.note:
            out.append(f"  note: {setup.note}")
        out.append(f"  {setup.caveat}")
    return out


# --- end feat/technique ------------------------------------------------------------------------------------------


@app.command("llm-check")
def llm_check() -> None:
    """Discover and validate the configured local LLM endpoint."""
    from pitwall.ai.providers import OpenAICompatibleProvider

    s = get_settings()

    async def run() -> None:
        p = OpenAICompatibleProvider(s.llm_base_url, s.llm_model, s.llm_api_key, timeout_s=s.llm_timeout_s)
        try:
            h = await p.health()
            typer.echo(
                f"endpoint: {h.base_url}\nok: {h.ok} ({h.detail})\nmodel: {h.model}\n"
                f"context tokens per slot: {h.context_tokens}"
            )
            if h.ok:
                r = await p.chat([{"role": "user", "content": "Reply with exactly: radio check OK"}], max_tokens=10)
                typer.echo(f"test reply: {r.text!r} in {r.latency_ms} ms")
        finally:
            await p.aclose()

    asyncio.run(run())


@app.command()
def capabilities() -> None:
    """Print the integration capability matrix."""
    from pitwall.capabilities import capability_matrix

    for row in capability_matrix():
        typer.echo(f"{row['status']:22} {'impl' if row['implemented'] else '    '}  {row['game']} [{row['platform']}]")
        typer.echo(f"{'':28}{row['notes']}")


@app.command()
def token() -> None:
    """Show the access token and LAN URL for phones/tablets."""
    s: Settings = get_settings()
    t = s.resolve_access_token()
    typer.echo(f"http://{_lan_ip()}:{s.http_port}/?token={t}")


@app.command()
def doctor(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable report (used by /setup-pitwall)")] = False,
    llm: Annotated[bool, typer.Option("--llm/--no-llm", help="Contact the configured AI provider's endpoint")] = True,
) -> None:
    """Check this computer's setup (Python, dashboard, ports, firewall, voice, AI, token) with a fix for each problem.

    Read-only. Exit code 1 when a check fails.
    """
    from pitwall.doctor import main

    raise typer.Exit(main(as_json, llm, echo=typer.echo))


# ---------------------------------------------------------------------------------------------- pitwall game
game_app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="What you're playing: the game catalogue, what each game sends, and the household's selection.",
)
app.add_typer(game_app, name="game")
SERVER_PROBE_S = 1.5
NO_REPLY = 0  # _http status: something accepted the connection but no HTTP reply came (timeout, dropped connection)


def _http(method: str, url: str, body: dict[str, Any] | None = None, timeout_s: float = 10.0) -> tuple[int, Any] | None:
    """One request to a local Pitwall. ``None`` only when nothing listens (the connection is refused); a timeout or a
    dropped connection is ``(NO_REPLY, None)``: a server may be there, just slow (a swapping Mac during a race).
    Loopback is trusted (no token); a server bound to a LAN address gets the access token header."""
    import httpx

    from pitwall.doctor import _is_loopback_host

    headers: dict[str, str] = {}
    try:
        host = httpx.URL(url).host
    except (httpx.InvalidURL, ValueError):
        return None
    if not _is_loopback_host(host):
        headers["x-pitwall-token"] = get_settings().resolve_access_token()
    try:
        with httpx.Client(timeout=timeout_s, trust_env=False, follow_redirects=False) as client:
            r = client.request(method, url, json=body, headers=headers)
    except httpx.ConnectError:
        return None  # refused (or no such host): nothing is listening
    except (httpx.HTTPError, OSError):
        return NO_REPLY, None
    try:
        data = r.json()
    except ValueError:
        data = None
    return r.status_code, data


def _server(s: Settings, strict: bool = False) -> tuple[str, str] | None:
    """(base URL, version) of a Pitwall answering on the configured HTTP port; None when nothing listens there.

    Something that listens but does not answer like Pitwall (a timeout, a 401, another program) is not "no server":
    with ``strict`` (commands that would otherwise write settings.json under a running server) the command stops with
    exit code 1; without it (read-only commands) it reads as no server."""
    from pitwall.doctor import client_host

    base = f"http://{client_host(s.http_host)}:{s.http_port}"
    reply = _http("GET", f"{base}/api/health", timeout_s=SERVER_PROBE_S)
    if reply is None:
        return None
    status, data = reply
    if status == 200 and isinstance(data, dict) and isinstance(data.get("connection"), dict):
        return base, str(data.get("version") or "?")
    if not strict:
        return None
    if status == NO_REPLY:
        what = f"did not answer within {SERVER_PROBE_S:g} s"
    elif status != 200:
        what = f"answered HTTP {status}"
    else:
        what = "did not answer like Pitwall"
    typer.echo(
        f"something listens on {base} but {what}: if Pitwall is running there, it may be busy - retry in a moment "
        "(settings.json is left alone while a server may be running)",
        err=True,
    )
    raise typer.Exit(1)


def _stored_sections(s: Settings) -> dict[str, Any]:
    """settings.json sections, read without side effects (the server writes this file on every change)."""
    from pitwall.doctor import _read_settings_file

    return _read_settings_file(s.data_dir / "settings.json")[0]


def _configs(s: Settings) -> dict[str, Any]:
    from pitwall.integrations import resolve_configs

    return resolve_configs(s, _stored_sections(s).get("integrations") or {})


def _selected_id(s: Settings) -> str | None:
    from pitwall import games

    sel = games.parse_selection(_stored_sections(s).get(games.SECTION) or {})
    return sel.id if sel is not None else None


def _older_server(version: str) -> typer.Exit:
    typer.echo(
        f"the running Pitwall (version {version}) predates game selection: update it and restart, then run this again",
        err=True,
    )
    return typer.Exit(1)


def _entry_or_bad(entry_id: str) -> Any:
    from pitwall import games

    e = games.entry(entry_id)
    if e is None:
        raise typer.BadParameter(f"unknown game {entry_id!r}: see uv run pitwall game list --all", param_hint="ID")
    return e


@game_app.command("list")
def game_list(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
    show_all: Annotated[bool, typer.Option("--all", help="Include the 'more games' group")] = False,
) -> None:
    """List the games Pitwall knows, with how well each is supported (* = selected)."""
    from pitwall import games

    s = get_settings()
    selected = _selected_id(s)
    shown = [e for e in games.entries() if show_all or e.group == "main"]
    if as_json:
        configs = _configs(s)
        out = {"selected": selected, "entries": [e.to_dict(configs) for e in shown]}
        typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return
    for e in shown:
        mark = "*" if e.id == selected else " "
        name = e.label if e.platform == "any" else f"{e.label} · {e.platform_label}"
        typer.echo(f"{mark} {e.id:22} {name:42} {e.support_words}")
    if selected is None:
        typer.echo("\nNo game selected: uv run pitwall game set <id>")


@game_app.command("show")
def game_show(
    entry_id: Annotated[str | None, typer.Argument(metavar="ID", help="Defaults to the selected game")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    """What a game sends and what Pitwall does with it (support level, features, setup guide)."""
    from dataclasses import asdict

    from pitwall import games
    from pitwall.connect import game_guides, primary_lan_ip

    s = get_settings()
    selected = _selected_id(s)
    eid = entry_id or selected
    if eid is None:
        typer.echo("no game selected: uv run pitwall game set <id> (see: uv run pitwall game list)", err=True)
        raise typer.Exit(1)
    e = _entry_or_bad(eid)
    configs = _configs(s)
    guide: dict[str, Any] | None = None
    game_input: dict[str, Any] | None = None
    server = _server(s)
    if server is not None:
        base, _version = server
        got = _http("GET", f"{base}/api/games/{e.id}")
        if got is not None and got[0] == 200 and isinstance(got[1], dict):
            guide = got[1].get("guide")
        rows = _http("GET", f"{base}/api/integrations")
        if rows is not None and rows[0] == 200 and isinstance(rows[1], list):
            game_input = games.game_input(e, rows[1])
    if guide is None and e.guide_id is not None:
        ac = configs["ac"]
        ip = primary_lan_ip() or f"<{this_machine()}'s IP>"
        g = next((x for x in game_guides(ip, s, ac.console_ip, ac.platform) if x.id == e.guide_id), None)
        guide = asdict(g) if g is not None else None
    if game_input is None:
        game_input = games.game_input(e, [c.to_dict() for c in configs.values()])
    if as_json:
        out = {
            "entry": e.to_dict(configs, with_fields=True, guide=guide),
            "selected": e.id == selected,
            "guide": guide,
            "input": game_input,
        }
        typer.echo(json.dumps(out, indent=2, ensure_ascii=False))
        return
    name = e.label if e.platform == "any" else f"{e.label} · {e.platform_label}"
    typer.echo(f"{name} ({e.id}){'  [selected]' if e.id == selected else ''}")
    typer.echo(f"Support: {e.support_words}. {e.row.notes if e.row is not None else games.OTHER_NOTE}")
    if e.integration is not None:
        typer.echo(f"Telemetry: {games.transport(e.integration, configs)['summary']}")
    by_short: dict[str, list[str]] = {}
    for f in e.features:
        if f.status in games.UNAVAILABLE:
            by_short.setdefault(f.short, []).append(f.noun)
    for short, nouns in by_short.items():
        typer.echo(f"{short}: {', '.join(nouns)}")
    for gid, glabel in games.GROUPS:
        feats = sorted((f for f in e.features if f.group == gid), key=lambda f: not f.available)
        typer.echo(f"\n{glabel}")
        for f in feats:
            status = {
                "supported": "yes",
                "partial": f.short.lower(),
                "not_sent": "not sent",
                "not_implemented": "not yet",
            }.get(f.status, "unknown")
            typer.echo(f"  {f.label:32} {status:10} {f.reason}")


@game_app.command("set")
def game_set(
    entry_id: Annotated[str, typer.Argument(metavar="ID", help="A catalogue id, e.g. gt7:ps5 (pitwall game list)")],
    console_ip: Annotated[
        str | None, typer.Option("--console-ip", help="The console's LAN IP (Assetto Corsa: required; GT7: optional)")
    ] = None,
    no_input: Annotated[bool, typer.Option("--no-input", help="Only record the selection; leave inputs alone")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    """Tell Pitwall what you play: saves the selection and switches that game's telemetry input on (never off)."""
    from pitwall import games
    from pitwall.settings_store import SettingsStore

    s = get_settings()
    e = _entry_or_bad(entry_id)
    server = _server(s, strict=True)
    if server is not None:  # never write settings.json while a server runs: it would overwrite it
        base, version = server
        body = {"id": e.id, "console_ip": console_ip, "ensure_input": not no_input, "source": "cli"}
        reply = _http("PUT", f"{base}/api/game", body)
        if reply is None or reply[0] == NO_REPLY:
            typer.echo(f"the running Pitwall at {base} did not answer: retry in a moment", err=True)
            raise typer.Exit(1)
        status, data = reply
        if status == 404:
            raise _older_server(version)
        if status != 200 or not isinstance(data, dict):
            detail = data.get("detail") if isinstance(data, dict) else None
            typer.echo(f"the running Pitwall refused: {detail or f'HTTP {status}'}", err=True)
            raise typer.Exit(1)
        actions = data.get("actions") or []
        via = "server"
    else:
        try:
            ip = games.validate_console_ip(e, console_ip)
        except ValueError as err:
            typer.echo(str(err), err=True)
            raise typer.Exit(1) from err
        store = SettingsStore(s.data_dir / "settings.json")
        store.replace(games.SECTION, games.new_selection(e.id, "cli").section())
        actions = [] if no_input else games.ensure_input(e, s, store, None, ip)
        via = "file"
    if as_json:
        typer.echo(json.dumps({"selected": e.id, "via": via, "actions": actions}, indent=2, ensure_ascii=False))
        return
    typer.echo(f"Selected {e.where} ({e.id}): {e.support_words}.")
    for a in actions:
        typer.echo(f"  {a.get('action')}: {a.get('message')}")


@game_app.command("clear")
def game_clear() -> None:
    """Forget the selected game (inputs stay as they are)."""
    from pitwall import games
    from pitwall.settings_store import SettingsStore

    s = get_settings()
    server = _server(s, strict=True)
    if server is not None:
        base, version = server
        reply = _http("DELETE", f"{base}/api/game")
        if reply is not None and reply[0] == 404:
            raise _older_server(version)
        if reply is None or reply[0] != 200:
            typer.echo("the running Pitwall did not clear the selection", err=True)
            raise typer.Exit(1)
    else:
        SettingsStore(s.data_dir / "settings.json").replace(games.SECTION, {})
    typer.echo("No game selected.")


# ---------------------------------------------------------------- lane motivation: goals, recap, digest (read-only)
def _motivation_driver(db: object, driver: str | None) -> int:
    """A driver id from ``--driver NAME|ID``, else the driver in the seat."""
    from pitwall.storage import repo
    from pitwall.storage.db import Database

    assert isinstance(db, Database)
    with db.read() as c:
        if driver is None:
            did = repo.active_driver_id(c)
        elif driver.isdigit():
            row = repo.get_driver(c, int(driver))
            did = None if row is None else int(row["id"])
        else:
            row = repo.find_driver_by_name(c, driver)
            did = None if row is None else int(row["id"])
    if did is None:
        typer.echo(f"no driver {driver!r}" if driver else "no driver in the seat", err=True)
        raise typer.Exit(1)
    return did


@app.command()
def goals(
    driver: Annotated[str | None, typer.Option("--driver", help="Driver name or id (default: in the seat)")] = None,
    suggest: Annotated[bool, typer.Option("--suggest", help="Also list suggested goals")] = False,
    game: str | None = None,
    track: Annotated[str | None, typer.Option("--track", help="Track id for suggestions")] = None,
    car: Annotated[str | None, typer.Option("--car", help="Car id for suggestions")] = None,
) -> None:
    """List a driver's goals with their progress (and suggestions with --suggest)."""
    from pitwall.motivation.service import MotivationService
    from pitwall.storage.db import Database

    db = Database(get_settings().db_path)
    svc = MotivationService(db)
    did = _motivation_driver(db, driver)
    res = svc.goals_response(did, ("active", "achieved", "archived"))
    if not res["goals"]:
        typer.echo("no goals")
    for g in res["goals"]:
        where = f" ({g['scope_text']})" if g["scope_text"] else ""
        typer.echo(f"[{g['status']:8}] #{g['id']} {g['title']}{where}: {g['progress']['text']}")
    if suggest:
        sug = svc.suggestions_response(did, game=game, track_id=track, car=car)
        typer.echo("\nSuggested:")
        for s_ in sug["suggestions"]:
            where = f" ({s_['scope_text']})" if s_["scope_text"] else ""
            typer.echo(f"  {s_['title']}{where}: {s_['basis']['text']}")
        if sug["none_reason"]:
            typer.echo(f"  ({sug['none_reason']})")


@app.command()
def recap(session_id: Annotated[str | None, typer.Argument()] = None) -> None:
    """Print a session's 3 things (went well, one to work on, progress); default: the seated driver's latest."""
    from pitwall.motivation.service import MotivationService
    from pitwall.storage import repo
    from pitwall.storage.db import Database

    db = Database(get_settings().db_path)
    with db.read() as c:
        sid = session_id or repo.latest_session_id(c, driver_id=repo.active_driver_id(c))
    if sid is None:
        typer.echo("no sessions recorded", err=True)
        raise typer.Exit(1)
    out = MotivationService(db).recap(sid)
    if out is None:
        typer.echo(f"session {sid} not found", err=True)
        raise typer.Exit(1)
    simple = bool(out["simple"])
    for key, label in (("went_well", "Went well"), ("work_on", "One to work on"), ("progress", "Progress")):
        thing = out["things"][key]
        if thing is None:
            typer.echo(f"{label}: - ({out['why_empty'][key]})")
        else:
            typer.echo(f"{label}: {thing['text_simple'] if simple else thing['text']}")
            if thing.get("evidence"):
                typer.echo(f"    {thing['evidence']}")


@app.command()
def digest(
    driver: Annotated[str | None, typer.Option("--driver", help="Driver name or id (default: in the seat)")] = None,
    week: Annotated[str | None, typer.Option("--week", help="Any date in the week, YYYY-MM-DD")] = None,
    html: Annotated[Path | None, typer.Option("--html", help="Write the printable page here")] = None,
) -> None:
    """Print a driver's weekly digest as Markdown, or write the printable HTML page."""
    from datetime import date

    from pitwall.motivation.html import digest_html
    from pitwall.motivation.service import MotivationService
    from pitwall.storage.db import Database

    db = Database(get_settings().db_path)
    did = _motivation_driver(db, driver)
    d = MotivationService(db).digest(did, date.fromisoformat(week) if week else None)
    if html is not None:
        html.write_text(digest_html(d), encoding="utf-8")
        typer.echo(f"wrote {html}")
    else:
        typer.echo(d["markdown"])


@app.callback()
def _main() -> None:
    _windows_safe_output()


if __name__ == "__main__":
    app()
