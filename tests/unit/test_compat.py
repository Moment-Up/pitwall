"""Platform helpers (``pitwall.compat``): macOS keeps its exact behaviour, Windows gets its own paths, file names,
clock and UDP socket semantics. Windows branches are exercised here by patching ``sys.platform`` (pure logic) and
for real on the Windows CI runner (sockets, file replace)."""

from __future__ import annotations

import itertools
import os
import socket
import stat
import sys
import threading
import time
from pathlib import Path

import pytest

from pitwall import compat

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows socket behaviour")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file mode bits")


# ---------------------------------------------------------------------------------------------- folders
def test_app_support_dir_per_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(compat.sys, "platform", "darwin")
    assert compat.app_support_dir() == Path.home() / "Library" / "Application Support" / "pitwall"  # unchanged
    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert compat.app_support_dir() == tmp_path / "Local" / "pitwall"
    monkeypatch.delenv("LOCALAPPDATA")
    assert compat.app_support_dir() == Path.home() / "AppData" / "Local" / "pitwall"
    monkeypatch.setattr(compat.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert compat.app_support_dir() == tmp_path / "xdg" / "pitwall"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert compat.app_support_dir() == Path.home() / ".local" / "share" / "pitwall"


def test_venv_python_per_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    venv = Path("venv")
    monkeypatch.setattr(compat.sys, "platform", "darwin")
    assert compat.venv_python(venv) == venv / "bin" / "python"
    monkeypatch.setattr(compat.sys, "platform", "win32")
    assert compat.venv_python(venv) == venv / "Scripts" / "python.exe"


def test_tts_home_is_unchanged_on_macos() -> None:
    from pitwall.voice.tts import TTS_HOME

    if sys.platform == "darwin":
        assert Path.home() / "Library" / "Application Support" / "pitwall" == TTS_HOME
    else:
        assert compat.app_support_dir() == TTS_HOME


def test_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    for plat, name in (("darwin", "this Mac"), ("win32", "this PC"), ("linux", "this computer")):
        monkeypatch.setattr(compat.sys, "platform", plat)
        assert compat.this_machine() == name


# ---------------------------------------------------------------------------------------------- file names
@pytest.mark.parametrize(
    "name",
    ["20261011-120000_udp20777.pwcap", "settings.json", "synthetic-coaching-demo-2025.pwcap", "Jamie (Premium)", "é"],
)
def test_safe_filename_keeps_names_that_are_valid_everywhere(name: str) -> None:
    assert compat.safe_filename(name) == name


@pytest.mark.parametrize(
    ("name", "safe"),
    [
        ("f1:7", "f1_7"),
        ("ac:car:ks_ferrari", "ac_car_ks_ferrari"),
        ("synthetic:pitwall-park", "synthetic_pitwall-park"),
        ('a<b>c"d|e?f*g', "a_b_c_d_e_f_g"),
        ("dir/name", "dir_name"),
        ("back\\slash", "back_slash"),
        ("tab\there", "tab_here"),
        ("trailing.", "trailing_"),
        ("trailing ", "trailing_"),
        ("CON", "_CON"),
        ("nul.json", "_nul.json"),
        ("com1.pwcap", "_com1.pwcap"),
        ("LPT9", "_LPT9"),
        ("console.json", "console.json"),  # only the exact device names are reserved
        ("", "_"),
        (".", "_"),
        ("..", "__"),
    ],
)
def test_safe_filename_sanitises_windows_invalid_names(name: str, safe: str) -> None:
    assert compat.safe_filename(name) == safe
    assert compat.safe_filename(safe) == safe  # stable: sanitising twice changes nothing


# ---------------------------------------------------------------------------------------------- files
def test_replace_file_replaces_atomically(tmp_path: Path) -> None:
    src, dst = tmp_path / "new.json", tmp_path / "cur.json"
    dst.write_text("old", encoding="utf-8")
    src.write_text("new", encoding="utf-8")
    compat.replace_file(src, dst)
    assert dst.read_text(encoding="utf-8") == "new" and not src.exists()


def test_replace_file_retries_transient_sharing_violations_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src, dst = tmp_path / "new.json", tmp_path / "cur.json"
    src.write_text("new", encoding="utf-8")
    real = Path.replace
    calls: list[Path] = []

    def flaky(self: Path, target: Path) -> Path:
        calls.append(self)
        if len(calls) <= 2:
            raise PermissionError(13, "The process cannot access the file because it is being used")
        return real(self, target)

    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(Path, "replace", flaky)
    monkeypatch.setattr(compat.time, "sleep", lambda _s: None)
    compat.replace_file(src, dst)
    assert len(calls) == 3 and dst.read_text(encoding="utf-8") == "new"

    calls.clear()
    src.write_text("again", encoding="utf-8")
    monkeypatch.setattr(Path, "replace", lambda self, target: (_ for _ in ()).throw(PermissionError(13, "locked")))
    with pytest.raises(PermissionError):  # a lasting lock is reported, not swallowed
        compat.replace_file(src, dst)


def test_replace_file_does_not_retry_on_posix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "new.json"
    src.write_text("x", encoding="utf-8")
    calls: list[int] = []

    def locked(self: Path, target: Path) -> Path:
        calls.append(1)
        raise PermissionError(13, "denied")

    monkeypatch.setattr(compat.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "replace", locked)
    with pytest.raises(PermissionError):
        compat.replace_file(src, tmp_path / "cur.json")
    assert calls == [1]


@posix_only
def test_set_private_mode_on_posix(tmp_path: Path) -> None:
    p = tmp_path / "secret"
    fd = os.open(p, os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        compat.set_private_mode(fd, 0o600)
    finally:
        os.close(fd)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_set_private_mode_is_a_no_op_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object) -> None:
        raise AssertionError("os.fchmod must not be called on Windows")

    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat.os, "fchmod", boom, raising=False)  # Python 3.12 on Windows has no os.fchmod
    compat.set_private_mode(123, 0o600)


