"""``pitwall install-finish``: switch an install home to a staged version folder.

Run from the NEW version's own environment by install.sh, install.ps1 and ``pitwall update`` (and by
``pitwall update --rollback`` with the previous folder). In order:

1. check the folder (``RELEASE.txt`` tag = folder name, ``.venv``, ``.pitwall-ready``) and take the lock;
2. decide the data folder: install.json (an absolute ``PITWALL_DATA_DIR`` in the carried ``.env`` that names
   another folder stops with exit 4), an absolute ``PITWALL_DATA_DIR`` in the carried ``.env`` (or in our own
   launchd plist), ``<home>/data`` holding Pitwall files, adopting the hand-installed release folder whose ``data/``
   holds sessions (the folder being updated, whatever its name, or the one ``pitwall-v*`` folder; asks first), or a
   new ``<home>/data``. Conflicts (and a ``~`` path, which the server does not expand) stop with exit 4 and change
   nothing. Going to an older version than install.json's asks first (or ``--yes``), except for a rollback;
3. refuse while someone is driving: telemetry live, or the last packet less than 2 minutes ago (a paused game)
   (exit 3; only ``install.json.staged`` is written), or wait with ``--wait-idle``;
4. back up the database with SQLite's online backup API and check the copy (``PRAGMA integrity_check``);
5. carry ``.env`` forward (byte for byte, mode 0600; a newer ``.env`` in the folder we update from replaces one an
   earlier attempt left, which is kept as ``.env.before-<date>``) and make it name exactly one absolute
   ``PITWALL_DATA_DIR``;
6. create the data folder, private to this account;
7. check again that nobody drives, then repoint our own background service (launchd agent / "Pitwall" task) to the
   new folder, or install one when asked; a service that runs from anywhere else is never touched. The service
   scripts refuse while telemetry is live (exit 3: nothing changed, the update stops with exit 3). If the new
   version itself (``GET /api/update/version`` = its tag) does not answer within 90 s, everything is put back (data
   folder, service) and install.json is left as it was; if the data folder cannot be moved back, the old service is
   not restarted and the message says where the data is (exit 4);
8. write install.json and print a summary.

Never deleted: the data folder, any ``.env``, any version folder. A Pitwall started by hand is never stopped by this
code, but on macOS starting or moving the background service runs ``scripts/pitwall-service.sh install``, which
stops every ``pitwall serve`` this account runs (from any folder, on any port) so the service can bind its ports.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pitwall.install.layout import (
    DATA_KEY,
    EXIT_ERROR,
    EXIT_LIVE,
    EXIT_NEEDS_USER,
    EXIT_OK,
    EXIT_USAGE,
    READY_MARKER,
    InstallError,
    InstallState,
    ServiceKind,
    ensure_data_dir_line,
    env_port,
    free_bytes,
    install_lock,
    is_anchored,
    load_state,
    managed_env_text,
    read_env_value,
    save_state,
    tag_of_dir,
    version_dir,
    write_private_text,
)
from pitwall.install.stage import venv_bin
from pitwall.install.versions import parse_version, release_tag, supports_managed

ServiceMode = Literal["yes", "no", "ask", "keep"]
PLIST = Path.home() / "Library" / "LaunchAgents" / "com.pitwall.server.plist"
HEALTHY_TIMEOUT_S = 90.0
STOP_TIMEOUT_S = 20.0
IDLE_POLL_S = 5.0
IDLE_CHECKS = 3
MOVE_ATTEMPTS = 5
PITWALL_FILES = ("pitwall.sqlite3", "access_token")
# A game that sent telemetry this recently counts as someone driving (paused, or between two sessions).
PAUSE_GRACE_S = 120.0


# ============================================================================================ the machine
@dataclass(frozen=True, slots=True)
class ServiceInfo:
    kind: Literal["launchd", "task"]
    working_dir: Path | None
    data_dir: Path | None  # PITWALL_DATA_DIR in the launchd plist (the Windows task reads .env instead)
    where: str  # the plist path or the task name, for messages


class System:
    """Everything install-finish does to the machine. Tests replace it with a fake."""

    platform: str = sys.platform

    def echo(self, msg: str) -> None:
        print(msg, flush=True)

    def ask(self, question: str) -> bool | None:
        """y/N from the terminal; ``None`` when there is no terminal to ask."""
        try:
            if sys.platform == "win32":
                if not sys.stdin or not sys.stdin.isatty():
                    return None
                answer = input(f"{question} [y/N] ")
            else:
                with Path("/dev/tty").open("r+", encoding="utf-8") as tty:
                    tty.write(f"{question} [y/N] ")
                    tty.flush()
                    answer = tty.readline()
        except (OSError, EOFError):
            return None
        return answer.strip().lower() in ("y", "yes")

    def has_terminal(self) -> bool:
        if sys.platform == "win32":
            return bool(sys.stdin and sys.stdin.isatty())
        try:
            with Path("/dev/tty").open("r", encoding="utf-8"):
                return True
        except OSError:
            return False

    def _get_json(self, port: int, path: str) -> dict[str, Any] | None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
                data = json.loads(r.read())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def health(self, port: int) -> dict[str, Any] | None:
        return self._get_json(port, "/api/health")

    def running_version(self, port: int) -> str | None:
        """The release tag of the Pitwall answering on ``port`` (``GET /api/update/version``, v0.2.0 and later);
        ``None`` when nothing answers or it is older (404)."""
        data = self._get_json(port, "/api/update/version")
        cur = data.get("current") if data else None
        return cur if isinstance(cur, str) else None

    def sleep(self, s: float) -> None:
        time.sleep(s)

    def monotonic(self) -> float:
        return time.monotonic()

    def free_bytes(self, path: Path) -> int:
        return free_bytes(path)

    def same_device(self, a: Path, b: Path) -> bool:
        """Both on one filesystem (a rename then moves nothing and cannot half-fail)."""
        try:
            return a.stat().st_dev == b.stat().st_dev
        except OSError:
            return False

    def lan_ip(self) -> str | None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 9))  # no packet is sent for a UDP connect
                return str(s.getsockname()[0])
        except OSError:
            return None

    def run(self, cmd: list[str], env: dict[str, str] | None = None) -> int:
        try:
            return subprocess.run(cmd, env=env, check=False).returncode
        except OSError as e:
            self.echo(f"could not run {cmd[0]}: {e}")
            return 127

    def _powershell(self, script: str) -> str | None:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    def find_service(self) -> ServiceInfo | None:
        if self.platform == "darwin":
            if not PLIST.is_file():
                return None
            import plistlib

            try:
                with PLIST.open("rb") as f:
                    data = plistlib.load(f)
            except (OSError, ValueError, plistlib.InvalidFileException):
                return ServiceInfo("launchd", None, None, str(PLIST))
            wd = data.get("WorkingDirectory")
            env = data.get("EnvironmentVariables") or {}
            dd = env.get(DATA_KEY) if isinstance(env, dict) else None
            return ServiceInfo(
                "launchd",
                Path(wd) if isinstance(wd, str) and wd else None,
                Path(dd) if isinstance(dd, str) and dd and Path(dd).is_absolute() else None,
                str(PLIST),
            )
        if self.platform == "win32":
            out = self._powershell(
                "$t = Get-ScheduledTask -TaskName Pitwall -TaskPath '\\' -ErrorAction SilentlyContinue; "
                "if ($t) { 'TASK=' + [string]$t.Actions[0].WorkingDirectory }"
            )
            if not out or not out.startswith("TASK="):
                return None
            wd = out[len("TASK=") :].strip()
            return ServiceInfo("task", Path(wd) if wd else None, None, "Task Scheduler task 'Pitwall'")
        return None

    def _ps_file(self, script: Path, *args: str) -> list[str]:
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]

    def service_install(self, app_dir: Path, data_dir: Path) -> int:
        """Exit code of the folder's own service script: 0 ok, 3 telemetry live (it changed nothing), else an error
        (the macOS script also returns 1 when the server is not up on port 8770 within 20 s, so a non-zero code is
        not proof that the new version failed: ``wait_healthy`` decides)."""
        if self.platform == "darwin":
            env = dict(os.environ, PITWALL_APP_DIR=str(app_dir), PITWALL_DATA_DIR=str(data_dir))
            return self.run([str(app_dir / "scripts" / "pitwall-service.sh"), "install"], env)
        if self.platform == "win32":
            return self.run(self._ps_file(app_dir / "scripts" / "windows" / "service.ps1", "install"))
        return EXIT_USAGE

    def service_uninstall(self, app_dir: Path) -> int:
        if self.platform == "darwin":
            return self.run([str(app_dir / "scripts" / "pitwall-service.sh"), "uninstall"])
        if self.platform == "win32":
            return self.run(self._ps_file(app_dir / "scripts" / "windows" / "service.ps1", "uninstall"))
        return EXIT_USAGE

    def service_stop(self, app_dir: Path) -> int:
        """Windows only: stop the task and the server of ``app_dir`` (its own scripts know its processes). Exit 3:
        telemetry live, nothing was stopped."""
        if self.platform == "win32":
            return self.run(self._ps_file(app_dir / "scripts" / "windows" / "service.ps1", "stop"))
        return EXIT_OK

    def make_private(self, path: Path) -> None:
        if self.platform != "win32":
            with contextlib.suppress(OSError):
                path.chmod(0o700)
            return
        # The same command as scripts/windows/install.ps1 (well-known SIDs: independent of the display language).
        sid = self._powershell("[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value")
        if not sid:
            self.echo(f"warning: could not make {path} private (no user SID); `uv run pitwall doctor` shows the fix")
            return
        code = self.run(
            [
                "icacls.exe",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",
                "*S-1-5-32-544:(OI)(CI)F",
                "/Q",
            ]
        )
        if code != 0:
            self.echo(f"warning: could not make {path} private (icacls exit code {code}); `uv run pitwall doctor`")

    def log_hint(self) -> str:
        if self.platform == "darwin":
            return str(Path.home() / "Library" / "Logs" / "pitwall" / "server.log")
        if self.platform == "win32":
            return str(Path(os.environ.get("LOCALAPPDATA", "")) / "pitwall" / "logs" / "server.log")
        return "the terminal running Pitwall"


# ============================================================================================ options
@dataclass(slots=True)
class FinishOptions:
    home: Path
    version_dir: Path
    from_dir: Path | None = None
    service: ServiceMode = "keep"
    yes: bool = False
    wait_idle_min: float = 0.0
    no_backup: bool = False
    installer: str = "pitwall update"
    rollback: bool = False  # the target is the previous folder (it may predate .pitwall-ready)
    allow_older: bool = False  # `pitwall update` already asked before going to an older version


@dataclass(slots=True)
class DataPlan:
    data_dir: Path
    source: str  # how it was chosen (for the summary)
    adopt_from: Path | None = None  # a legacy release folder whose data/ moves to data_dir
    created: bool = False  # a new, empty data folder


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _nonempty_dir(p: Path) -> bool:
    try:
        return p.is_dir() and any(p.iterdir())
    except OSError:
        return False


def _has_pitwall_files(p: Path) -> bool:
    return any((p / name).exists() for name in PITWALL_FILES)


def _same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a.absolute() == b.absolute()


def _is_release_dir(d: Path) -> bool:
    """An unzipped release (``RELEASE.txt``, no ``.git``), whatever the folder is called."""
    return d.is_dir() and (d / "RELEASE.txt").is_file() and not (d / ".git").exists()


def legacy_folders(home: Path) -> list[Path]:
    """Release folders in ``home`` installed by hand that keep sessions in their own ``data/``."""
    return [
        d for d in sorted(home.glob("pitwall-v*")) if tag_of_dir(d) and _is_release_dir(d) and _nonempty_dir(d / "data")
    ]


# ============================================================================================ the steps
class Finisher:
    def __init__(self, opts: FinishOptions, system: System) -> None:
        self.o = opts
        self.sys = system
        self.home = opts.home.expanduser().absolute()
        self.new = opts.version_dir.expanduser().absolute()
        self.tag = ""
        self.state: InstallState | None = None
        self.from_dir: Path | None = None
        self.backup: Path | None = None
        self.installed = False  # the new folder's service script ran (a rollback must uninstall it)

    def say(self, msg: str) -> None:
        self.sys.echo(msg)

    # ---------------------------------------------------------------- 1. folder
    def check_folder(self) -> None:
        tag = release_tag(self.new)
        if tag is None or self.new.name != f"pitwall-{tag}":
            raise InstallError(EXIT_USAGE, f"{self.new} is not an unzipped release folder named pitwall-<version>")
        if self.new.parent.resolve() != self.home.resolve():
            raise InstallError(EXIT_USAGE, f"{self.new} is not inside the install folder {self.home}")
        if not (self.new / ".venv").is_dir():
            raise InstallError(EXIT_USAGE, f"{self.new} has no .venv: run the installer (or uv sync) there first")
        unmarked_ok = self.o.rollback and venv_bin(self.new, "pitwall").is_file()
        if not (self.new / READY_MARKER).is_file() and not unmarked_ok:
            raise InstallError(EXIT_USAGE, f"{self.new} was not installed completely (no {READY_MARKER})")
        self.tag = tag

    # ---------------------------------------------------------------- 2. data folder
    def env_source(self) -> Path | None:
        """The ``.env`` the new folder will use: the folder we update from's when the new folder has none, or when
        it differs and was saved later (edited after an earlier attempt or a rollback); else the new folder's own."""
        own = self.new / ".env"
        prev = self.from_dir / ".env" if self.from_dir is not None else None
        if prev is not None and prev.is_file():
            if not own.is_file():
                return prev
            try:
                newer = prev.stat().st_mtime_ns > own.stat().st_mtime_ns
                if newer and prev.read_bytes() != own.read_bytes():
                    return prev
            except OSError:
                pass
        return own if own.is_file() else None

    def _release_dirs(self) -> list[Path]:
        """Folders whose own ``data/`` may hold sessions to adopt: ``pitwall-v*`` here, and the folder being
        updated (a hand-installed release may have been renamed)."""
        dirs = list(self.home.glob("pitwall-v*"))
        fd = self.from_dir
        if fd is not None and _is_release_dir(fd) and not any(_same_path(fd, d) for d in dirs):
            dirs.append(fd)
        return dirs

    def plan_data(self, svc: ServiceInfo | None, svc_ours: bool) -> DataPlan:
        home_data = self.home / "data"
        st = self.state
        src = self.env_source()
        env_dir = src.parent if src is not None else self.new
        raw = read_env_value(src, DATA_KEY) if src is not None else None
        if raw and raw.startswith("~"):
            # The server does not expand ~: it would be a folder named "~" inside the folder Pitwall starts in.
            try:
                example = str(Path(raw).expanduser())
            except RuntimeError:
                example = str(Path.home() / "pitwall-data")
            raise InstallError(
                EXIT_NEEDS_USER,
                f"{DATA_KEY} in {src} starts with ~, which Pitwall does not expand: write the full path (for example "
                f"{example}) and run this again. Nothing was changed.",
            )
        anchored: Path | None = None
        if raw and is_anchored(Path(raw)):  # absolute (or, on Windows, rooted on the current drive)
            p = Path(raw)
            anchored = p if p.is_absolute() else p.resolve()
        if st is not None and st.data_dir:
            d = Path(st.data_dir)
            if anchored is not None and not _same_path(anchored, d):
                raise InstallError(
                    EXIT_NEEDS_USER,
                    f"two data folders: {self.home / 'install.json'} says {d}, but {DATA_KEY} in {src} says "
                    f"{anchored} (a Pitwall started by hand uses that one). Make them the same: change {DATA_KEY} in "
                    f'that .env, or "data_dir" in install.json, to the folder that holds your sessions, then run this '
                    "again. Nothing was changed.",
                )
            return DataPlan(d, "install.json")
        legacy_rel: Path | None = None
        if anchored is not None:
            return DataPlan(anchored, f"{DATA_KEY} in {src}")
        if raw:
            resolved = (env_dir / raw).resolve()
            if any(_inside(resolved, d) for d in self._release_dirs()):
                legacy_rel = resolved  # data inside a version folder: adopted below
            else:
                return DataPlan(resolved, f"{DATA_KEY} in {src}")
        if (
            svc is not None
            and svc_ours
            and svc.data_dir is not None
            and not any(_inside(svc.data_dir, d) for d in self.home.glob("pitwall-v*"))
        ):
            return DataPlan(svc.data_dir, f"{DATA_KEY} of the background service")
        if home_data.is_dir() and _has_pitwall_files(home_data):
            return DataPlan(home_data, "the existing data folder")
        legacy = legacy_folders(self.home)
        fd = self.from_dir
        if (
            fd is not None
            and _is_release_dir(fd)
            and _has_pitwall_files(fd / "data")
            and not any(_same_path(fd, d) for d in legacy)
        ):
            legacy.append(fd)  # the folder being updated, renamed by hand (not pitwall-<version>)
        if legacy_rel is not None:
            legacy = [d for d in legacy if _inside(legacy_rel, d)] or legacy
        elif fd is not None and any(_same_path(fd, d) for d in legacy):
            legacy = [fd]  # the folder being updated holds the sessions in use
        if _nonempty_dir(home_data):
            raise InstallError(
                EXIT_NEEDS_USER,
                f"{home_data} holds files that are not Pitwall's: move them elsewhere (or set an absolute "
                f"{DATA_KEY} in .env) and run this again.",
            )
        if len(legacy) > 1:
            found = "\n  ".join(str(d / "data") for d in legacy)
            raise InstallError(
                EXIT_NEEDS_USER,
                "more than one Pitwall folder here holds sessions, so none is moved:\n  "
                f"{found}\nKeep the one you use: move its data folder to {home_data} by hand (Pitwall stopped), "
                "then run this again.",
            )
        if len(legacy) == 1:
            src = legacy[0] / "data"
            if not self.sys.same_device(src, self.home):
                raise InstallError(
                    EXIT_NEEDS_USER,
                    f"{src} is on another drive than {self.home}: move it to {home_data} by hand (Pitwall stopped), "
                    "then run this again.",
                )
            question = (
                f"Your sessions and settings are in {src}. Move that folder to {home_data}, where every version "
                "will use it?"
            )
            answer = True if self.o.yes else self.sys.ask(question)
            if answer is None:
                raise InstallError(
                    EXIT_NEEDS_USER,
                    f"found sessions in {src}; run this again in a terminal (to answer), or with --yes to move "
                    f"them to {home_data}",
                )
            if not answer:
                raise InstallError(
                    EXIT_NEEDS_USER, f"not moving {src}. Nothing was changed; {self.new.name} stays unpacked."
                )
            if self.from_dir is None:
                self.from_dir = legacy[0]
            return DataPlan(home_data, f"moved from {legacy[0].name}", adopt_from=src)
        return DataPlan(home_data, "new", created=not home_data.exists())

    # ---------------------------------------------------------------- 3. live
    def is_live(self, port: int) -> bool:
        h = self.sys.health(port)
        conn = h.get("connection") if h else None
        return isinstance(conn, dict) and conn.get("status") == "live"

    def is_busy(self, port: int) -> bool:
        """Someone is driving: telemetry is live, or the game sent some less than ``PAUSE_GRACE_S`` ago (a paused
        game sends nothing, so it reads as "stale"). Switching now would end or split their session."""
        h = self.sys.health(port)
        conn = h.get("connection") if h else None
        if not isinstance(conn, dict):
            return False
        if conn.get("status") == "live":
            return True
        age = conn.get("last_packet_age_s")
        return (
            conn.get("status") == "stale"
            and isinstance(age, int | float)
            and not isinstance(age, bool)
            and age < PAUSE_GRACE_S
        )

    def mark_staged(self) -> None:
        """The only change made when the switch is refused: install.json remembers the unpacked target."""
        if self.state is not None:
            self.state.staged = self.tag
            save_state(self.home, self.state)

    def require_idle(self, port: int) -> None:
        if not self.is_busy(port):
            return
        if self.o.wait_idle_min <= 0:
            self.mark_staged()
            raise InstallError(
                EXIT_LIVE,
                f"a game is sending telemetry to http://127.0.0.1:{port}/, or paused less than 2 minutes ago "
                f"(someone is driving): not switching now. {self.new.name} is unpacked and ready; run this again "
                "between sessions, or add --wait-idle 120 to wait up to 2 hours.",
            )
        self.say(f"Someone is driving: waiting up to {self.o.wait_idle_min:g} min for the session to end…")
        deadline = self.sys.monotonic() + self.o.wait_idle_min * 60
        quiet = 0
        while self.sys.monotonic() < deadline:
            if self.is_busy(port):
                quiet = 0
            else:
                quiet += 1
                if quiet >= IDLE_CHECKS:
                    return
            self.sys.sleep(IDLE_POLL_S)
        self.mark_staged()
        raise InstallError(EXIT_LIVE, f"still driving after {self.o.wait_idle_min:g} min: not switching")

    # ---------------------------------------------------------------- 4. backup
    def back_up(self, data_dir: Path) -> None:
        db = data_dir / "pitwall.sqlite3"
        if not db.is_file():
            return
        if self.o.no_backup:
            self.say("Database backup skipped (--no-backup).")
            return
        size = db.stat().st_size
        for extra in ("-wal",):
            with contextlib.suppress(OSError):
                size += (data_dir / f"pitwall.sqlite3{extra}").stat().st_size
        if self.sys.free_bytes(data_dir) < 2 * size:
            raise InstallError(
                EXIT_NEEDS_USER,
                f"not enough free space to back up the database ({size / 1e6:.1f} MB needs twice that free): "
                "free some space, or run again with --no-backup",
            )
        backups = data_dir / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        dest = backups / f"pitwall-before-{self.tag}-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
        self.say(f"Backing up the database ({size / 1e6:.1f} MB)…")
        backup_sqlite(db, dest)
        self.backup = dest
        self.say(f"Backing up the database… done: {dest} ({dest.stat().st_size / 1e6:.1f} MB)")

    # ---------------------------------------------------------------- 5. .env
    def carry_env(self, data_dir: Path) -> None:
        env = self.new / ".env"
        date = time.strftime("%Y-%m-%d")
        src = self.env_source()
        if src is None:
            write_private_text(env, managed_env_text(data_dir, date).encode("utf-8"))
            self.say("Settings: wrote a new .env")
        elif not _same_path(src, env):
            if env.exists():
                # An earlier attempt (or the version we left with --rollback) wrote this one; the folder we update
                # from has a newer .env. Keep the replaced file next to it, never delete it.
                kept = env.with_name(f".env.before-{date}")
                if kept.exists():
                    kept = env.with_name(f".env.before-{time.strftime('%Y-%m-%d-%H%M%S')}")
                write_private_text(kept, env.read_bytes())
                write_private_text(env, src.read_bytes())
                self.say(
                    f"Settings: carried the newer .env forward from {src.parent.name}; the one that was in "
                    f"{self.new.name} is kept as {kept.name}"
                )
            else:
                write_private_text(env, src.read_bytes())
                self.say(f"Settings: carried .env forward from {src.parent.name}")
        raw = env.read_bytes()
        text = raw.decode("utf-8", "surrogateescape")
        edit = ensure_data_dir_line(text, data_dir, base=self.from_dir, rewrite_relative=True, date=date)
        if edit.changed:
            write_private_text(env, edit.text.encode("utf-8", "surrogateescape"))
            self.say(f"Settings: {edit.note}")
        elif sys.platform != "win32":
            with contextlib.suppress(OSError):
                env.chmod(0o600)

    # ---------------------------------------------------------------- 7. service
    def answers_as_new(self, port: int) -> bool:
        """The NEW version answers on ``port``, not the old one still running. From v0.2.0 the server says its own
        tag (``GET /api/update/version``); an older target (a rollback into a hand-installed v0.1.x) is matched by
        ``/api/health``'s package version instead."""
        if supports_managed(self.tag):
            return self.sys.running_version(port) == self.tag
        h = self.sys.health(port)
        v = parse_version(self.tag)
        return h is not None and v is not None and h.get("version") == ".".join(str(n) for n in v.core)

    def wait_healthy(self, port: int) -> bool:
        deadline = self.sys.monotonic() + HEALTHY_TIMEOUT_S
        while self.sys.monotonic() < deadline:
            if self.answers_as_new(port):
                return True
            self.sys.sleep(1.0)
        return False

    def wait_down(self, port: int) -> bool:
        deadline = self.sys.monotonic() + STOP_TIMEOUT_S
        while self.sys.monotonic() < deadline:
            if self.sys.health(port) is None:
                return True
            self.sys.sleep(0.5)
        return False

    def refuse_live(self, port: int, what: str) -> InstallError:
        self.mark_staged()
        return InstallError(
            EXIT_LIVE,
            f"{what} refused: telemetry went live on http://127.0.0.1:{port}/ (someone is driving). Nothing was "
            f"switched; {self.new.name} is unpacked and ready: run this again between sessions.",
        )

    def start_new_service(self, port: int, data_dir: Path, *, changed: bool) -> None:
        """Run the new folder's service script and wait for the new version to answer. ``changed``: something was
        already done that must be undone (an old service stopped, data moved), so a refusal rolls back."""
        code = self.sys.service_install(self.new, data_dir)
        if code == EXIT_LIVE:
            if changed:
                raise _RollBack("the service script refused: telemetry is live")
            raise self.refuse_live(port, "the background service script")
        self.installed = True
        if code != EXIT_OK:
            self.say(f"note: the service script exited with code {code}; waiting for Pitwall {self.tag} to answer…")
        if not self.wait_healthy(port):
            raise _RollBack(f"Pitwall {self.tag} did not answer on http://127.0.0.1:{port}/ within 90 s")

    # ---------------------------------------------------------------- the whole thing
    def run(self) -> int:
        self.check_folder()
        with install_lock(self.home):
            return self._locked()

    def check_older(self, old_tag: str | None) -> None:
        """Going down a version (``install.sh --version <older>``, or a "latest" that is a later fix of an older
        line) asks first, as ``pitwall update`` does. A rollback goes back on purpose."""
        if self.o.rollback or self.o.allow_older or old_tag is None:
            return
        old, new = parse_version(old_tag), parse_version(self.tag)
        if old is None or new is None or not new < old:
            return
        if self.o.yes:
            self.say(f"{self.tag} is older than the installed {old_tag}: going back to it (--yes).")
            return
        answer = self.sys.ask(
            f"Pitwall {old_tag} is installed and {self.tag} is older. Go back to {self.tag}? The database may already "
            f"have changes from {old_tag}; older versions normally ignore them."
        )
        if answer is None:
            raise InstallError(
                EXIT_NEEDS_USER,
                f"{self.tag} is older than the installed {old_tag}: run this again in a terminal (to answer), or with "
                "--yes to go back to it. Nothing was changed.",
            )
        if not answer:
            raise InstallError(
                EXIT_NEEDS_USER, f"staying on {old_tag}. Nothing was changed; {self.new.name} stays unpacked."
            )

    def _locked(self) -> int:
        self.state = load_state(self.home)
        st = self.state
        old_tag = st.current if st is not None else None
        self.check_older(old_tag)
        if self.o.from_dir is not None:
            self.from_dir = self.o.from_dir.expanduser().absolute()
        elif old_tag is not None and old_tag != self.tag and version_dir(self.home, old_tag).is_dir():
            self.from_dir = version_dir(self.home, old_tag)
        if self.from_dir is not None and self.from_dir.resolve() == self.new.resolve():
            self.from_dir = None

        svc = self.sys.find_service()
        svc_ours = svc is not None and svc.working_dir is not None and self._ours(svc.working_dir)
        plan = self.plan_data(svc, svc_ours)
        data_dir = plan.data_dir
        if plan.adopt_from is not None and self.from_dir is None:
            self.from_dir = plan.adopt_from.parent
        port = env_port((self.from_dir or self.new) / ".env")
        udp = self._udp_port()

        # 3. live (and a hand-started server that holds the data folder we would move)
        self.require_idle(port)
        running = self.sys.health(port) is not None
        svc_at_old = svc_ours and svc is not None and svc.working_dir is not None
        if plan.adopt_from is not None and running and not svc_at_old:
            raise InstallError(
                EXIT_NEEDS_USER,
                f"Pitwall is running on http://127.0.0.1:{port}/ and its data folder is about to move: stop it "
                "(Ctrl+C in its window) and run this again.",
            )
        mode = self.o.service
        if plan.adopt_from is not None and svc_at_old and mode == "no":
            raise InstallError(
                EXIT_NEEDS_USER,
                f"the background service runs from {svc.working_dir if svc else ''} and would lose its data "
                "folder: allow the service step (leave out --no-service), or uninstall the service first.",
            )

        # 4-6. backup, .env, data folder
        self.back_up(plan.adopt_from or data_dir)
        self.carry_env(data_dir)
        if plan.adopt_from is None:
            data_dir.mkdir(parents=True, exist_ok=True)
            self.sys.make_private(data_dir)

        # 7. service. A session may have started during the backup: check again right before the switch.
        self.require_idle(port)
        service: ServiceKind = st.service if st is not None else "none"
        moved = False
        self.installed = False
        old_dir = svc.working_dir if svc is not None and svc_ours else None
        try:
            if svc is not None and not svc_ours:
                self.say(
                    f"note: a Pitwall background service ({svc.where}) runs from {svc.working_dir}, outside "
                    f"{self.home}: it was not touched."
                )
                service = "none"
                if plan.adopt_from is not None:
                    moved = self._move_data(plan.adopt_from, data_dir)
            elif svc is not None and svc_ours and mode != "no":
                self.say("Restarting the background service…")
                assert old_dir is not None
                changed = False
                if plan.adopt_from is not None:
                    code = self.sys.service_uninstall(old_dir)
                    changed = True
                    if not self.wait_down(port):
                        raise _RollBack(
                            f"the old Pitwall still answered on port {port} 20 s after its service stopped (exit code "
                            f"{code})"
                        )
                    moved = self._move_data(plan.adopt_from, data_dir)
                elif self.sys.platform == "win32" and old_dir.resolve() != self.new.resolve():
                    code = self.sys.service_stop(old_dir)
                    if code == EXIT_LIVE:
                        raise self.refuse_live(port, "stopping the old Pitwall")
                    changed = True
                    if code != EXIT_OK or not self.wait_down(port):
                        raise _RollBack(f"the old Pitwall did not stop (its service script exited with code {code})")
                self.start_new_service(port, data_dir, changed=changed)
                service = svc.kind
                self.say(f"Restarting the background service… Pitwall {self.tag} is up: http://127.0.0.1:{port}/")
            else:
                if svc is not None and svc_ours:  # mode "no"
                    self.say(
                        f"note: the background service still starts {svc.working_dir}. To move it to {self.new.name}: "
                        f'cd "{self.new}" && uv run pitwall update --service'
                    )
                if plan.adopt_from is not None:
                    moved = self._move_data(plan.adopt_from, data_dir)
                if svc is None and self.sys.platform in ("darwin", "win32"):
                    want = mode == "yes"
                    if mode == "ask":
                        ans = True if self.o.yes else self.sys.ask("Start Pitwall in the background at every login?")
                        want = bool(ans)
                    if want and running:
                        self.say(
                            f"note: a Pitwall is already running on port {port}, so no background service was "
                            f'installed. Stop it (Ctrl+C) and run: cd "{self.new}" && uv run pitwall update --service'
                        )
                    elif want:
                        self.say("Installing the background service…")
                        self.start_new_service(port, data_dir, changed=moved)
                        service = "launchd" if self.sys.platform == "darwin" else "task"
                        self.say(f"Pitwall {self.tag} is up: http://127.0.0.1:{port}/")
                    else:
                        service = "none"
                elif self.sys.platform not in ("darwin", "win32"):
                    service = "none"
        except _RollBack as rb:
            stuck = self._roll_back(plan, data_dir, moved, self.installed, old_dir, svc)
            if stuck is not None:
                raise InstallError(EXIT_NEEDS_USER, f"{rb}. {stuck} Log: {self.sys.log_hint()}") from None
            raise InstallError(
                EXIT_ERROR, f"{rb}. The previous version and its service were put back. Log: {self.sys.log_hint()}"
            ) from None
        if moved:
            self.sys.make_private(data_dir)

        # 8. install.json
        versions = set(st.versions if st is not None else [])
        versions.add(self.tag)
        if self.from_dir is not None and (t := tag_of_dir(self.from_dir)) and self.from_dir.parent == self.home:
            versions.add(t)
        previous = old_tag if old_tag is not None and old_tag != self.tag else (st.previous if st else None)
        if previous is None and self.from_dir is not None and self.from_dir.parent == self.home:
            previous = tag_of_dir(self.from_dir)
        new_state = InstallState(
            home=str(self.home),
            data_dir=str(data_dir),
            current=self.tag,
            previous=previous if previous != self.tag else None,
            staged=None,
            versions=sorted(versions),
            service=service,
            installed_by=self.o.installer,
            updated_unix=round(time.time(), 3),
        )
        save_state(self.home, new_state)
        if not self.installed and running and not (svc is not None and svc_ours and mode != "no"):
            # this code stops nothing: a server started by hand (or by a service that is not ours) keeps running
            self.say(
                f"note: a Pitwall is running on port {port}: stop it (Ctrl+C in its window, or its background "
                f"service) and start {self.tag} from {self.new}"
            )
        self.summary(new_state, plan, port, udp, first=st is None and plan.source == "new", service=service)
        return EXIT_OK

    def _ours(self, working_dir: Path) -> bool:
        """A service is ours when it runs a version folder of this home, or the folder we update from."""
        wd = working_dir.absolute()
        if wd.parent.resolve() == self.home.resolve() and tag_of_dir(wd) is not None:
            return True
        return self.from_dir is not None and wd.resolve() == self.from_dir.resolve()

    def _move_data(self, src: Path, dest: Path) -> bool:
        """Rename (same filesystem: nothing is copied). A failure rolls back: the old service comes back as it was.
        Windows refuses to rename a folder while a file in it is open, for example for a moment after the old
        server stopped, so it is tried a few times."""
        if dest.exists():
            try:
                dest.rmdir()  # an empty folder only (checked by plan_data)
            except OSError as e:
                raise _RollBack(f"{dest} is not empty: not moving {src} onto it") from e
        for attempt in range(MOVE_ATTEMPTS):
            try:
                src.rename(dest)
                break
            except OSError as e:
                if attempt == MOVE_ATTEMPTS - 1:
                    raise _RollBack(
                        f"could not move {src} to {dest} ({e.strerror or e}): close anything that uses it (a "
                        "running Pitwall, a window showing that folder) and run this again"
                    ) from e
                self.sys.sleep(1.0)
        with contextlib.suppress(OSError):
            (src.parent / "data-moved-to.txt").write_text(
                f"Pitwall moved this folder's data to {dest} on {time.strftime('%Y-%m-%d %H:%M')}.\n", encoding="utf-8"
            )
        self.say(f"Moved your data: {src} -> {dest}")
        if self.backup is not None and _inside(self.backup, src):
            self.backup = dest / self.backup.relative_to(src)
        return True

    def _roll_back(
        self,
        plan: DataPlan,
        data_dir: Path,
        moved: bool,
        installed: bool,
        old_dir: Path | None,
        svc: ServiceInfo | None,
    ) -> str | None:
        """Undo what was done. Returns ``None`` when everything is back, or a sentence for the person when the data
        folder could not be moved back (the old service is then NOT restarted: it would start on an empty folder)."""
        self.say("Putting the previous state back…")
        if installed:
            self.sys.service_uninstall(self.new)
            self.wait_down(env_port((self.from_dir or self.new) / ".env"))
        if moved and plan.adopt_from is not None:
            for attempt in range(MOVE_ATTEMPTS):  # Windows: a file may stay open for a moment after a stop
                try:
                    data_dir.rename(plan.adopt_from)
                    break
                except OSError:
                    if attempt == MOVE_ATTEMPTS - 1:
                        return (
                            f"Putting it back failed: your sessions are in {data_dir}. With Pitwall stopped, move that "
                            f"folder back to {plan.adopt_from}, or run this again (it then keeps them in {data_dir}). "
                            "The previous background service was not started again."
                        )
                    self.sys.sleep(1.0)
            with contextlib.suppress(OSError):
                (plan.adopt_from.parent / "data-moved-to.txt").unlink(missing_ok=True)
        if old_dir is not None and svc is not None:
            old_data = plan.adopt_from if moved and plan.adopt_from is not None else (svc.data_dir or data_dir)
            code = self.sys.service_install(old_dir, old_data)
            if code != EXIT_OK:
                self.say(f"note: the previous service's script exited with code {code}; check it is running")
        return None

    def _udp_port(self) -> int:
        raw = os.environ.get("PITWALL_F1_UDP_PORT") or read_env_value(
            (self.from_dir or self.new) / ".env", "PITWALL_F1_UDP_PORT"
        )
        try:
            return int(str(raw)) if raw else 20777
        except ValueError:
            return 20777

    # ---------------------------------------------------------------- 9. summary
    def summary(self, st: InstallState, plan: DataPlan, port: int, udp: int, *, first: bool, service: str) -> None:
        win = self.sys.platform == "win32"
        sep = "; " if win else " && "
        lan = self.sys.lan_ip() or "<this computer's IP address>"
        lines = [
            "",
            f"Pitwall {self.tag} is installed in {self.new}",
            f"  Dashboard on this computer:  http://127.0.0.1:{port}/",
            f'  iPad or phone link:          cd "{self.new}"{sep}uv run pitwall token',
            f"  Your data:                   {st.data_dir}",
        ]
        if self.backup is not None:
            lines.append(f"  Database backup:             {self.backup}")
        lines.append(f"  Game telemetry:              UDP {lan}:{udp}  (set this address and port in the game)")
        if service == "none":
            if self.sys.platform in ("darwin", "win32"):
                lines.append(f'  Start Pitwall:               cd "{self.new}"{sep}uv run pitwall serve')
            else:
                lines.append(f'  Start Pitwall:               cd "{self.new}" && uv run pitwall serve')
                lines.append("  (Linux has no background service script yet: start it yourself or with your own unit.)")
        else:
            lines.append(f"  Background service:          on ({service}); log: {self.sys.log_hint()}")
        if win:
            fw = self.new / "scripts" / "windows" / "firewall.ps1"
            lines.append(
                "  Let your console in (once, PowerShell as administrator): "
                f'powershell -NoProfile -ExecutionPolicy Bypass -File "{fw}" add'
            )
        if first:
            lines.append(
                f"  Next: open http://127.0.0.1:{port}/ and go to Setup › Connect to point your game at Pitwall "
                f"(in Claude Code you can also run /setup-pitwall in {self.new})"
            )
        keep = {st.current, st.previous}
        older = [
            str(d)
            for d in sorted(self.home.glob("pitwall-v*"))
            if d.is_dir() and tag_of_dir(d) not in keep and (d / "RELEASE.txt").is_file()
        ]
        if older:
            lines.append("  Older folders you can delete by hand: " + ", ".join(older))
        for line in lines:
            self.say(line)


class _RollBack(Exception):
    pass


def backup_sqlite(src: Path, dest: Path) -> None:
    """Copy a live SQLite database consistently (online backup API), then require ``integrity_check`` = ok."""
    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    s = sqlite3.connect(src, timeout=30)
    try:
        d = sqlite3.connect(part)
        try:
            s.backup(d)
            row = d.execute("PRAGMA integrity_check").fetchone()
        finally:
            d.close()
    finally:
        s.close()
    if not row or row[0] != "ok":
        part.unlink(missing_ok=True)
        raise InstallError(EXIT_ERROR, f"the database backup failed its integrity check ({row[0] if row else '?'})")
    part.replace(dest)


def finish(opts: FinishOptions, system: System | None = None, echo_errors: Callable[[str], None] | None = None) -> int:
    """Run install-finish; returns the exit code (0, 1, 2, 3, 4 or 5)."""
    s = system or System()
    try:
        return Finisher(opts, s).run()
    except InstallError as e:
        (echo_errors or s.echo)(f"error: {e.message}")
        return e.code
