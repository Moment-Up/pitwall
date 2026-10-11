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
        self.calls.append(("install", f"{app_dir.name}|{data_dir}"))
        return 0

    def service_uninstall(self, app_dir: Path) -> int:
        self.calls.append(("uninstall", app_dir.name))
        return 0

    def service_stop(self, app_dir: Path) -> int:
        self.calls.append(("stop", app_dir.name))
        return 0

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
    assert "run /setup-pitwall" in s.text and "UDP 192.168.1.20:20777" in s.text
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


def test_windows_repoint_stops_the_old_task_first(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    old = version(home, "v0.2.0")
    new = version(home, "v0.3.0")
    managed(home, "v0.2.0", service="task")
    s = FakeSystem("win32")
    s.service = ServiceInfo("task", old, None, "task")
    s.health_fn = lambda _s: IDLE
    assert finish(opts(home, new), s) == 0, s.text
    assert s.calls == [("stop", "pitwall-v0.2.0"), ("install", f"pitwall-v0.3.0|{home / 'data'}")]
    assert "firewall.ps1" in s.text and 'cd "' in s.text and "; uv run pitwall token" in s.text


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