# ---------------------------------------------------------------------------------------------- clock
def test_recv_clock_is_monotonic_nanoseconds() -> None:
    expected = time.perf_counter_ns if sys.platform == "win32" else time.monotonic_ns
    assert compat.recv_clock_ns is expected
    a = compat.recv_clock_ns()
    time.sleep(0.002)
    b = compat.recv_clock_ns()
    assert 1_000_000 <= b - a < 1_000_000_000


@windows_only
def test_recv_clock_resolves_packets_closer_than_a_windows_tick() -> None:
    """60 Hz packets are 16.7 ms apart; Python 3.12's time.monotonic ticks every 15.6 ms on Windows."""
    samples = [compat.recv_clock_ns() for _ in range(2000)]
    steps = {b - a for a, b in itertools.pairwise(samples) if b != a}
    assert steps and min(steps) < 1_000_000  # sub-millisecond resolution


# ---------------------------------------------------------------------------------------------- UDP sockets
def test_is_port_unreachable() -> None:
    assert compat.is_port_unreachable(ConnectionRefusedError())
    assert compat.is_port_unreachable(ConnectionResetError())
    assert not compat.is_port_unreachable(TimeoutError())
    assert not compat.is_port_unreachable(OSError(1, "other"))
    assert not compat.is_port_unreachable(ValueError())


def test_bind_udp_exclusive_binds_and_keeps_a_second_listener_out() -> None:
    a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        compat.bind_udp_exclusive(a, ("127.0.0.1", 0))
        port = a.getsockname()[1]
        with pytest.raises(OSError):  # a second pitwall (or another app) cannot share the telemetry port
            compat.bind_udp_exclusive(b, ("127.0.0.1", port))
        if sys.platform != "win32":
            assert a.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) != 0  # POSIX: as before
    finally:
        a.close()
        b.close()


def test_bind_udp_exclusive_never_sets_reuseaddr_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    class Sock:
        def __init__(self) -> None:
            self.opts: list[tuple[int, int, int]] = []
            self.bound: tuple[str, int] | None = None

        def setsockopt(self, level: int, opt: int, value: int) -> None:
            self.opts.append((level, opt, value))

        def bind(self, address: tuple[str, int]) -> None:
            self.bound = address

    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(compat.socket, "SO_EXCLUSIVEADDRUSE", -5, raising=False)
    s = Sock()
    compat.bind_udp_exclusive(s, ("0.0.0.0", 20777))  # type: ignore[arg-type]
    assert s.bound == ("0.0.0.0", 20777)
    assert (socket.SOL_SOCKET, -5, 1) in s.opts
    assert all(opt != socket.SO_REUSEADDR for _, opt, _ in s.opts)


def test_ignore_udp_port_unreachable_is_a_no_op_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compat.sys, "platform", "darwin")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        assert compat.ignore_udp_port_unreachable(s) is False


