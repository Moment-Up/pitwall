"""FastAPI application: REST + WebSocket API and static dashboard hosting."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
import orjson
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Scope

from pitwall import __version__
from pitwall.ai.engineer import RaceEngineer
from pitwall.ai.facts import build_fact_sheet
from pitwall.ai.provider_registry import SwitchableProvider, config_from_settings
from pitwall.analysis.distance import to_distance_domain
from pitwall.analysis.track_identity import corner_texts, identify, track_model_payload
from pitwall.analysis.track_skeleton import skeleton_from_session_row
from pitwall.api.auth import AccessPolicy, detect_tailscale
from pitwall.config import Settings, get_settings
from pitwall.core.runtime import Runtime
from pitwall.core.session_analysis import SessionAnalyzer
from pitwall.ingest.capture import CaptureReader
from pitwall.model.telemetry import TrackZones
from pitwall.storage import repo

log = logging.getLogger(__name__)
WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"  # Svelte (frozen): served only if web-react is unbuilt
WEB_REACT_DIST = Path(__file__).resolve().parents[3] / "web-react" / "dist"  # React + HeroUI dashboard, at / and /next/


class OrjsonResponse(JSONResponse):
    """orjson: fast, serialises dataclasses/numpy, and turns NaN into null (valid JSON)."""

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS)


class DashboardFiles(StaticFiles):
    """A built dashboard (``html=True``). index.html and the other unhashed files are revalidated on every load
    (no-cache), so after a release or the switch-over no browser keeps running a cached page whose hashed assets are
    gone; Vite's hashed ``assets/*`` never change, so they are cached for a year. ``fallback``: another build whose
    files are served when this one lacks them (see the static block in create_app)."""

    def __init__(self, directory: Path, fallback: Path | None = None) -> None:
        super().__init__(directory=directory, html=True)
        if fallback is not None and fallback.is_dir():
            self.all_directories.append(fallback)

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        # Starlette passes the OS path (os.path.normpath: "assets\\x.js" on Windows); compare with "/" separators.
        immutable = path.replace(os.sep, "/").startswith("assets/") and response.status_code in (200, 304)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return response


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: str | None = None
    use_llm: bool = True


class SayRequest(BaseModel):
    # Module level: with ``from __future__ import annotations`` FastAPI cannot resolve a model defined inside
    # create_app, and silently treats ``body`` as a query parameter (POST /api/voice/say and /ask returned 422).
    text: str = Field(min_length=1, max_length=400)


class ReplayRequest(BaseModel):
    path: str
    speed: float | None = 1.0
    loop: bool = False


class ReferenceRequest(BaseModel):
    lap_id: int
    label: str | None = None


class SimulateRequest(BaseModel):
    scenario: str = "coaching-demo"
    packet_format: int = 2025


def create_app(settings: Settings | None = None, start_udp: bool = True) -> FastAPI:
    settings = settings or get_settings()
    token = settings.resolve_access_token()
    logins = set(settings.tailscale_allowed_logins)
    ts = detect_tailscale()
    if ts and settings.tailscale_trust_owner and ts.owner_login:
        logins.add(ts.owner_login)
    policy = AccessPolicy(token, frozenset(logins), ts.ips if ts else frozenset())
    tailscale_dns = ts.dns_name if ts else None
    if ts:
        log.info(
            "tailscale: %s (%s); identity-trusted logins: %s", ts.dns_name, ",".join(sorted(ts.ips)), sorted(logins)
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        rt = Runtime(settings)
        app.state.runtime = rt
        app.state.analyzer = SessionAnalyzer(rt.db)
        # One provider object for the whole app. It follows Settings > AI engineer (SettingsStore section "llm":
        # local Qwen, Claude, OpenAI-compatible clouds) and hot-swaps on change; until that section is saved the
        # PITWALL_LLM_* environment settings apply. Driver names are redacted before anything goes to a cloud.
        provider = SwitchableProvider(
            rt.store,
            rt.secrets,
            defaults=config_from_settings(settings),
            usage_path=settings.data_dir / "llm_usage.json",
            names=lambda: [settings.driver_name, *(d.name for d in rt.drivers.list_drivers())],
            default_keys={"llm_api_key": settings.llm_api_key},  # PITWALL_LLM_API_KEY keeps working (local only)
        )
        rt.drivers.subscribe(lambda _driver: provider.invalidate_names())
        app.state.llm = provider
        app.state.provider = provider
        app.state.engineer = RaceEngineer(provider, settings.llm_max_tokens, settings.llm_temperature)
        # The radio answers with the fast "radio" model (same provider object, so it hot-swaps too).
        radio_engineer = RaceEngineer(provider.for_purpose("radio"), settings.llm_max_tokens, settings.llm_temperature)
        app.state.hub = None
        app.state.radio_detach = None

        # Braking cues follow the seated driver too (their focus limits; a new driver drops the old cue plan).
        def cues_follow_driver(d: Any) -> None:
            rt.live.on_driver(d.id if d else None, d.coaching if d else None)

        rt.drivers.subscribe(cues_follow_driver)
        cues_follow_driver(rt.drivers.active)
        if settings.voice_enabled:
            from pitwall.voice.factory import build_radio_hub

            try:
                hub = build_radio_hub(settings, rt.live, radio_engineer, rt.db, app.state.analyzer, rt.drivers)
                hub.start()
                app.state.hub = hub
                # The radio follows whoever is in the seat: their coaching amount, voice switch and skill limits.
                loop = asyncio.get_running_loop()

                def radio_follows(d: Any) -> None:
                    loop.call_soon_threadsafe(hub.apply_driver, d)

                app.state.radio_detach = rt.drivers.attach_radio(radio_follows)
                log.info("radio ready: stt=%s tts=%s", hub.stt.name, hub.tts.name)
            except Exception:
                log.exception("radio unavailable (voice disabled for this run)")
        if start_udp:
            try:
                rt.start_udp()
            except OSError as e:
                log.error("could not bind UDP port %d: %s", settings.f1_udp_port, e)
        log.info("pitwall %s ready on http://%s:%d", __version__, settings.http_host, settings.http_port)
        try:
            yield
        finally:
            if app.state.radio_detach is not None:
                app.state.radio_detach()
            if app.state.hub is not None:
                await app.state.hub.stop()
            rt.close()
            await provider.aclose()

    app = FastAPI(title="Pitwall", version=__version__, lifespan=lifespan, default_response_class=OrjsonResponse)
    app.add_middleware(GZipMiddleware, minimum_size=1024)  # dashboard bundles + JSON; WebSockets pass through

    # ------------------------------------------------------------------ access control
    @app.middleware("http")
    async def auth(request: Request, call_next: Any) -> Response:
        decision = policy.check(
            request.client.host if request.client else None,
            request.headers,
            request.query_params.get("token"),
            request.cookies.get("pitwall_token"),
        )
        if request.url.path.startswith("/api/") and not decision.allowed:
            log.info(
                "denied %s from %s (headers: %s)",
                request.url.path,
                request.client.host if request.client else None,
                ",".join(sorted(k.lower() for k in request.headers)),
            )
            return OrjsonResponse({"detail": "access token required"}, status_code=401)
        response: Response = await call_next(request)
        if decision.set_cookie:
            response.set_cookie(
                "pitwall_token",
                token,
                httponly=True,
                secure=request.url.scheme == "https" or "x-forwarded-proto" in request.headers,
                samesite="strict",
                max_age=30 * 86400,
            )
        return response

    def ws_allowed(ws: WebSocket) -> bool:
        return policy.check(
            ws.client.host if ws.client else None,
            ws.headers,
            ws.query_params.get("token"),
            ws.cookies.get("pitwall_token"),
        ).allowed

    def rt(request: Request | WebSocket) -> Runtime:
        return request.app.state.runtime  # type: ignore[no-any-return]

    # ------------------------------------------------------------------ status
    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        r = rt(request)
        return {
            "version": __version__,
            "time": time.time(),
            "connection": r.live.connection(),
            "udp_port": settings.f1_udp_port if r.udp else None,
            "replay": r.replay_status(),
            "db_writer_errors": r.writer.errors,
            "analysis_errors": r.worker.errors,
            "laps_processed": r.processor.processed,
        }

    @app.get("/api/llm/health")
    async def llm_health(request: Request) -> dict[str, Any]:
        return asdict(await request.app.state.provider.health())

    @app.get("/api/capabilities")
    async def capabilities() -> list[dict[str, Any]]:
        from pitwall.capabilities import capability_matrix

        return capability_matrix()

    # ------------------------------------------------------------------ live
    @app.get("/api/live")
    async def live(request: Request, static: bool = False) -> dict[str, Any]:
        return rt(request).live.snapshot(include_static=static)

    @app.websocket("/ws/live")
    async def ws_live(ws: WebSocket) -> None:
        if not ws_allowed(ws):
            await ws.close(code=4401)
            return
        await ws.accept()
        ws.app.state.live_clients = getattr(ws.app.state, "live_clients", 0) + 1
        r = rt(ws)
        loop = asyncio.get_running_loop()
        notes: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue(maxsize=100)

        def on_note(kind: str, payload: dict[str, Any]) -> None:
            def put() -> None:
                if notes.full():
                    notes.get_nowait()  # drop the oldest notification for this slow client only
                notes.put_nowait((kind, payload))

            loop.call_soon_threadsafe(put)

        r.live.subscribe(on_note)
        period = 1.0 / max(1.0, settings.live_ws_hz)
        last_version = -1
        last_static = 0.0
        try:
            while True:
                now = time.monotonic()
                static = now - last_static > 5.0
                snap = r.live.snapshot(include_static=static)
                if snap["version"] != last_version or static:
                    last_version = snap["version"]
                    if static:
                        last_static = now
                    await ws.send_bytes(orjson.dumps({"type": "snapshot", "data": snap}))
                while not notes.empty():
                    kind, payload = notes.get_nowait()
                    await ws.send_bytes(orjson.dumps({"type": kind, "data": payload}))
                await asyncio.sleep(period)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            ws.app.state.live_clients -= 1
            r.live.unsubscribe(on_note)

    # ------------------------------------------------------------------ sessions & laps
    @app.get("/api/sessions")
    async def sessions(request: Request, limit: int = 50, driver_id: int | None = None) -> list[dict[str, Any]]:
        with rt(request).db.read() as c:
            return repo.list_sessions(c, limit, driver_id=driver_id)

    @app.get("/api/sessions/{sid}")
    async def session(request: Request, sid: str) -> dict[str, Any]:
        with rt(request).db.read() as c:
            s = repo.get_session(c, sid)
            if s is None:
                raise HTTPException(404, "session not found")
            s["laps"] = repo.list_laps(c, sid)
            s["setup"] = repo.latest_setup(c, sid)
        sk = skeleton_from_session_row(s)  # game-native sectors/zones; flags are never restored from storage
        s["skeleton"] = sk.to_dict() if sk else None
        return s

    @app.get("/api/sessions/{sid}/events")
    async def session_events(request: Request, sid: str) -> list[dict[str, Any]]:
        with rt(request).db.read() as c:
            return repo.list_events(c, sid)

    @app.get("/api/sessions/{sid}/setups")
    async def session_setups(request: Request, sid: str) -> list[dict[str, Any]]:
        with rt(request).db.read() as c:
            return repo.setup_history(c, sid)

    @app.get("/api/sessions/{sid}/analysis")
    async def session_analysis(request: Request, sid: str, ref_lap_id: int | None = None) -> dict[str, Any]:
        sa = await asyncio.to_thread(request.app.state.analyzer.analyse, sid, ref_lap_id)
        if sa is None:
            raise HTTPException(404, "session not found")
        return {
            "session_id": sid,
            "ref_lap_id": sa.ref_lap_id,
            "ref_lap": sa.ref_lap,
            "track_model": track_model_payload(sa.model) if sa.model else None,  # identified by the analyzer
            "corner_summary": [asdict(c) for c in sa.corner_summary],
            "observations": {str(k): v for k, v in sa.observations.items()},
            "comparisons": {
                str(lid): {
                    "cmp_lap_number": c.cmp_lap_number,
                    "total_delta_s": c.total_delta_s,
                    "compatibility": asdict(c.compatibility),
                    "corners": [{k: v for k, v in asdict(cd).items() if k not in ("ref", "cmp")} for cd in c.corners],
                }
                for lid, c in sa.comparisons.items()
            },
        }

    @app.get("/api/sessions/{sid}/report")
    async def session_report(request: Request, sid: str) -> dict[str, Any]:
        from pitwall.core.report import build_report

        sa = await asyncio.to_thread(request.app.state.analyzer.analyse, sid, None)
        if sa is None:
            raise HTTPException(404, "session not found")
        return build_report(sa)

    @app.get("/api/laps/{lap_id}/trace")
    async def lap_trace(request: Request, lap_id: int, step: float = 2.0) -> Response:
        with rt(request).db.read() as c:
            trace = repo.load_lap_trace(c, lap_id)
            row = repo.get_lap(c, lap_id, with_trace=False)
            sess = repo.get_session(c, row["session_id"]) if row else None
        if trace is None or sess is None:
            raise HTTPException(404, "lap not found")
        length = sess.get("track_length_m") or float(np.nanmax(trace.channels["distance_m"]))
        dt = to_distance_domain(trace, length, step_m=max(0.5, step))
        body = {
            "lap_id": lap_id,
            "lap_number": trace.lap_number,
            "lap_time_ms": trace.lap_time_ms,
            "d": dt.d,
            "t_s": dt.t_s,
            **{
                k: v
                for k, v in dt.ch.items()
                if k
                in (
                    "speed_kph",
                    "throttle",
                    "brake",
                    "steering",
                    "gear",
                    "rpm",
                    "pos_x_m",
                    "pos_y_m",
                    "pos_z_m",
                    "g_lat",
                    "g_lon",
                )
            },
        }
        return OrjsonResponse(body)

    @app.get("/api/compare")
    async def compare_laps(request: Request, ref: int, lap: int) -> dict[str, Any]:
        from pitwall.analysis.coaching import observations_for_comparison
        from pitwall.analysis.compare import analyse_lap, check_compatibility, compare, compat_meta
        from pitwall.core.session_analysis import session_ctx

        r = rt(request)

        def work() -> dict[str, Any]:
            with r.db.read() as c:
                a, b = repo.load_lap_trace(c, ref), repo.load_lap_trace(c, lap)
                if a is None or b is None:
                    raise HTTPException(404, "lap not found")
                sa = repo.get_session(c, a.meta["session_id"])
                sb = repo.get_session(c, b.meta["session_id"])
                assert sa is not None and sb is not None
                model = repo.load_track_model(c, sa["game"], sa["track_id"]) if sa.get("track_id") else None
            if model is None:
                raise HTTPException(409, "no track model yet for this track (complete a clean lap first)")
            a.meta.update(session_ctx(sa))
            b.meta.update(session_ctx(sb))
            compat = check_compatibility(compat_meta(a.meta), compat_meta(b.meta), a.clean)
            model = identify(model, zones=TrackZones.from_dict((sb.get("info") or {}).get("track_zones")))[0]
            ra, rb = analyse_lap(a, model), analyse_lap(b, model)
            comp = compare(ra, rb, compat)
            obs = observations_for_comparison(comp, corner_text=corner_texts(model))
            return {
                "comparison": comp.to_dict(),
                "observations": [o.to_dict() for o in obs],
                "track_model": track_model_payload(model),
            }

        return await asyncio.to_thread(work)

    @app.post("/api/references")
    async def pin_reference(request: Request, body: ReferenceRequest) -> dict[str, Any]:
        r = rt(request)
        try:
            rid = r.writer.call(lambda c: repo.pin_reference(c, body.lap_id, body.label))
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
        return {"reference_id": rid, "lap_id": body.lap_id}

    @app.get("/api/track-model")
    async def track_model(request: Request, game: str, track_id: str) -> dict[str, Any]:
        with rt(request).db.read() as c:
            m = repo.load_track_model(c, game, track_id)
        if m is None:
            raise HTTPException(404, "no model")
        return track_model_payload(identify(m)[0])

    # ------------------------------------------------------------------ captures / replay / simulation
    @app.get("/api/captures")
    async def captures() -> list[dict[str, Any]]:
        out = []
        for p in sorted(settings.capture_dir.glob("*.pwcap"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                meta = CaptureReader(p).meta
            except Exception:
                continue
            out.append(
                {
                    "path": str(p),
                    "name": p.name,
                    "size_bytes": p.stat().st_size,
                    "synthetic": meta.synthetic,
                    "description": meta.description,
                    "created_unix": meta.created_unix,
                }
            )
        return out

    @app.post("/api/replay")
    async def start_replay(request: Request, body: ReplayRequest) -> dict[str, Any]:
        path = Path(body.path).resolve()
        if settings.capture_dir.resolve() not in path.parents or not path.exists():
            raise HTTPException(400, "path must be an existing capture inside the data/captures directory")
        rt(request).start_replay(path, speed=body.speed, loop=body.loop)
        return {"replaying": str(path), "speed": body.speed}

    @app.delete("/api/replay")
    async def stop_replay(request: Request) -> dict[str, Any]:
        rt(request).stop_replay()
        return {"stopped": True}

    @app.post("/api/simulate")
    async def simulate(body: SimulateRequest) -> dict[str, Any]:
        from pitwall.sim.f1_stream import F1Scenario
        from pitwall.sim.scenarios import SCENARIOS, write_synthetic_capture

        if body.scenario not in SCENARIOS:
            raise HTTPException(404, f"unknown scenario; options: {sorted(SCENARIOS)}")
        sc: F1Scenario = SCENARIOS[body.scenario]()
        sc.packet_format = body.packet_format
        path = settings.capture_dir / f"synthetic-{body.scenario}-{body.packet_format}.pwcap"
        truth = await asyncio.to_thread(write_synthetic_capture, path, sc, body.scenario)
        return {"path": str(path), "synthetic": True, "lap_times_ms": truth.lap_times_ms}

    # ------------------------------------------------------------------ AI engineer
    @app.post("/api/engineer/ask")
    async def ask(request: Request, body: AskRequest) -> dict[str, Any]:
        r = rt(request)
        sid = body.session_id or await asyncio.to_thread(r.drivers.session_for_questions, r.live.session_id)
        if sid is None:
            raise HTTPException(409, "no sessions recorded yet for the driver in the seat")
        sa = await asyncio.to_thread(request.app.state.analyzer.analyse, sid, None)
        if sa is None:
            raise HTTPException(404, "session not found")
        live_snap = r.live.snapshot() if r.live.session_id == sid else None
        sheet = build_fact_sheet(sa, live_snap)
        history: list[dict[str, str]] = []
        if settings.store_conversations:
            with r.db.read() as c:
                history = [{"role": m["role"], "text": m["text"]} for m in repo.list_messages(c, sid, 6)]
        ans = await request.app.state.engineer.answer(body.question, sheet, history, use_llm=body.use_llm)
        if settings.store_conversations:

            def store(c: Any) -> None:
                repo.insert_message(c, sid, "user", body.question, intent=ans.intent)
                repo.insert_message(
                    c,
                    sid,
                    "engineer",
                    ans.text,
                    intent=ans.intent,
                    facts=ans.facts,
                    model=ans.model,
                    latency_ms=ans.latency_ms,
                    grounded=ans.grounded,
                    fallback=ans.fallback,
                )

            r.writer.submit(store)
        return {"session_id": sid, **asdict(ans)}

    @app.get("/api/engineer/history")
    async def ask_history(request: Request, session_id: str | None = None) -> list[dict[str, Any]]:
        with rt(request).db.read() as c:
            return repo.list_messages(c, session_id, 50)

    @app.get("/api/engineer/facts")
    async def facts(request: Request, session_id: str) -> list[dict[str, Any]]:
        sa = await asyncio.to_thread(request.app.state.analyzer.analyse, session_id, None)
        if sa is None:
            raise HTTPException(404, "session not found")
        r = rt(request)
        live_snap = r.live.snapshot() if r.live.session_id == session_id else None
        return [asdict(f) for f in build_fact_sheet(sa, live_snap).facts]

    # ------------------------------------------------------------------ connect page
    @app.get("/api/connect")
    async def connect_page(request: Request) -> dict[str, Any]:
        from pitwall.connect import connect_info

        r = rt(request)
        info = await asyncio.to_thread(connect_info, settings, tailscale_dns, token, r.input_status())
        conn = r.live.connection()
        sess = r.live.session
        decode = conn.get("decode") or {}
        err = str(decode.get("last_error") or "")
        hint = None
        if "packetFormat 2024" in err or "packetFormat 2023" in err:
            hint = "The game is sending an old UDP format: set UDP Format to 2025 (or 2026) in Telemetry Settings."
        elif "size" in err:
            hint = "Packet sizes don't match the selected format: check the in-game UDP Format setting."
        elif conn.get("unrecognised"):
            hint = "Packets arrived that aren't F1 25 telemetry: check which device/game is sending to this port."
        hub = request.app.state.hub
        return {
            **info,
            "udp": {
                "listening": r.udp is not None,
                "port": settings.f1_udp_port,
                "received": r.udp.received if r.udp else 0,
                "sources": r.udp.source_snapshot() if r.udp else [],
                "capture": str(r.udp.capture.path) if r.udp and r.udp.capture else None,
            },
            "telemetry": {
                **conn,
                "game": sess.game.value if sess else None,
                "track": sess.track_name if sess else None,
                "session_type": sess.session_type_raw if sess else None,
                "platform": sess.platform.value if sess else None,
                "packet_format": sess.extra.get("packet_format") if sess else None,
                "game_version": sess.extra.get("game_version") if sess else None,
                "hint": hint,
            },
            "radio": hub.status()["clients"] if hub is not None else [],
            "radio_enabled": hub is not None,
            "dashboards": getattr(request.app.state, "live_clients", 0),
        }

    @app.get("/api/integrations")
    async def integrations(request: Request) -> list[dict[str, Any]]:
        return rt(request).input_status()

    @app.put("/api/integrations/{key}")
    async def update_integration(request: Request, key: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        """Enable a game / set its console IP or port. Applied immediately (listeners restart as needed)."""
        from pitwall.integrations import validate_update

        r = rt(request)
        try:
            clean = validate_update(key, body)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        cur = r.store.get("integrations")
        merged = {**cur, key: {**(cur.get(key) or {}), **clean}}
        from pitwall.integrations import port_conflicts, resolve_configs

        conflicts = port_conflicts(resolve_configs(settings, merged).values())
        if conflicts:
            raise HTTPException(409, "two enabled games would share a port: " + "; ".join(conflicts))
        await asyncio.to_thread(r.store.update, "integrations", {key: merged[key]})
        return r.input_status()

    # ------------------------------------------------------------------ voice lab (audition TTS samples)
    PHRASES = [
        "Radio check, loud and clear.",
        "Box, box. Box this lap for mediums.",
        "Turn two: you're braking about thirteen metres earlier than your reference. That's costing you three tenths.",
        "Lap four, one oh five point seven. Purple in sector two, keep pushing.",
        "Fuel is fine, we're plus zero point four laps. Tyres look good, the front left is the limit.",
        "Copy, checking.",
    ]

    @app.get("/api/voicelab", response_class=HTMLResponse)
    async def voicelab() -> str:
        import html

        root = settings.voicelab_dir
        if root is None or not root.is_dir():
            return "<p>No voice lab samples configured (PITWALL_VOICELAB_DIR).</p>"
        rows = []
        for d in sorted(p for p in root.iterdir() if p.is_dir()):
            wavs = sorted(d.glob("[0-9][0-9].wav"))
            if not wavs:
                continue
            engine, _, voice = d.name.partition("__")
            players = "".join(
                f'<div class="p"><span>{html.escape(PHRASES[int(w.stem) - 1] if 0 < int(w.stem) <= 6 else w.stem)}'
                f'</span><audio controls preload="none" src="/api/voicelab/{html.escape(d.name)}/{w.name}"></audio>'
                f"</div>"
                for w in wavs
            )
            rows.append(
                f"<details><summary><b>{html.escape(voice or 'default')}</b> · "
                f'<span class="e">{html.escape(engine)}</span></summary>{players}</details>'
            )
        return (
            "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Pitwall voice lab</title><style>body{font:16px -apple-system,sans-serif;background:#0b0d10;"
            "color:#e8ebf0;margin:16px}details{border:1px solid #232b35;border-radius:10px;padding:10px 14px;"
            "margin:8px 0;background:#12161b}summary{cursor:pointer;font-size:18px}.e{color:#8a94a3}"
            ".p{display:grid;gap:4px;margin:10px 0}.p span{color:#8a94a3;font-size:14px}audio{width:100%}</style>"
            "<h2>Voice lab</h2><p style='color:#8a94a3'>Tap a voice, play the clips through the AirPod, and tell"
            " Claude which one you want for the race engineer.</p>" + "".join(rows)
        )

    @app.get("/api/voicelab/{folder}/{name}")
    async def voicelab_file(folder: str, name: str) -> Response:
        from fastapi.responses import FileResponse

        root = settings.voicelab_dir
        if root is None:
            raise HTTPException(404)
        path = (root / folder / name).resolve()
        if root.resolve() not in path.parents or path.suffix != ".wav" or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="audio/wav")

    # ------------------------------------------------------------------ voice radio
    @app.websocket("/ws/radio")
    async def ws_radio(ws: WebSocket) -> None:
        from pitwall.voice.hub import RadioClient

        if not ws_allowed(ws):
            await ws.close(code=4401)
            return
        await ws.accept()
        hub = ws.app.state.hub
        if hub is None:
            await ws.send_text(orjson.dumps({"type": "error", "message": "voice is disabled"}).decode())
            await ws.close()
            return

        async def send(item: Any) -> None:
            if isinstance(item, bytes | bytearray):
                await ws.send_bytes(bytes(item))
            else:
                await ws.send_text(orjson.dumps(item).decode())

        client = RadioClient(send=send)
        await hub.connect(client)
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                if m.get("bytes") is not None:
                    hub.on_audio(client, m["bytes"])
                elif m.get("text"):
                    try:
                        payload = orjson.loads(m["text"])
                    except orjson.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        await hub.on_text(client, payload)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await hub.disconnect(client)

    @app.get("/api/voice/status")
    async def voice_status(request: Request) -> dict[str, Any]:
        hub = request.app.state.hub
        return {"enabled": False} if hub is None else {"enabled": True, **hub.status()}

    @app.post("/api/voice/say")
    async def voice_say(request: Request, body: SayRequest) -> dict[str, Any]:
        """Speak arbitrary text on connected radios (radio check / testing)."""
        from pitwall.voice.types import MessageKind, Priority

        hub = request.app.state.hub
        if hub is None:
            raise HTTPException(409, "voice disabled")
        msg = hub._msg(MessageKind.INFO, Priority.HIGH, body.text, bypass=True)
        await hub.say(msg, None, None)
        return {"id": msg.id, "clients": len(hub.clients)}

    @app.post("/api/voice/ask")
    async def voice_ask(request: Request, body: SayRequest) -> dict[str, Any]:
        """A typed question answered over the radio (same pipeline as speech, minus STT)."""
        hub = request.app.state.hub
        if hub is None:
            raise HTTPException(409, "voice disabled")
        hub.ask_text(body.text)
        return {"queued": True}

    # ------------------------------------------------------------------ feature routers (before the static mount)
    from pitwall.api.routes_drivers import router as drivers_router

    app.include_router(drivers_router)
    from pitwall.api.routes_llm import router as llm_router

    app.include_router(llm_router)
    from pitwall.api.routes_rig import router as rig_router

    app.include_router(rig_router)
    from pitwall.api.routes_carsetup import router as carsetup_router

    app.include_router(carsetup_router)
    from pitwall.api.routes_track import router as track_router

    app.include_router(track_router)
    from pitwall.api.routes_strategy import router as strategy_router  # race strategy (pitwall.strategy)

    app.include_router(strategy_router)

    # ------------------------------------------------------------------ static dashboard
    # React + HeroUI dashboard (web-react/, hash-routed) at "/", built with `npm run build:root`. /next/ stays an alias
    # for a week after the switch-over: the same files, so old /next/ links and Home Screen icons keep working, and a
    # page loads its assets from the base it was built for (both are mounted). Hashes such as #/radio?token=... never
    # reach the server; the app rewrites them. The Svelte dashboard (web/, frozen) is served only while web-react is
    # not built. "/next" must be mounted before "/".
    react_index = WEB_REACT_DIST / "index.html"
    if react_index.exists():
        if '"/next/' in react_index.read_text(encoding="utf-8"):
            log.warning("web-react/dist was built for /next/ (npm run build): build it for / with `npm run build:root`")

        @app.get("/next", include_in_schema=False)
        async def next_dashboard_slash(request: Request) -> RedirectResponse:
            query = request.url.query
            return RedirectResponse(f"/next/{'?' + query if query else ''}", status_code=307)

        app.mount("/next", DashboardFiles(WEB_REACT_DIST), name="web-next")
        # Switch-over only (remove with /next/): a browser may still hold the Svelte index.html, which was served
        # without Cache-Control, so its hashed /assets/* keep loading from web/dist until that page revalidates.
        app.mount("/", DashboardFiles(WEB_REACT_DIST, fallback=WEB_DIST), name="web")
    elif WEB_DIST.exists():
        app.mount("/", DashboardFiles(WEB_DIST), name="web")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def no_ui() -> str:
            return (
                "<h1>Pitwall API is running</h1><p>The dashboard has not been built. "
                "Run <code>make web-react</code> (or <code>cd web-react && npm ci && npm run build:root</code>).</p>"
            )

    return app
