"""Application runtime: owns the database, workers, live state and packet sources.

Packet sources are per integration (``integrations.py``): one ``UdpListener`` per bound port (F1, GT7, Forza,
raw recording) and, for Assetto Corsa, one ``AcRemoteClient`` that registers with the game and receives its stream
on an ephemeral port. Each source has its own ``PacketRouter`` + ``SessionManager``, all feeding the same
``LiveState``, database writer and analysis worker.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pitwall import games
from pitwall.adapters.ac.adapter import AcTrackGeometry
from pitwall.adapters.base import GameAdapter
from pitwall.analysis.brake_prior import BrakeEnvelope, PriorRefresher
from pitwall.analysis.field_model import FieldSnapshot
from pitwall.carclass import classify_info
from pitwall.carhealth import settings as carhealth_settings  # --- health lane ---
from pitwall.carhealth.worker import CarHealthWorker  # --- health lane ---
from pitwall.config import Settings
from pitwall.controls.service import ControlsService
from pitwall.core.coachref import CoachRef
from pitwall.core.lap_processor import AnalysisWorker, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.session import SessionManager
from pitwall.core.track_knowledge import FieldWorker, PhysicsPrior, TrackKnowledgeResolver
from pitwall.drivers import Driver, DriverService
from pitwall.ingest.ac_client import CAPTURE_GAME_HINT as AC_CAPTURE_HINT
from pitwall.ingest.ac_client import AcRemoteClient
from pitwall.ingest.gt7_heartbeat import GT7Heartbeat
from pitwall.ingest.router import PacketRouter
from pitwall.ingest.sources import ReplaySource, UdpListener
from pitwall.integrations import (
    CAPTURE_ONLY,
    SPECS,
    IntegrationConfig,
    ac_platform,
    adapters_for,
    all_adapters,
    listens,
    resolve_configs,
)
from pitwall.integrations import SECTION as INTEGRATIONS_STORE_SECTION
from pitwall.model.telemetry import Game, Platform, SessionInfo
from pitwall.motivation.worker import MotivationWorker  # lane motivation
from pitwall.raceradio.names import SECTION as RACE_RADIO_SECTION  # race radio
from pitwall.raceradio.names import online_names_enabled  # race radio
from pitwall.raceradio.worker import RaceRadioWorker  # race radio
from pitwall.settings_store import SecretStore, SettingsStore
from pitwall.spotter.model import SpotterCall  # --- spotter ---
from pitwall.spotter.settings import SECTION as SPOTTER_SECTION  # --- spotter ---
from pitwall.spotter.settings import SpotterSettings, parse_stored  # --- spotter ---
from pitwall.spotter.worker import SpotterWorker  # --- spotter ---
from pitwall.storage import repo
from pitwall.storage.db import Database, DbWriter
from pitwall.strategy.worker import StrategyWorker

log = logging.getLogger(__name__)

INTEGRATIONS_SECTION = INTEGRATIONS_STORE_SECTION
BOOT_BIND_ATTEMPTS = 20  # at start-up a previous instance may still be releasing the port (launchd restart)
APPLY_BIND_ATTEMPTS = 3  # from the dashboard: fail fast and report instead of blocking the request
AC_SOURCE = "ac-remote"  # sessions.source of live Assetto Corsa sessions
AC_GEOMETRY_SCAN_SESSIONS = 1000  # most recent sessions searched for AC track geometry (an existing repo read)


def default_adapters() -> list[GameAdapter]:
    """Every decoder pitwall has (replays and tests decode any game's capture)."""
    return all_adapters()


@dataclass(slots=True)
class _Input:
    """One bound UDP port: its listener, router (own session manager) and the integrations it serves."""

    port: int
    keys: tuple[str, ...]
    listener: UdpListener
    router: PacketRouter | None  # None for capture-only inputs (raw recording of a game pitwall can't decode yet)


def _age_s(mono: float | None) -> float | None:
    """Seconds since a ``time.monotonic()`` instant (None: never)."""
    return None if mono is None else round(max(0.0, time.monotonic() - mono), 1)


@dataclass(slots=True)
class _AcInput:
    """The Assetto Corsa client (no bound port): it registers with the game and feeds its own router."""

    client: AcRemoteClient
    router: PacketRouter
    platform: str | None  # the configured platform this client's adapter was built with


def ac_known_tracks(sessions: list[dict[str, Any]]) -> dict[str, AcTrackGeometry]:
    """AC track geometry (length + spline position of the line) from stored sessions, most recent first.

    Only real (non-synthetic) AC sessions whose ``track_id`` came from the handshake contribute, and only values the
    adapter itself learned or was given (``sessions.track_length_m`` + ``info['ac_line_norm']``). The most recent
    session with a usable line position wins; one with only a length is kept if nothing better exists. A session
    whose stream contradicted the stored geometry (``info['ac_geometry_rejected']``) closes that track to every
    older session: they carry the rejected values, so only what it learned itself (if anything) is used.
    """
    out: dict[str, AcTrackGeometry] = {}
    closed: set[str] = set()
    for row in sessions:
        track_id = row.get("track_id")
        if row.get("game") != Game.AC.value or row.get("synthetic") or not isinstance(track_id, str):
            continue
        if not track_id.startswith("ac:") or track_id in closed:
            continue
        info = row.get("info")
        extra = info if isinstance(info, dict) else None
        if extra is not None and extra.get("ac_geometry_rejected") is True:
            closed.add(track_id)
        geo = AcTrackGeometry.from_session(row.get("track_length_m"), extra)
        if geo is None:
            continue
        have = out.get(track_id)
        if have is None or (have.line_norm is None and geo.line_norm is not None):
            out[track_id] = geo
    return out


def finish_router(router: PacketRouter) -> None:
    """End a router's session after releasing what an adapter still holds (AC: a lap completion waiting for
    ``lastLap`` and the frames behind it), so the last lap of a stream that stops at the line is not lost."""
    for adapter in router.adapters:
        flush = getattr(adapter, "flush", None)
        if callable(flush):
            try:
                for item in flush():
                    router.sessions.handle(item)
            except Exception:  # ending a session must never fail because of one adapter
                log.exception("flushing %s failed", adapter.info.name)
    router.finish()


def knowledge_feeds(
    resolver: TrackKnowledgeResolver,
) -> tuple[Callable[[FieldSnapshot | None], None], Callable[[SessionInfo | None], None]]:
    """Field-worker callbacks: the AI-field layer (L0b) plus the physics heavy-stop prior (L1c) for the same track.

    Both run on the field worker thread, never on ingest. The prior is rebuilt only when the track, its length, the car
    class family (``carclass``: F2 has its own default braking curve, classic cars none) or the AI field's fitted brake
    envelope change (``PriorRefresher``); it only ever yields severity windows, never positions or "brake" calls.
    """
    priors = PriorRefresher()
    family: list[str | None] = [None]  # the session's car class family (carclass): the AI-field snapshot uses it

    def push(game: str, track_id: str | None, length: float | None, env: BrakeEnvelope | None) -> None:
        changed, prior = priors.refresh(game, track_id, length, env, family[0])
        if changed:
            resolver.set_physics(None if prior is None else PhysicsPrior.from_payload(prior.to_payload()))

    def on_session(info: SessionInfo | None) -> None:
        resolver.set_session(info)
        if info is not None:
            cls = classify_info(info)
            family[0] = None if cls is None else cls.family  # F1 / unknown: the default model; F2: its own curve
            push(info.game.value, info.track_id, info.track_length_m, None)

    def on_snapshot(snap: FieldSnapshot | None) -> None:
        resolver.set_field(snap)
        fe = snap.brake_envelope if snap is not None else None
        if snap is None or fe is None:
            return
        try:
            env = BrakeEnvelope(fe.brake_base, fe.brake_aero, "AI field")  # constant source: part of the cache key
        except ValueError:  # a non-physical fit keeps the current prior
            return
        push(snap.game, snap.track_id, snap.track_length_m, env)

    return on_snapshot, on_session


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # Dashboard-editable settings (rig, integrations, AI provider) and API keys; see settings_store.py.
        self.store = SettingsStore(settings.data_dir / "settings.json")
        self.secrets = SecretStore(settings.data_dir / "secrets.json")
        self.db = Database(settings.db_path)
        self.writer = DbWriter(self.db)
        # Who is in the seat: new sessions are tagged with the active driver (also runs the profiles migration).
        # A fresh install's first profile is named from settings.driver_name; existing drivers are never renamed.
        self.drivers = DriverService(self.db, self.writer, default_name=settings.driver_name)
        self.live = LiveState()
        # Track knowledge (layers L3 > L0b > L1c): the field worker learns the circuit from the other cars off the
        # ingest thread; the resolver publishes one TrackKnowledge to live state (snapshot "track_knowledge") and
        # the cue engine (AI-field heads-ups while the driver has no reference lap). Replays get their own pair.
        self.knowledge = TrackKnowledgeResolver(self.live.set_track_knowledge)
        self.live.knowledge = self.knowledge
        on_snapshot, on_session = knowledge_feeds(self.knowledge)
        self.field = FieldWorker(on_snapshot, on_session=on_session)
        self._replay_field: FieldWorker | None = None
        # race strategy (pitwall.strategy): one worker for live F1 input, one per replay (calls only when not max speed)
        self.strategy = StrategyWorker(self.live, self.writer)
        self._replay_strategy: StrategyWorker | None = None
        # --- race radio --- one worker for live input (every game), one per replay (calls only when not max speed)
        self.race = RaceRadioWorker(self.live)
        self._replay_race: RaceRadioWorker | None = None
        # race radio, opt-in: online names in "who's ahead?" answers (a household setting, off by default)
        self.live.race_online_names = online_names_enabled(self.store.get(RACE_RADIO_SECTION))
        self._unsubscribe_race = self.store.subscribe(
            RACE_RADIO_SECTION, lambda _s, v: setattr(self.live, "race_online_names", online_names_enabled(v))
        )
        # --- health lane: car health (pitwall.carhealth) for every game, one worker for live input and one per replay;
        # the household's call settings are swapped in by a store listener
        hs = carhealth_settings.from_stored(self.store.get(carhealth_settings.SECTION))
        self.health = CarHealthWorker(self.live, settings=hs)
        self._replay_health: CarHealthWorker | None = None
        self._unsubscribe_health = self.store.subscribe(carhealth_settings.SECTION, self._on_health_settings)
        # --- end health lane ---
        # --- spotter --- every car's Motion (F1 only) on its own thread; the radio hub attaches its sink to it
        self.spotter_settings: SpotterSettings = parse_stored(self.store.get(SPOTTER_SECTION))
        self.spotter = SpotterWorker(self.live, self.spotter_settings)
        self._replay_spotter: SpotterWorker | None = None
        self._unsubscribe_spotter = self.store.subscribe(SPOTTER_SECTION, self._on_spotter_settings)
        # --- end spotter ---
        self.processor = LapProcessor(self.db, self.writer, self.live)
        self.worker = AnalysisWorker(self.processor)
        self.motivation = MotivationWorker(self.db, self.writer, self.live)  # lane motivation: goals reached
        # --- coachref --- reference choice + practice drills; their changes run on the lap-analysis thread
        self.coachref = CoachRef(
            self.db, self.writer, self.live, self.drivers, run_task=self.worker.submit_task, processor=self.processor
        )
        self.processor.coachref = self.coachref
        # --- coachref ---
        # one-off data repairs (F1 25 one-shot laps, track models per car class), first on the analysis thread
        self.worker.submit_task(self._run_repairs)
        self.inputs: dict[int, _Input] = {}
        self.ac: _AcInput | None = None  # Assetto Corsa client (when enabled with a console IP)
        self.input_errors: dict[str, str] = {}  # integration key -> last bind/start error (Connect page)
        self.gt7_heartbeat: GT7Heartbeat | None = None
        self.replay: ReplaySource | None = None
        self._live_ingest = False
        self._lock = threading.Lock()  # replay start/stop
        self._ilock = threading.RLock()  # live inputs
        self._unsubscribe = self.store.subscribe(INTEGRATIONS_SECTION, lambda _s, _v: self._on_integrations_changed())
        # What the household plays (games.py): survives restarts and replays; the live snapshot reports it.
        self.live.set_game_selection(games.parse_selection(self.store.get(games.SECTION)))
        self._unsubscribe_game = self.store.subscribe(
            games.SECTION, lambda _s, v: self.live.set_game_selection(games.parse_selection(v))
        )
        self._seated = self.drivers.active_id
        self.drivers.subscribe(self._on_driver)
        # Setup › Controls: the F1 button probe (ingest thread, O(1)), the button test and push-to-talk that follows
        # the seated driver's F1 25 layout. Built whether or not voice is on (the app attaches the radio hub).
        self.controls = ControlsService(self.store, self.live, self.drivers, settings.voice_ptt_button)
        self.controls.senders = self._f1_senders
        self.controls.last_sender_ip = self._f1_last_ip

    def _f1_last_ip(self) -> str | None:
        """The F1 listener's last sender (ingest thread, O(1)): the controls probe tags presses from this computer."""
        for inp in list(self.inputs.values()):
            if "f1" in inp.keys:
                return inp.listener.last_ip
        return None

    def _f1_senders(self) -> list[dict[str, Any]]:
        """Who is sending to the F1 port (Setup › Controls: a loopback sender is not a console)."""
        inp = self.inputs.get(self.integration_configs()["f1"].port)
        return [dict(s) for s in inp.listener.source_snapshot()] if inp is not None else []

    def _run_repairs(self) -> None:
        try:
            self.processor.run_repairs()
        except Exception:  # a repair must never stop the service; it runs again at the next start
            log.exception("data repair failed")

    # ------------------------------------------------------------------ live UDP (all games)
    @property
    def udp(self) -> UdpListener | None:
        """The F1 listener (kept for callers written before multi-game ingest)."""
        inp = self.inputs.get(self.integration_configs()["f1"].port)
        return inp.listener if inp else None

    def integration_configs(self) -> dict[str, IntegrationConfig]:
        return resolve_configs(self.settings, self.store.get(INTEGRATIONS_SECTION))

    def start_udp(self) -> None:
        """Start listening for every enabled game. Raises if the F1 port cannot be bound (the primary input)."""
        self._live_ingest = True
        self.apply_integrations(bind_attempts=BOOT_BIND_ATTEMPTS)
        if self.udp is None:
            raise OSError(self.input_errors.get("f1", f"could not bind UDP {self.settings.f1_udp_port}"))

    def _on_integrations_changed(self) -> None:
        if self._live_ingest:
            self.apply_integrations()

    def apply_integrations(self, bind_attempts: int = APPLY_BIND_ATTEMPTS) -> None:
        """Make the running listeners match the configured integrations (idempotent; safe from any thread)."""
        with self._ilock:
            configs = self.integration_configs()
            wanted: dict[int, tuple[str, ...]] = {}
            for c in configs.values():
                if c.enabled and listens(c.key):
                    wanted[c.port] = tuple(sorted((*wanted.get(c.port, ()), c.key)))
            for port, inp in list(self.inputs.items()):
                if wanted.get(port) != inp.keys:
                    self._stop_input(inp)
                    del self.inputs[port]
            for port, keys in wanted.items():
                if port not in self.inputs:
                    self._start_input(port, keys, bind_attempts)
            self._apply_gt7_heartbeat(configs["gt7"])
            self._apply_ac(configs["ac"])

    def _known_tracks(self) -> dict[str, list[str]]:
        try:
            with self.db.read() as c:
                return {
                    "gt7": repo.derived_track_ids(c, ("gt7",)),
                    "forza": repo.derived_track_ids(c, ("forza_motorsport", "forza_horizon")),
                }
        except Exception:  # an old database must never stop ingest from starting
            log.exception("could not load known GT7/Forza tracks")
            return {}

    def _ac_known_tracks(self) -> dict[str, AcTrackGeometry]:
        try:
            with self.db.read() as c:
                return ac_known_tracks(repo.list_sessions(c, limit=AC_GEOMETRY_SCAN_SESSIONS, include_empty=True))
        except Exception:  # an old database must never stop ingest from starting
            log.exception("could not load known AC track geometry")
            return {}

    def _resume_candidate(self, source: str) -> dict[str, Any] | None:
        try:
            with self.db.read() as c:
                return repo.last_live_session(c, source)
        except Exception:
            log.exception("could not read the last session for %s", source)
            return None

    def _start_input(self, port: int, keys: tuple[str, ...], attempts: int) -> None:
        if set(keys) <= CAPTURE_ONLY:
            self._start_capture_only(port, keys, attempts)
            return
        source = f"udp:{port}"
        sessions = SessionManager(
            self.writer,
            self.live,
            self.worker,
            source=source,
            drivers=self.drivers,
            resume_candidate=self._resume_candidate(source),  # a restart mid-race continues the same session
            field=self.field if "f1" in keys else None,  # only F1 reports the whole field (one worker per runtime)
            strategy=self.strategy if "f1" in keys else None,  # race strategy (pitwall.strategy): F1 timing only
            race=self.race,  # race radio: every game
            health=self.health,  # --- health lane --- every game
            spotter=self.spotter if "f1" in keys else None,  # --- spotter --- F1 sends every car's Motion
        )
        router = PacketRouter(adapters_for(keys, self._known_tracks(), field_motion="f1" in keys), sessions, self.live)
        last_err: OSError | None = None
        listener: UdpListener | None = None
        for attempt in range(attempts):
            try:
                listener = UdpListener(
                    port,
                    router.handle,
                    bind=self.settings.udp_bind,
                    capture_dir=self.settings.capture_dir if self.settings.record_raw else None,
                    on_idle=router.finish,
                    idle_timeout_s=self.settings.session_idle_timeout_s,
                )
                break
            except OSError as e:
                last_err = e
                if attempt + 1 < attempts:
                    time.sleep(0.5)
        if listener is None:
            msg = f"could not listen on UDP {port}: {last_err}"
            log.error("%s (%s)", msg, ", ".join(SPECS[k].name for k in keys))
            for k in keys:
                self.input_errors[k] = msg
            return
        for k in keys:
            self.input_errors.pop(k, None)
        listener.start()
        self.inputs[port] = _Input(port, keys, listener, router)
        log.info("telemetry input udp:%d for %s", port, ", ".join(SPECS[k].name for k in keys))

    def _start_capture_only(self, port: int, keys: tuple[str, ...], attempts: int) -> None:
        """Record raw datagrams (UdpListener writes the .pwcap before calling the handler) without decoding."""
        last_err: OSError | None = None
        for attempt in range(attempts):
            try:
                listener = UdpListener(
                    port,
                    lambda _pkt: None,
                    bind=self.settings.udp_bind,
                    capture_dir=self.settings.capture_dir,  # recording is the whole point: always on
                    idle_timeout_s=self.settings.session_idle_timeout_s,
                )
                break
            except OSError as e:
                last_err = e
                if attempt + 1 < attempts:
                    time.sleep(0.5)
        else:
            for k in keys:
                self.input_errors[k] = f"could not listen on UDP {port}: {last_err}"
            return
        for k in keys:
            self.input_errors.pop(k, None)
        listener.start()
        self.inputs[port] = _Input(port, keys, listener, None)
        log.info("raw capture input udp:%d (no decoding)", port)

    @staticmethod
    def _stop_input(inp: _Input) -> None:
        inp.listener.stop()
        if inp.router is not None:
            inp.router.finish()
        log.info("telemetry input udp:%d stopped", inp.port)

    def _apply_gt7_heartbeat(self, cfg: IntegrationConfig) -> None:
        hb = self.gt7_heartbeat
        if not cfg.enabled or cfg.port not in self.inputs:
            if hb is not None:
                hb.stop()
                self.gt7_heartbeat = None
            return
        if hb is None:
            hb = GT7Heartbeat(cfg.console_ip, cfg.variant)
            hb.start()
            self.gt7_heartbeat = hb
            log.info("GT7 heartbeat -> %s (variant %s)", cfg.console_ip or "broadcast", cfg.variant)
        else:
            hb.set_console_ip(cfg.console_ip)
            hb.set_variant(cfg.variant)

    # ------------------------------------------------------------------ Assetto Corsa (client, no bound port)
    def _apply_ac(self, cfg: IntegrationConfig) -> None:
        """Start, retarget or stop the AC client to match the settings (caller holds ``_ilock``)."""
        cur = self.ac
        want = cfg.enabled and cfg.console_ip is not None
        if cur is not None and (not want or cur.platform != cfg.platform):
            self._stop_ac()  # disabled, IP cleared, or another platform (the adapter is built with it)
            cur = None
        if not want:
            self.input_errors.pop("ac", None)
            return
        if cur is not None:
            try:
                cur.client.set_console_ip(cfg.console_ip)  # DISMISS the old target, handshake the new one
            except ValueError as e:
                self.input_errors["ac"] = f"invalid console IP: {e}"
            else:
                self.input_errors.pop("ac", None)
            return
        self._start_ac(cfg)

    def _start_ac(self, cfg: IntegrationConfig) -> None:
        sessions = SessionManager(
            self.writer,
            self.live,
            self.worker,
            source=AC_SOURCE,
            drivers=self.drivers,
            resume_candidate=self._resume_candidate(AC_SOURCE),
            race=self.race,  # race radio (AC: off, with its reason in the view)
        )
        platform = ac_platform(cfg)
        router = PacketRouter(
            adapters_for(("ac",), ac_tracks=self._ac_known_tracks(), ac_platform=platform), sessions, self.live
        )
        try:
            client = AcRemoteClient(
                cfg.console_ip,
                router.handle,
                bind=self.settings.udp_bind,
                capture_dir=self.settings.capture_dir if self.settings.record_raw else None,
                on_idle=lambda: finish_router(router),
                idle_timeout_s=self.settings.session_idle_timeout_s,
                capture_meta_extra={"platform": platform.value},
            )
        except (OSError, ValueError) as e:
            self.input_errors["ac"] = f"could not start the Assetto Corsa client: {e}"
            log.error("%s", self.input_errors["ac"])
            return
        client.start()
        self.ac = _AcInput(client, router, cfg.platform)
        self.input_errors.pop("ac", None)
        log.info("Assetto Corsa client -> %s:%d (%s)", cfg.console_ip, client.port, platform.value)

    def _stop_ac(self) -> None:
        cur, self.ac = self.ac, None
        if cur is None:
            return
        cur.client.stop()  # sends DISMISS, closes the socket and the capture
        finish_router(cur.router)
        log.info("Assetto Corsa client stopped")

    def input_status(self) -> list[dict[str, Any]]:
        """Per integration: configuration and what is actually happening (Connect page)."""
        configs = self.integration_configs()
        out: list[dict[str, Any]] = []
        for key, cfg in configs.items():
            spec = SPECS[key]
            if not spec.listens:
                out.append(self._ac_status(cfg) if key == "ac" else {**cfg.to_dict(), "listens": False})
                continue
            inp = self.inputs.get(cfg.port) if cfg.enabled else None
            row: dict[str, Any] = {
                **cfg.to_dict(),
                "name": spec.name,
                "platforms": list(spec.platforms),
                "status": spec.status,
                "port_editable": spec.port_editable,
                "needs_console_ip": spec.needs_console_ip,
                "listening": inp is not None,
                "received": inp.listener.received if inp else 0,
                "sources": inp.listener.source_snapshot() if inp else [],
                "capture": str(inp.listener.capture.path) if inp and inp.listener.capture else None,
                "error": self.input_errors.get(key),
                "listens": True,
            }
            if inp is not None and inp.router is not None:  # a decoder: how long since it accepted a packet
                row["decoded_s_ago"] = _age_s(inp.router.last_accepted_mono)
            if key == "gt7":
                row["heartbeat"] = self.gt7_heartbeat.snapshot() if self.gt7_heartbeat else None
            out.append(row)
        return out

    def _ac_status(self, cfg: IntegrationConfig) -> dict[str, Any]:
        spec = SPECS["ac"]
        cur = self.ac if cfg.enabled else None
        client = cur.client if cur is not None else None
        snap = client.snapshot() if client is not None else None
        if snap is not None:
            snap["platform"] = cur.platform if cur is not None else None
        return {
            **cfg.to_dict(),
            "name": spec.name,
            "platforms": list(spec.platforms),
            "status": spec.status,
            "port_editable": spec.port_editable,
            "needs_console_ip": spec.needs_console_ip,
            "listens": False,  # nothing bound on this Mac: the client registers with the game
            "listening": client is not None and client.running,
            "received": client.received if client is not None else 0,
            "sources": client.source_snapshot() if client is not None else [],
            "capture": str(client.capture.path) if client is not None and client.capture else None,
            "error": self.input_errors.get("ac"),
            "client": snap,  # state, sent/received, rate, last error, last handshake (car/track)
            "decoded_s_ago": _age_s(cur.router.last_accepted_mono) if cur is not None else None,
        }

    # ------------------------------------------------------------------ replay
    def start_replay(self, path: Path, speed: float | None = 1.0, loop: bool = False) -> ReplaySource:
        with self._lock:
            self.stop_replay()
            from pitwall.ingest.capture import CaptureReader

            meta = CaptureReader(path).meta
            platform = Platform.UNKNOWN
            if meta.game_hint == AC_CAPTURE_HINT:  # AC captures carry the platform the client/probe was told
                try:
                    platform = Platform(str(meta.extra.get("platform")))
                except ValueError:
                    platform = Platform.UNKNOWN
            # A replay learns the field with its own worker and resolver, so it never rebuilds the live stream's
            # field model; it is not the UDP thread, so it waits for its worker instead of dropping samples (a
            # max-speed replay would overflow the queue). Live state follows the replay's knowledge until it ends.
            resolver = TrackKnowledgeResolver(self.live.set_track_knowledge)
            on_snapshot, on_session = knowledge_feeds(resolver)
            field = FieldWorker(on_snapshot, on_session=on_session, block_when_full=True)
            self._replay_field = field
            # race strategy (pitwall.strategy): a max-speed replay makes no radio calls (nobody is driving)
            strategy = StrategyWorker(self.live, self.writer, publish_calls=speed is not None, block_when_full=True)
            self._replay_strategy = strategy
            race = RaceRadioWorker(self.live, publish_calls=speed is not None, block_when_full=True)  # race radio
            self._replay_race = race
            # --- health lane: the same rules as strategy (no calls at max speed; waits instead of dropping)
            health = CarHealthWorker(
                self.live, settings=self.health.settings, publish_calls=speed is not None, block_when_full=True
            )
            self._replay_health = health
            # --- spotter --- the replay's own worker; its calls reach the radio only at a real-time speed
            spotter = SpotterWorker(
                self.live, self.spotter_settings, sink=self._replay_spotter_sink, publish_calls=speed is not None
            )
            self._replay_spotter = spotter
            self.live.knowledge = resolver
            sessions = SessionManager(
                self.writer,
                self.live,
                self.worker,
                source=f"replay:{path.name}",
                synthetic=meta.synthetic,
                capture_path=str(path),
                overrides={"track_name": meta.extra.get("track_name"), "scenario": meta.extra.get("scenario")},
                drivers=self.drivers,
                field=field,
                strategy=strategy,
                race=race,  # race radio
                health=health,  # --- health lane ---
                spotter=spotter,  # --- spotter ---
            )
            adapters = all_adapters(
                self._known_tracks(), ac_tracks=self._ac_known_tracks(), ac_platform=platform, field_motion=True
            )
            if meta.game_hint != AC_CAPTURE_HINT:
                # AC is detected by datagram size alone, so only AC's own captures (client, probe, synthetic writer:
                # game_hint 'ac-remote') are decoded as AC; a raw recording of another game never is.
                adapters = [a for a in adapters if a.info.game is not Game.AC]
            router = PacketRouter(adapters, sessions, self.live)

            def done() -> None:
                finish_router(router)
                field.close(drain=True)  # learn what is still queued, publish the final view
                strategy.close(timeout=30.0, drain=True)  # race strategy: finish the records and stops
                race.close(timeout=30.0, drain=True)  # race radio: the final view
                health.close(timeout=30.0, drain=True)  # --- health lane ---
                spotter.close()  # --- spotter ---
                if self.live.knowledge is resolver:
                    self.live.knowledge = self.knowledge  # learned (L3) models feed the live resolver again

            self.replay = ReplaySource(path, router.handle, speed=speed, on_done=done, loop=loop)
            self.replay.start()
            log.info("replaying %s at %s", path, "max speed" if not speed else f"{speed}x")
            return self.replay

    def stop_replay(self) -> None:
        if self.replay is not None:
            self.replay.stop()
            self.replay = None
        field, self._replay_field = self._replay_field, None
        if field is not None:
            field.close()
        strategy, self._replay_strategy = self._replay_strategy, None
        if strategy is not None:
            strategy.close()
        race, self._replay_race = self._replay_race, None  # race radio
        if race is not None:
            race.close()
        health, self._replay_health = self._replay_health, None  # --- health lane ---
        if health is not None:
            health.close()
        spotter, self._replay_spotter = self._replay_spotter, None  # --- spotter ---
        if spotter is not None:
            spotter.close()
        self.live.knowledge = self.knowledge

    def replay_status(self) -> dict[str, Any] | None:
        r = self.replay
        if r is None:
            return None
        return {
            "path": str(r.path),
            "sent": r.sent,
            "done": r.done.is_set(),
            "speed": r.speed,
            "synthetic": r.meta.synthetic,
        }

    # ------------------------------------------------------------------ shutdown
    def _on_driver(self, driver: Driver | None) -> None:
        """A new driver in the seat with a usual game (``DriverPreferences.default_game``) selects it, unless it is
        already selected or telemetry is live (whatever is being driven right now wins). Profile edits of the seated
        driver are not seat changes. Runs on the thread that changed the seat (never ingest)."""
        new_id = driver.id if driver is not None else None
        if new_id == self._seated:
            return
        self._seated = new_id
        game = driver.preferences.default_game if driver is not None else None
        sel = self.live.game_selection
        if game is None or (sel is not None and sel.id == game) or self.live.connection()["status"] == "live":
            return
        self.store.replace(games.SECTION, games.new_selection(game, "driver_default", by_driver_id=new_id).section())
        log.info("game %s selected: the usual game of driver %s", game, new_id)

    # --- health lane ---
    def _on_health_settings(self, _section: str, values: dict[str, Any]) -> None:
        s = carhealth_settings.from_stored(values)
        self.health.set_settings(s)
        replay = self._replay_health
        if replay is not None:
            replay.set_settings(s)

    # --- end health lane ---

    # --- spotter ---
    def _on_spotter_settings(self, _section: str, values: dict[str, Any]) -> None:
        """Settings > Radio & voice > Spotter changed (any thread): attribute swaps on the workers."""
        self.spotter_settings = parse_stored(values)
        self.spotter.apply_settings(self.spotter_settings)
        replay = self._replay_spotter
        if replay is not None:
            replay.apply_settings(self.spotter_settings)

    def _replay_spotter_sink(self, call: SpotterCall) -> None:
        """A real-time replay's calls go wherever the live worker's go (the radio hub attaches to that one)."""
        sink = self.spotter.sink
        if sink is not None:
            sink(call)

    # --- end spotter ---

    def close(self) -> None:
        self._unsubscribe()
        self._unsubscribe_game()
        self.controls.close()
        self._unsubscribe_race()  # race radio
        self._unsubscribe_health()  # --- health lane ---
        self._unsubscribe_spotter()  # --- spotter ---
        self.drivers.unsubscribe(self._on_driver)
        self.stop_replay()
        with self._ilock:
            self._live_ingest = False
            if self.gt7_heartbeat is not None:
                self.gt7_heartbeat.stop()
                self.gt7_heartbeat = None
            self._stop_ac()
            for inp in self.inputs.values():
                self._stop_input(inp)
            self.inputs.clear()
        self.coachref.close()  # --- coachref ---
        self.worker.join()
        self.worker.close()
        self.motivation.close()  # lane motivation
        self.field.close()
        self.strategy.close(drain=True)
        self.race.close()  # race radio
        self.health.close()  # --- health lane --- (nothing to persist)
        self.spotter.close()  # --- spotter ---
        self.writer.flush()
        self.writer.close()
