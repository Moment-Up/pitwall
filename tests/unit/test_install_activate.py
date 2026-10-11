"""``pitwall install-finish`` with a fake machine: health answers, the service runner, disk and questions are
scripted; files are real (tmp_path), and so is the SQLite backup."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pitwall.install.activate import FinishOptions, ServiceInfo, System, backup_sqlite, finish
from pitwall.install.layout import InstallState, load_state, save_state

LIVE = {"connection": {"status": "live"}}
IDLE = {"connection": {"status": "stale"}}


class FakeSystem(System):
    def __init__(self, platform: str = "darwin") -> None:
        self.platform = platform
        self.lines: list[str] = []
        self.answers: list[bool | None] = []
        self.questions: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.clock = 0.0
        self.free = 500 * 10**9
        self.service: ServiceInfo | None = None
        self.health_fn: Callable[[FakeSystem], dict[str, Any] | None] = lambda s: None
        # The tag that /api/update/version answers with; default: the folder whose service was installed last,
        # while health answers (an old server still running answers health, but not as the new version).
        self.version_fn: Callable[[FakeSystem], str | None] | None = None
        self.install_codes: list[int] = []  # exit codes of service_install, in order (default 0)
        self.stop_codes: list[int] = []
        self.same_fs = True
        self.private: list[Path] = []

    def echo(self, msg: str) -> None:
        self.lines.append(msg)

    def ask(self, question: str) -> bool | None:
        self.questions.append(question)
        return self.answers.pop(0) if self.answers else None

    def has_terminal(self) -> bool:
        return False

    def health(self, port: int) -> dict[str, Any] | None:
        return self.health_fn(self)

    def running_version(self, port: int) -> str | None:
        if self.version_fn is not None:
            return self.version_fn(self)
        if self.health_fn(self) is None:
            return None
        installed = [c[1].split("|")[0] for c in self.calls if c[0] == "install"]
        return installed[-1].removeprefix("pitwall-") if installed else None

    def sleep(self, s: float) -> None:
        self.clock += s

    def monotonic(self) -> float:
        return self.clock

    def free_bytes(self, path: Path) -> int:
        return self.free

    def same_device(self, a: Path, b: Path) -> bool:
        return self.same_fs

    def lan_ip(self) -> str | None:
        return "192.168.1.20"

    def find_service(self) -> ServiceInfo | None:
        return self.service

    def service_install(self, app_dir: Path, data_dir: Path) -> int:
        code = self.install_codes.pop(0) if self.install_codes else 0
        if code != 3:  # 3: the script refused (telemetry live) and changed nothing
            self.calls.append(("install", f"{app_dir.name}|{data_dir}"))
        else:
            self.calls.append(("install-refused", app_dir.name))
        return code

    def service_uninstall(self, app_dir: Path) -> int:
        self.calls.append(("uninstall", app_dir.name))
        return 0

    def service_stop(self, app_dir: Path) -> int:
        self.calls.append(("stop", app_dir.name))
        return self.stop_codes.pop(0) if self.stop_codes else 0

    def make_private(self, path: Path) -> None:
        self.private.append(path)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def version(home: Path, tag: str, *, ready: bool = True, env: bytes | None = None, data: bool = False) -> Path:
    d = home / f"pitwall-{tag}"
    (d / ".venv" / "bin").mkdir(parents=True)
    (d / "RELEASE.txt").write_text(f"Pitwall {tag}\n", encoding="utf-8")
    if ready:
        (d / ".pitwall-ready").write_text(json.dumps({"tag": tag}), encoding="utf-8")
    if env is not None:
        (d / ".env").write_bytes(env)
    if data:
        make_db(d / "data")
    return d


def make_db(data: Path) -> Path:
    data.mkdir(parents=True, exist_ok=True)
    db = data / "pitwall.sqlite3"
    # closed explicitly: `with sqlite3.connect()` only commits, and an open file on Windows blocks moving its folder
    with contextlib.closing(sqlite3.connect(db)) as c, c:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, laps INTEGER)")
        c.executemany("INSERT INTO sessions VALUES (?, ?)", [(f"s{i}", i) for i in range(50)])
    (data / "access_token").write_text("tok", encoding="utf-8")
    return db


def opts(home: Path, new: Path, **kw: Any) -> FinishOptions:
    return FinishOptions(home=home, version_dir=new, **kw)


def managed(home: Path, current: str, **kw: Any) -> InstallState:
    st = InstallState(
        home=str(home),
        data_dir=str(home / "data"),
        current=current,
        versions=[current],
        installed_by="install.sh",
        **kw,
    )
    save_state(home, st)
    return st


# ------------------------------------------------------------------------------------------------ fresh / update
def test_fresh_install(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0")
    s = FakeSystem()
    assert finish(opts(home, new, installer="install.sh"), s) == 0, s.text
    st = load_state(home)
    assert st is not None and st.current == "v0.2.0" and st.previous is None and st.versions == ["v0.2.0"]
    assert st.data_dir == str(home / "data") and st.service == "none" and st.installed_by == "install.sh"
    assert (home / "data").is_dir() and s.private == [home / "data"]
    env = (new / ".env").read_text()
    assert env.startswith("# Written by the Pitwall installer on ") and f"PITWALL_DATA_DIR={home / 'data'}\n" in env
    if sys.platform != "win32":
        assert (new / ".env").stat().st_mode & 0o777 == 0o600
    assert "Next: open http://127.0.0.1:8770/ and go to Setup › Connect" in s.text and "/setup-pitwall" in s.text
    assert "UDP 192.168.1.20:20777" in s.text
    assert s.calls == [] and not (home / ".install.lock").exists()
    assert s.questions == []  # no service question without a terminal ("keep")


def test_update_carries_env_backs_up_and_records_previous(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    old_env = b"# mine\r\nPITWALL_HTTP_PORT=8831\r\nPITWALL_DATA_DIR=" + str(home / "data").encode() + b"\r\n"
    version(home, "v0.2.0", env=old_env)
    new = version(home, "v0.3.0")
    version(home, "v0.1.0")
    managed(home, "v0.2.0", previous="v0.1.0")
    make_db(home / "data")
    s = FakeSystem()
    assert finish(opts(home, new), s) == 0, s.text
    assert (new / ".env").read_bytes() == old_env  # byte for byte: nothing to change
    st = load_state(home)
    assert st is not None and st.current == "v0.3.0" and st.previous == "v0.2.0"
    assert set(st.versions) == {"v0.2.0", "v0.3.0"}
    (backup,) = (home / "data" / "backups").glob("pitwall-before-v0.3.0-*.sqlite3")
    with contextlib.closing(sqlite3.connect(backup)) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("SELECT count(*) FROM sessions").fetchone()[0] == 50
    assert "http://127.0.0.1:8831/" in s.text  # the port from the carried .env
    assert "Older folders you can delete by hand: " + str(home / "pitwall-v0.1.0") in s.text
    assert "setup-pitwall" not in s.text


def test_not_ready_or_misnamed_folders_are_refused(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0", ready=False)
    assert finish(opts(home, new), FakeSystem()) == 2
    other = home / "pitwall-v0.9.0"
    other.mkdir()
    (other / "RELEASE.txt").write_text("Pitwall v0.2.0\n")
    assert finish(opts(home, other), FakeSystem()) == 2
    assert load_state(home) is None


# ------------------------------------------------------------------------------------------------ live
def test_live_exits_3_and_only_marks_staged(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    version(home, "v0.2.0", env=b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"\n")
    new = version(home, "v0.3.0")
    before = managed(home, "v0.2.0")
    make_db(home / "data")
    s = FakeSystem()
    s.health_fn = lambda _s: LIVE
    assert finish(opts(home, new), s) == 3
    st = load_state(home)
    assert st is not None and st.staged == "v0.3.0" and st.current == before.current and st.versions == before.versions
    assert not (new / ".env").exists() and not (home / "data" / "backups").exists()
    assert s.calls == [] and "someone is driving" in s.text


def test_wait_idle_continues_after_three_quiet_checks(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0")
    s = FakeSystem()
    replies = [LIVE, LIVE, IDLE, LIVE, IDLE, IDLE, None]
    s.health_fn = lambda _s: replies.pop(0) if replies else None
    assert finish(opts(home, new, wait_idle_min=10), s) == 0, s.text
    assert s.clock == 5 * 5.0  # polled every 5 s until 3 quiet checks in a row (live, quiet, live, quiet x3)


def test_wait_idle_gives_up_with_3(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0")
    s = FakeSystem()
    s.health_fn = lambda _s: LIVE
    assert finish(opts(home, new, wait_idle_min=1), s) == 3
    assert s.clock >= 60


# ------------------------------------------------------------------------------------------------ adoption
def test_adopts_a_hand_installed_release(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    legacy = version(
        home, "v0.1.0", ready=False, env=b"PITWALL_DATA_DIR=data\nPITWALL_TTS_VOICE=bm_george\n", data=True
    )
    new = version(home, "v0.2.0")
    s = FakeSystem()
    assert finish(opts(home, new, yes=True), s) == 0, s.text
    assert not (legacy / "data").exists() and (home / "data" / "pitwall.sqlite3").is_file()
    assert "moved this folder's data to" in (legacy / "data-moved-to.txt").read_text()
    env = (new / ".env").read_text().splitlines()
    assert (
        env[0]
        == f"# Rewritten by the Pitwall installer on {env[0].split(' on ')[1].split(':')[0]}: this line said 'data' (relative to {legacy}); the data folder is now {home / 'data'}."
    )
    assert env[1] == f"PITWALL_DATA_DIR={home / 'data'}" and env[2] == "PITWALL_TTS_VOICE=bm_george"
    assert (legacy / ".env").read_text().startswith("PITWALL_DATA_DIR=data")  # the old folder's .env is untouched
    st = load_state(home)
    assert (
        st is not None
        and st.current == "v0.2.0"
        and st.previous == "v0.1.0"
        and set(st.versions) == {"v0.1.0", "v0.2.0"}
    )
    (backup,) = (home / "data" / "backups").glob("*.sqlite3")  # made before the move, found after it
    assert str(backup) in s.text


def test_adoption_asks_and_needs_a_terminal_or_yes(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    legacy = version(home, "v0.1.0", ready=False, data=True)
    new = version(home, "v0.2.0")
    s = FakeSystem()
    assert finish(opts(home, new), s) == 4  # no terminal, no --yes
    s = FakeSystem()
    s.answers = [False]
    assert finish(opts(home, new), s) == 4 and "Move that folder" in s.questions[0]
    assert (legacy / "data" / "pitwall.sqlite3").is_file() and not (home / "data").exists()
    assert load_state(home) is None and not (new / ".env").exists()
    s = FakeSystem()
    s.answers = [True]
    assert finish(opts(home, new), s) == 0, s.text


@pytest.mark.parametrize("case", ["other files in data", "two legacy folders", "other filesystem", "running by hand"])
def test_adoption_refusals_change_nothing(tmp_path: Path, case: str) -> None:
    home = tmp_path / "Pitwall"
    legacy = version(home, "v0.1.0", ready=False, data=True)
    new = version(home, "v0.2.0")
    s = FakeSystem()
    if case == "other files in data":
        (home / "data").mkdir()
        (home / "data" / "holiday.jpg").write_bytes(b"x")
    elif case == "two legacy folders":
        version(home, "v0.1.1", ready=False, data=True)
    elif case == "other filesystem":
        s.same_fs = False
    else:
        s.health_fn = lambda _s: IDLE  # a Pitwall answers, and no service runs it
    assert finish(opts(home, new, yes=True), s) == 4, s.text
    assert (legacy / "data" / "pitwall.sqlite3").is_file()
    assert load_state(home) is None and not (new / ".env").exists() and s.calls == []


# ------------------------------------------------------------------------------------------------ services
def test_a_foreign_service_is_never_touched(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0")
    s = FakeSystem()
    s.service = ServiceInfo(
        "launchd", tmp_path / "Projects" / "pitwall-release", tmp_path / "Projects" / "data", "plist"
    )
    s.health_fn = lambda _s: IDLE
    assert finish(opts(home, new, service="yes", yes=True), s) == 0, s.text
    assert s.calls == [] and "was not touched" in s.text
    st = load_state(home)
    assert st is not None and st.service == "none" and st.data_dir == str(home / "data")  # not the foreign data


def test_our_service_is_repointed(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0", env=b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"\n")
    new = version(home, "v0.3.0")
    managed(home, "v0.2.0", service="launchd")
    s = FakeSystem()
    s.service = ServiceInfo("launchd", old, home / "data", "plist")
    s.health_fn = lambda _s: IDLE
    assert finish(opts(home, new), s) == 0, s.text
    assert s.calls == [("install", f"pitwall-v0.3.0|{home / 'data'}")]
    st = load_state(home)
    assert st is not None and st.service == "launchd" and st.current == "v0.3.0"


def _down_after_stop(fs: FakeSystem) -> dict[str, Any] | None:
    """A server that answers until its service is stopped or uninstalled, and again once one is installed."""
    last = fs.calls[-1][0] if fs.calls else None
    return None if last in ("stop", "uninstall") else IDLE


def test_windows_repoint_stops_the_old_task_first(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0")
    new = version(home, "v0.3.0")
    managed(home, "v0.2.0", service="task")
    s = FakeSystem("win32")
    s.service = ServiceInfo("task", old, None, "task")
    s.health_fn = _down_after_stop
    assert finish(opts(home, new), s) == 0, s.text
    assert s.calls == [("stop", "pitwall-v0.2.0"), ("install", f"pitwall-v0.3.0|{home / 'data'}")]
    assert "firewall.ps1" in s.text and 'cd "' in s.text and "; uv run pitwall token" in s.text


@pytest.mark.parametrize("case", ["refused while live", "still answering", "script failed"])
def test_windows_old_task_that_does_not_stop(tmp_path: Path, case: str) -> None:
    """service.ps1 stop exits 3 while live (nothing stopped: exit 3, only staged); an old server that still answers
    after the stop, or a stop that failed, puts the old task back instead of starting a second server."""
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0")
    new = version(home, "v0.3.0")
    before = managed(home, "v0.2.0", service="task")
    s = FakeSystem("win32")
    s.service = ServiceInfo("task", old, None, "task")
    s.health_fn = _down_after_stop if case == "script failed" else (lambda _s: IDLE)
    s.stop_codes = [3] if case == "refused while live" else [1] if case == "script failed" else [0]
    code = finish(opts(home, new), s)
    st = load_state(home)
    assert st is not None and st.current == "v0.2.0" and st.versions == before.versions
    if case == "refused while live":
        assert code == 3 and s.calls == [("stop", "pitwall-v0.2.0")] and st.staged == "v0.3.0", s.text
    else:
        assert code == 1 and "did not stop" in s.text and "put back" in s.text, s.text
        assert s.calls == [("stop", "pitwall-v0.2.0"), ("install", f"pitwall-v0.2.0|{home / 'data'}")]


def test_failed_health_rolls_back(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0")
    new = version(home, "v0.3.0")
    before = managed(home, "v0.2.0", service="launchd")
    s = FakeSystem()
    s.service = ServiceInfo("launchd", old, home / "data", "plist")
    state = {"installed": False}

    def health(fs: FakeSystem) -> dict[str, Any] | None:
        # the old server answers until the new service is installed; the new one never does
        installed = any(c[0] == "install" and c[1].startswith("pitwall-v0.3.0") for c in fs.calls)
        state["installed"] = installed
        return None if installed else IDLE

    s.health_fn = health
    assert finish(opts(home, new), s) == 1
    assert s.calls == [
        ("install", f"pitwall-v0.3.0|{home / 'data'}"),
        ("uninstall", "pitwall-v0.3.0"),
        ("install", f"pitwall-v0.2.0|{home / 'data'}"),
    ]
    assert load_state(home) == before  # install.json unchanged
    assert "put back" in s.text and "server.log" in s.text


def test_adoption_with_our_service_moves_data_between_uninstall_and_install(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    legacy = version(home, "v0.1.0", ready=False, data=True)
    new = version(home, "v0.2.0")
    s = FakeSystem()
    s.service = ServiceInfo("launchd", legacy, legacy / "data", "plist")
    up = {"v": True}

    def health(fs: FakeSystem) -> dict[str, Any] | None:
        if fs.calls and fs.calls[-1][0] == "uninstall":
            up["v"] = False
        if fs.calls and fs.calls[-1][0] == "install":
            up["v"] = True
        return IDLE if up["v"] else None

    s.health_fn = health
    assert finish(opts(home, new, yes=True), s) == 0, s.text
    assert s.calls == [("uninstall", "pitwall-v0.1.0"), ("install", f"pitwall-v0.2.0|{home / 'data'}")]
    assert (home / "data" / "pitwall.sqlite3").is_file() and not (legacy / "data").exists()


def test_a_data_folder_that_cannot_move_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows refuses to rename a folder with an open file in it: after a few tries the old service comes back
    with its data where it was, and install.json is not written."""
    home = tmp_path / "Pitwall"
    legacy = version(home, "v0.1.0", ready=False, data=True)
    new = version(home, "v0.2.0")
    s = FakeSystem()
    s.service = ServiceInfo("launchd", legacy, legacy / "data", "plist")
    up = {"v": True}

    def health(fs: FakeSystem) -> dict[str, Any] | None:
        if fs.calls:
            up["v"] = fs.calls[-1][0] == "install"
        return IDLE if up["v"] else None

    def refuse(self: Path, target: Any) -> Path:
        raise PermissionError(13, "Access is denied", str(self))

    s.health_fn = health
    monkeypatch.setattr(Path, "rename", refuse)
    assert finish(opts(home, new, yes=True), s) == 1, s.text
    assert s.calls == [("uninstall", "pitwall-v0.1.0"), ("install", f"pitwall-v0.1.0|{legacy / 'data'}")]
    assert "could not move" in s.text and "put back" in s.text
    assert (legacy / "data" / "pitwall.sqlite3").is_file() and not (home / "data").exists()
    assert load_state(home) is None


