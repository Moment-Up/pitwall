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
from typing import Annotated

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


@app.callback()
def _main() -> None:
    _windows_safe_output()


if __name__ == "__main__":
    app()