def test_ignore_udp_port_unreachable_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compat.sys, "platform", "win32")
    assert compat.ignore_udp_port_unreachable(object()) is False  # type: ignore[arg-type]  # no fileno / no ws2_32


def _closed_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_sending_to_a_closed_port_does_not_break_receiving() -> None:
    """The heartbeat / fake-server pattern: one socket sends to a peer that is gone and keeps receiving. On Windows
    this needs SIO_UDP_CONNRESET off (else recvfrom raises WSAECONNRESET); POSIX never reports it."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as tx:
        s.bind(("127.0.0.1", 0))
        assert compat.ignore_udp_port_unreachable(s) is (sys.platform == "win32")
        s.settimeout(0.2)
        s.sendto(b"beat", ("127.0.0.1", _closed_udp_port()))
        with pytest.raises(TimeoutError):
            s.recvfrom(64)  # nothing arrived, and no error either
        tx.sendto(b"telemetry", s.getsockname())
        assert s.recvfrom(64)[0] == b"telemetry"


# ---------------------------------------------------------------------------------------------- listener / client
def test_udp_listener_survives_a_connection_reset() -> None:
    """Windows reports ICMP for datagrams a socket sent as WSAECONNRESET on recvfrom: the listener keeps going."""
    from pitwall.ingest.capture import CapturedPacket
    from pitwall.ingest.sources import UdpListener

    got: list[CapturedPacket] = []
    lst = UdpListener(0, got.append, bind="127.0.0.1")
    real = lst._sock
    events: list[object] = [ConnectionResetError(10054, "reset"), (b"pkt", ("127.0.0.1", 5000))]
    done = threading.Event()

    class FlakySock:
        def recvfrom(self, n: int) -> tuple[bytes, tuple[str, int]]:
            if events:
                ev = events.pop(0)
                if isinstance(ev, BaseException):
                    raise ev
                return ev  # type: ignore[return-value]
            done.set()
            time.sleep(0.01)
            raise TimeoutError

        def close(self) -> None:
            real.close()

    lst._sock = FlakySock()  # type: ignore[assignment]
    lst.start()
    try:
        assert done.wait(5.0)
        assert [p.data for p in got] == [b"pkt"] and lst.received == 1
        assert lst._thread.is_alive()
    finally:
        lst.stop()


def test_ac_client_treats_a_windows_connection_reset_as_refused() -> None:
    """On a connect()-ed UDP socket Windows reports ICMP port unreachable as WSAECONNRESET, POSIX as ECONNREFUSED:
    both are the console saying "no AC session here"."""
    from pitwall.ingest.ac_client import AcClientState, AcRemoteClient

    class ResetSock:
        def setsockopt(self, *_: object) -> None:
            return None

        def bind(self, _addr: object) -> None:
            return None

        def connect(self, _addr: object) -> None:
            return None

        def settimeout(self, _t: float) -> None:
            return None

        def getsockname(self) -> tuple[str, int]:
            return ("127.0.0.1", 50000)

        def send(self, data: bytes) -> int:
            return len(data)

        def recvfrom(self, _n: int) -> tuple[bytes, tuple[str, int]]:
            time.sleep(0.01)
            raise ConnectionResetError(10054, "An existing connection was forcibly closed by the remote host")

        def close(self) -> None:
            return None

    c = AcRemoteClient(
        "127.0.0.1",
        lambda _p: None,
        handshake_interval_s=0.05,
        min_handshake_interval_s=0.02,
        stream_timeout_s=0.3,
        socket_factory=ResetSock,  # type: ignore[arg-type]
    )
    c.start()
    try:
        deadline = time.monotonic() + 5.0
        while not (c.state is AcClientState.REFUSED and c.refused >= 1) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert c.state is AcClientState.REFUSED and c.refused >= 1
        assert "refused" in (c.snapshot()["last_error"] or "") and c.running
    finally:
        c.stop()


# ---------------------------------------------------------------------------------------------- Connect page text
def test_connect_guides_name_the_machine_and_probe_portably(monkeypatch: pytest.MonkeyPatch) -> None:
    from pitwall import connect
    from pitwall.config import Settings

    s = Settings(_env_file=None)
    monkeypatch.setattr(compat.sys, "platform", "darwin")
    monkeypatch.setattr(connect, "install_dir", lambda: None)  # the folder wording is tested in test_connect.py
    mac = {g.id: g for g in connect.game_guides("192.168.1.10", s)}
    assert any(st.note == "this Mac's LAN address" for st in mac["f1_25"].steps)  # unchanged on macOS
    assert connect.probe_command("192.168.1.50", "ps5").endswith("--out ~/ac-probe-ps5.pwcap")
    assert mac["ac"].extras[0].label == "Probe once, on track (Terminal on this Mac, in the pitwall folder)"

    monkeypatch.setattr(compat.sys, "platform", "win32")
    pc = {g.id: g for g in connect.game_guides("192.168.1.10", s)}
    assert any(st.note == "this PC's LAN address" for st in pc["f1_25"].steps)
    assert "this PC must be on the same network" in pc["f1_25"].notes[0]
    cmd = connect.probe_command("192.168.1.50", "ps5")
    assert cmd.endswith("--out ac-probe-ps5.pwcap") and "~" not in cmd  # Windows shells do not expand ~
    assert "PowerShell" in pc["ac"].extras[0].label


def test_lan_addresses_on_windows_are_the_default_route_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows resolves its host name to every adapter, Hyper-V/WSL/Docker vEthernet switches included (private
    172.16/12 addresses a console cannot reach, no interface names): only the default route's address is listed."""
    from pitwall import connect

    monkeypatch.setattr(compat.sys, "platform", "win32")
    monkeypatch.setattr(connect.subprocess, "run", lambda *_a, **_k: pytest.fail("no ifconfig on Windows"))
    monkeypatch.setattr(connect.socket, "getaddrinfo", lambda *_a, **_k: pytest.fail("host name not resolved"))
    monkeypatch.setattr(connect, "primary_lan_ip", lambda: "192.168.1.20")
    assert connect.lan_ipv4_addresses() == [{"interface": "", "ip": "192.168.1.20"}]
    for not_lan in (None, "100.101.102.103", "169.254.10.1", "8.8.8.8"):  # offline, Tailscale, link-local, public
        monkeypatch.setattr(connect, "primary_lan_ip", lambda ip=not_lan: ip)
        assert connect.lan_ipv4_addresses() == []