def test_service_question_and_a_running_server(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0")
    s = FakeSystem()
    s.answers = [True]
    s.health_fn = lambda fs: IDLE if fs.calls else None
    assert finish(opts(home, new, service="ask"), s) == 0, s.text
    assert s.calls == [("install", f"pitwall-v0.2.0|{home / 'data'}")]
    st = load_state(home)
    assert st is not None and st.service == "launchd"
    # a server started by hand is never killed: no service is installed while it runs
    home2 = tmp_path / "P2"
    new2 = version(home2, "v0.2.0")
    s2 = FakeSystem()
    s2.health_fn = lambda _s: IDLE
    assert finish(opts(home2, new2, service="yes"), s2) == 0
    assert s2.calls == [] and "already running" in s2.text


def test_linux_has_no_service(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0")
    s = FakeSystem("linux")
    assert finish(opts(home, new, service="yes"), s) == 0
    assert s.calls == [] and "Linux has no background service" in s.text


# ------------------------------------------------------------------------------------------------ backup, disk
def test_low_disk_for_the_backup_exits_4_and_no_backup_skips_it(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0")
    managed(home, "v0.1.0")
    make_db(home / "data")
    s = FakeSystem()
    s.free = 10
    assert finish(opts(home, new), s) == 4 and "--no-backup" in s.text
    st = load_state(home)
    assert st is not None and st.current == "v0.1.0"
    assert finish(opts(home, new, no_backup=True), s) == 0
    assert not (home / "data" / "backups").exists()


def test_backup_sqlite_is_consistent_while_open(tmp_path: Path) -> None:
    db = make_db(tmp_path / "data")
    writer = sqlite3.connect(db)
    writer.execute("INSERT INTO sessions VALUES ('late', 99)")
    writer.commit()  # in the WAL, not yet checkpointed
    dest = tmp_path / "b.sqlite3"
    backup_sqlite(db, dest)
    writer.close()
    with contextlib.closing(sqlite3.connect(dest)) as c:
        assert c.execute("SELECT count(*) FROM sessions").fetchone()[0] == 51
    assert not (tmp_path / "b.sqlite3.part").exists()


def test_rollback_option_accepts_an_unmarked_old_folder(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    current = version(home, "v0.2.0")
    old = version(home, "v0.1.0", ready=False)
    (old / ".venv" / "bin" / "pitwall").write_text("")
    (old / ".venv" / "Scripts").mkdir()
    (old / ".venv" / "Scripts" / "pitwall.exe").write_text("")
    managed(home, "v0.2.0", previous="v0.1.0")
    s = FakeSystem()
    assert finish(opts(home, old, from_dir=current, rollback=True), s) == 0, s.text
    st = load_state(home)
    assert st is not None and st.current == "v0.1.0" and st.previous == "v0.2.0"


# ------------------------------------------------------------------------------------------------ review fixes
def test_a_service_script_that_refuses_switches_nothing(tmp_path: Path) -> None:
    """pitwall-service.sh / service.ps1 exit 3 and change nothing when telemetry went live after the first check:
    install-finish exits 3 too (only staged), never claims the new version is up."""
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0", env=b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"\n")
    make_db(home / "data")
    before = managed(home, "v0.2.0", service="launchd")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    s.service = ServiceInfo("launchd", old, home / "data", "plist")
    s.health_fn = lambda _s: IDLE
    s.install_codes = [3]
    assert finish(opts(home, new), s) == 3, s.text
    st = load_state(home)
    assert st is not None and st.current == "v0.2.0" and st.service == "launchd" and st.staged == "v0.3.0"
    assert st.versions == before.versions and " is up" not in s.text and "someone is driving" in s.text
    assert s.calls == [("install-refused", "pitwall-v0.3.0")]


def test_the_old_server_still_answering_is_not_success(tmp_path: Path) -> None:
    """Only the new version's own tag counts: an old server that keeps answering /api/health is a failure, rolled
    back, and install.json stays as it was."""
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0", env=b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"\n")
    before = managed(home, "v0.2.0", service="launchd")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    s.service = ServiceInfo("launchd", old, home / "data", "plist")
    s.health_fn = lambda _s: IDLE
    s.version_fn = lambda _s: "v0.2.0"  # the old one answers, whatever the script said
    s.install_codes = [1]
    assert finish(opts(home, new), s) == 1, s.text
    assert "exited with code 1" in s.text and "did not answer" in s.text and "put back" in s.text
    assert s.calls == [
        ("install", f"pitwall-v0.3.0|{home / 'data'}"),
        ("uninstall", "pitwall-v0.3.0"),
        ("install", f"pitwall-v0.2.0|{home / 'data'}"),
    ]
    assert load_state(home) == before


def test_a_slow_script_is_fine_when_the_new_version_answers(tmp_path: Path) -> None:
    """The macOS script returns 1 when the server is not up on 8770 within 20 s; the new version answering on
    its own port within 90 s is what counts."""
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0", env=b"PITWALL_HTTP_PORT=8833\nPITWALL_DATA_DIR=" + str(home / "data").encode())
    managed(home, "v0.2.0", service="launchd")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    s.service = ServiceInfo("launchd", old, home / "data", "plist")
    s.health_fn = lambda _s: IDLE
    s.install_codes = [1]
    assert finish(opts(home, new), s) == 0, s.text
    st = load_state(home)
    assert st is not None and st.current == "v0.3.0" and "Pitwall v0.3.0 is up: http://127.0.0.1:8833/" in s.text


def test_driving_again_before_the_switch_stops_it(tmp_path: Path) -> None:
    """A session that starts during the backup: the check right before the service step refuses (exit 3)."""
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0", env=b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"\n")
    make_db(home / "data")
    managed(home, "v0.2.0", service="launchd")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    s.service = ServiceInfo("launchd", old, home / "data", "plist")
    s.health_fn = lambda _s: LIVE if (new / ".env").exists() else IDLE  # live from the moment .env is carried
    assert finish(opts(home, new), s) == 3, s.text
    st = load_state(home)
    assert st is not None and st.current == "v0.2.0" and st.staged == "v0.3.0" and s.calls == []


@pytest.mark.parametrize(("age", "code"), [(30.0, 3), (119.0, 3), (130.0, 0)])
def test_a_paused_game_counts_as_driving(tmp_path: Path, age: float, code: int) -> None:
    """No packet for 2 s reads "stale" (a paused game sends nothing): under 2 minutes it still counts as driving."""
    home = tmp_path / "Pitwall"
    new = version(home, "v0.2.0")
    s = FakeSystem()
    s.health_fn = lambda _s: {"connection": {"status": "stale", "last_packet_age_s": age}}
    assert finish(opts(home, new), s) == code, s.text
    if code == 3:
        assert "paused less than 2 minutes ago" in s.text and "--wait-idle 120 to wait up to 2 hours" in s.text


def test_a_failed_move_back_does_not_restart_the_old_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The new version never answers, and moving the data back fails every time (a file held open on Windows): the
    old service is not started on an empty folder, and the message says where the sessions are (exit 4)."""
    home = tmp_path / "Pitwall"
    legacy = version(home, "v0.1.5", ready=False, data=True)
    new = version(home, "v0.3.0")
    s = FakeSystem("win32")
    s.service = ServiceInfo("task", legacy, None, "task")
    s.health_fn = _down_after_stop
    s.version_fn = lambda _s: None  # the new version never answers
    real_rename = Path.rename

    def rename(self: Path, target: Any) -> Path:
        if Path(target) == legacy / "data":
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    assert finish(opts(home, new, yes=True), s) == 4, s.text
    assert s.calls == [
        ("uninstall", "pitwall-v0.1.5"),
        ("install", f"pitwall-v0.3.0|{home / 'data'}"),
        ("uninstall", "pitwall-v0.3.0"),
    ]  # no ("install", "pitwall-v0.1.5|...")
    assert f"your sessions are in {home / 'data'}" in s.text and str(legacy / "data") in s.text
    assert "were put back" not in s.text and (home / "data" / "pitwall.sqlite3").is_file()
    assert load_state(home) is None


def test_a_failed_move_back_is_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "Pitwall"
    legacy = version(home, "v0.1.5", ready=False, data=True)
    new = version(home, "v0.3.0")
    s = FakeSystem("win32")
    s.service = ServiceInfo("task", legacy, None, "task")
    s.health_fn = _down_after_stop
    s.version_fn = lambda _s: None
    real_rename = Path.rename
    refusals = [1, 1]

    def rename(self: Path, target: Any) -> Path:
        if Path(target) == legacy / "data" and refusals:
            refusals.pop()
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", rename)
    assert finish(opts(home, new, yes=True), s) == 1, s.text
    assert (legacy / "data" / "pitwall.sqlite3").is_file() and "were put back" in s.text
    assert s.calls[-1] == ("install", f"pitwall-v0.1.5|{legacy / 'data'}")


def test_pitwall_update_keeps_no_service_as_no_service(tmp_path: Path) -> None:
    """`pitwall update --yes` without --service ("keep"): nobody who never had a login service gets one."""
    from pitwall.install.commands import _service_mode

    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0", env=b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"\n")
    managed(home, "v0.2.0", service="none")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    assert finish(opts(home, new, from_dir=old, service=_service_mode(None), yes=True), s) == 0, s.text
    st = load_state(home)
    assert st is not None and st.service == "none" and s.calls == [] and s.questions == []
    assert _service_mode(True) == "yes" and _service_mode(False) == "no"


def test_a_renamed_hand_installed_release_keeps_its_sessions(tmp_path: Path) -> None:
    """A release folder renamed by hand (not pitwall-<version>) whose data/ holds sessions: its data is adopted
    (asked first) instead of starting from an empty data folder."""
    home = tmp_path / "Downloads"
    old = home / "Pitwall"
    (old / ".venv" / "bin").mkdir(parents=True)
    (old / "RELEASE.txt").write_text("Pitwall v0.2.0\n", encoding="utf-8")
    (old / ".env").write_text("PITWALL_LLM_ENABLED=false\n", encoding="utf-8")
    make_db(old / "data")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    assert finish(opts(home, new, from_dir=old, service="no"), s) == 4  # no terminal, no --yes: asks first
    assert (old / "data" / "pitwall.sqlite3").is_file() and load_state(home) is None
    s = FakeSystem()
    assert finish(opts(home, new, from_dir=old, service="no", yes=True), s) == 0, s.text
    st = load_state(home)
    assert st is not None and st.data_dir == str(home / "data") and (home / "data" / "pitwall.sqlite3").is_file()
    assert not (old / "data").exists() and (old / "data-moved-to.txt").is_file()
    assert "PITWALL_LLM_ENABLED=false" in (new / ".env").read_text()


def test_a_renamed_folder_with_a_relative_data_dir(tmp_path: Path) -> None:
    home = tmp_path / "Downloads"
    old = home / "my-pitwall"
    (old / ".venv" / "bin").mkdir(parents=True)
    (old / "RELEASE.txt").write_text("Pitwall v0.2.0\n", encoding="utf-8")
    (old / ".env").write_text("PITWALL_DATA_DIR=data\n", encoding="utf-8")
    make_db(old / "data")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    assert finish(opts(home, new, from_dir=old, service="no", yes=True), s) == 0, s.text
    assert (home / "data" / "pitwall.sqlite3").is_file()
    assert f"PITWALL_DATA_DIR={home / 'data'}" in (new / ".env").read_text()


@pytest.mark.parametrize("value", ["~/racing", "~"])
def test_a_tilde_data_dir_stops_and_changes_nothing(tmp_path: Path, value: str) -> None:
    """The server does not expand ~ (it would be a folder named "~" where Pitwall starts): ask for the full path."""
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0", env=f"PITWALL_DATA_DIR={value}\n".encode())
    managed(home, "v0.2.0")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    assert finish(opts(home, new, from_dir=old), s) == 4
    assert "starts with ~" in s.text and "write the full path" in s.text
    assert not (new / ".env").exists() and load_state(home) is not None and s.calls == []


def test_install_json_and_env_naming_different_data_folders_stop(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    other = tmp_path / "elsewhere"
    make_db(other)
    version(home, "v0.2.0", env=b"PITWALL_DATA_DIR=" + str(other).encode() + b"\n")
    before = managed(home, "v0.2.0")
    new = version(home, "v0.3.0")
    s = FakeSystem()
    assert finish(opts(home, new, service="no"), s) == 4
    assert "two data folders" in s.text and str(other) in s.text and str(home / "data") in s.text
    assert load_state(home) == before and not (new / ".env").exists() and not (other / "backups").exists()
    # the same folder written differently (a trailing slash) is not a conflict
    version(home, "v0.2.1", env=b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"/\n")
    assert finish(opts(home, new, from_dir=home / "pitwall-v0.2.1", service="no"), FakeSystem()) == 0


def test_a_newer_env_replaces_one_from_an_earlier_attempt(tmp_path: Path) -> None:
    """After a rolled-back attempt (or --rollback), edits made in the older folder's .env reach the new folder;
    the file that was there is kept as .env.before-<date>, never deleted."""
    import os

    home = tmp_path / "Pitwall"
    line = b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"\n"
    old = version(home, "v0.2.0", env=line)
    managed(home, "v0.2.0")
    new = version(home, "v0.3.0", env=line + b"# from the earlier attempt\n")
    os.utime(new / ".env", ns=(1_000_000_000_000, 1_000_000_000_000))
    (old / ".env").write_bytes(line + b"PITWALL_HTTP_PORT=8771\n")  # edited since
    s = FakeSystem()
    assert finish(opts(home, new, from_dir=old, service="no"), s) == 0, s.text
    assert (new / ".env").read_bytes() == line + b"PITWALL_HTTP_PORT=8771\n"
    (kept,) = new.glob(".env.before-*")
    assert kept.read_bytes() == line + b"# from the earlier attempt\n" and "is kept as .env.before-" in s.text
    # an older .env in the folder we leave does not overwrite the new folder's
    os.utime(old / ".env", ns=(1_000_000_000_000, 1_000_000_000_000))
    (new / ".env").write_bytes(line + b"PITWALL_HTTP_PORT=8772\n")
    assert finish(opts(home, new, from_dir=old, service="no"), FakeSystem()) == 0
    assert b"8772" in (new / ".env").read_bytes()


def test_going_to_an_older_version_asks_first(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    version(home, "v0.3.0", env=b"PITWALL_DATA_DIR=" + str(home / "data").encode() + b"\n")
    before = managed(home, "v0.3.0")
    older = version(home, "v0.2.5")
    s = FakeSystem()
    assert finish(opts(home, older, installer="install.sh"), s) == 4  # no terminal: asks for --yes
    assert "older than the installed v0.3.0" in s.text and load_state(home) == before
    s = FakeSystem()
    s.answers = [False]
    assert finish(opts(home, older), s) == 4 and "Go back to v0.2.5?" in s.questions[0]
    assert load_state(home) == before
    s = FakeSystem()
    s.answers = [True]
    assert finish(opts(home, older), s) == 0, s.text
    st = load_state(home)
    assert st is not None and st.current == "v0.2.5" and st.previous == "v0.3.0"
    # --yes, `pitwall update`'s own confirmation (--allow-older) and --rollback do not ask
    for kw in ({"yes": True}, {"allow_older": True}, {"rollback": True}):
        managed(home, "v0.3.0")
        s = FakeSystem()
        assert finish(opts(home, older, **kw), s) == 0, (kw, s.text)
        assert s.questions == []