SERVE_STATUS = {
    "TCP": {"443": {"HTTPS": True}, "8443": {"HTTPS": True}, "8444": {"HTTPS": True}},
    "Web": {
        "box.example.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:18789"}}},
        "box.example.ts.net:8443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8770"}}},
        "box.example.ts.net:8444": {"Handlers": {"/": {"Proxy": "http://localhost:8795/"}}},
    },
}


def test_tailscale_serve_url_is_the_serve_that_forwards_to_this_port() -> None:
    from pitwall.connect import tailscale_serve_url

    assert tailscale_serve_url(SERVE_STATUS, 8770) == "https://box.example.ts.net:8443/"
    assert tailscale_serve_url(SERVE_STATUS, 8795) == "https://box.example.ts.net:8444/"
    assert tailscale_serve_url(SERVE_STATUS, 18789) == "https://box.example.ts.net:443/"
    assert tailscale_serve_url(SERVE_STATUS, 877) is None  # never a prefix match
    assert tailscale_serve_url({}, 8770) is None
    assert tailscale_serve_url({"Web": {"h:1": {"Handlers": {"/radio": {"Proxy": "http://127.0.0.1:1"}}}}}, 1) == (
        "https://h:1/radio/"
    )


def test_connect_page_tailscale_link_follows_serve_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Connect page links the serve that really reaches this Pitwall (another port may serve another program or
    another Pitwall); it keeps the old :8443 guess only when the serve status cannot be read."""
    from pitwall import connect

    status: dict[str, object] | None = SERVE_STATUS
    calls: list[int] = []

    def read() -> dict[str, object] | None:
        calls.append(1)
        return status

    monkeypatch.setattr(connect, "read_tailscale_serve_status", read)
    monkeypatch.setattr(connect, "_serve_cache", None)
    assert connect.tailscale_https_url(None, 8770) is None and not calls  # no Tailscale: no CLI call
    assert connect.tailscale_https_url("box.example.ts.net", 8770) == "https://box.example.ts.net:8443/"
    assert connect.tailscale_https_url("box.example.ts.net", 8795) == "https://box.example.ts.net:8444/"
    assert connect.tailscale_https_url("box.example.ts.net", 9999) is None  # served elsewhere only: no link
    assert len(calls) == 1  # cached
    status = None
    monkeypatch.setattr(connect, "_serve_cache", None)
    assert connect.tailscale_https_url("box.example.ts.net", 9999) == "https://box.example.ts.net:8443/"
