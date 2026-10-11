"""Platform differences in one place.

macOS is the reference platform: there, every helper below does exactly what the code did before Windows support
existed (same paths, same clock, same socket options, same file modes). Windows support is additive and guarded by
``sys.platform``; other POSIX systems (Linux) follow the macOS behaviour except for the per-user data folder.

- ``app_support_dir`` / ``venv_python``: per-user folders for pitwall's own tools (TTS worker venv, model caches):
  ``~/Library/Application Support/pitwall`` on macOS, ``%LOCALAPPDATA%\\pitwall`` on Windows, the XDG data home
  elsewhere.
- ``recv_clock_ns``: the monotonic clock for packet receive timestamps. Python 3.12's ``time.monotonic`` ticks
  every 15.6 ms on Windows (GetTickCount64) - coarser than the 16.7 ms between 60 Hz telemetry packets, and Assetto
  Corsa's session clock *is* the receive clock - so Windows uses ``time.perf_counter_ns`` (QueryPerformanceCounter).
  On macOS both read the same clock; ``time.monotonic_ns`` is kept there.
- ``safe_filename``: a file name derived from an id or a user value that is valid on Windows too (today only the
  Assetto Corsa probe's ``ac-probe-<platform>.pwcap``; names already valid everywhere are returned unchanged).
- ``replace_file`` / ``set_private_mode``: atomic replace that survives Windows' transient sharing violations
  (antivirus and indexers briefly open new files); POSIX mode 0600 where the OS has mode bits. Windows has none:
  a file there is only as private as its folder's ACL, which ``scripts/windows/install.ps1`` makes private for the
  data folder (``pitwall doctor`` warns when other accounts can read it).
- ``bind_udp_exclusive`` / ``ignore_udp_port_unreachable`` / ``PORT_UNREACHABLE``: UDP socket options whose meaning
  differs on Windows (``SO_REUSEADDR`` would let a second process steal the telemetry port there; ICMP "port
  unreachable" surfaces as ``WSAECONNRESET`` on the next receive instead of ``ECONNREFUSED``).
- ``this_machine``: "this Mac" / "this PC" for user-facing text.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import re
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "pitwall"

__all__ = [
    "APP_NAME",
    "PORT_UNREACHABLE",
    "app_support_dir",
    "bind_udp_exclusive",
    "ignore_udp_port_unreachable",
    "is_macos",
    "is_port_unreachable",
    "is_windows",
    "recv_clock_ns",
    "replace_file",
    "safe_filename",
    "set_private_mode",
    "this_machine",
    "venv_python",
]


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def this_machine() -> str:
    """How user-facing text names the computer pitwall runs on."""
    if sys.platform == "darwin":
        return "this Mac"
    if sys.platform == "win32":
        return "this PC"
    return "this computer"


# ------------------------------------------------------------------------------------------------ folders
def app_support_dir() -> Path:
    """Per-user folder for pitwall's own tools and caches (not the telemetry data directory, ``Settings.data_dir``).

    macOS ``~/Library/Application Support/pitwall`` (unchanged), Windows ``%LOCALAPPDATA%\\pitwall`` (the
    profile's default ACL keeps it private to the user), elsewhere ``$XDG_DATA_HOME/pitwall`` (default
    ``~/.local/share/pitwall``).
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else Path.home() / "AppData" / "Local") / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_NAME


def venv_python(venv: Path) -> Path:
    """The interpreter of a virtual environment: ``Scripts\\python.exe`` on Windows, ``bin/python`` elsewhere."""
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


# ------------------------------------------------------------------------------------------------ clock
# Chosen once at import: every receive timestamp of a run (and of the captures it writes) comes from one clock.
recv_clock_ns: Callable[[], int] = time.perf_counter_ns if sys.platform == "win32" else time.monotonic_ns


# ------------------------------------------------------------------------------------------------ file names
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')  # Windows' list; "/" and NUL are invalid everywhere
_RESERVED_STEMS = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)


def safe_filename(name: str, replacement: str = "_") -> str:
    """``name`` as one file-name component that is valid on Windows, macOS and Linux - the same on every platform,
    so a data folder can move between machines.

    A name that is already valid everywhere is returned unchanged (files written before keep their names).
    Otherwise each invalid character (``<>:"/\\|?*`` and control characters) becomes ``replacement``, trailing
    dots/spaces (Windows strips them silently) are replaced, and a reserved device name (``CON``, ``NUL``,
    ``COM1``... with any extension) gets ``replacement`` in front. Never returns ``""``, ``"."`` or ``".."``.
    """
    out = _INVALID_CHARS.sub(replacement, name)
    stripped = out.rstrip(" .")
    if stripped != out:
        out = stripped + replacement * (len(out) - len(stripped))
    if out.split(".", 1)[0].rstrip(" ").upper() in _RESERVED_STEMS:
        out = replacement + out
    if out in ("", ".", ".."):
        out = replacement * max(1, len(out))
    return out


# ------------------------------------------------------------------------------------------------ files
_REPLACE_RETRY_S = (0.01, 0.03, 0.06, 0.1, 0.2, 0.4)  # ~0.8 s in all: longer than any scanner's peek


def replace_file(src: Path, dst: Path) -> None:
    """``src.replace(dst)`` (atomic rename over an existing file).

    On Windows the rename fails with a sharing violation while another process has ``dst`` (or ``src``) open
    without delete sharing - typically Defender or the search indexer looking at a file that was just written.
    Those are transient, so the rename is retried for up to ~0.8 s before the error is raised.
    """
    if sys.platform != "win32":
        src.replace(dst)
        return
    for delay in (*_REPLACE_RETRY_S, None):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)


def set_private_mode(fd: int, mode: int = 0o600) -> None:
    """``os.fchmod(fd, mode)`` where files have POSIX modes. On Windows there are no mode bits to set (Python 3.12
    has no ``os.fchmod`` there at all): the file is private only when its folder's ACL is private. ``%LOCALAPPDATA%``
    and the user profile are by default; a data folder elsewhere (``C:\\pitwall\\data``, another drive) inherits
    "Authenticated Users" access from the drive root unless ``scripts/windows/install.ps1`` made it private."""
    if sys.platform != "win32":
        os.fchmod(fd, mode)


# ------------------------------------------------------------------------------------------------ UDP sockets
# ICMP "port unreachable" for a datagram sent on a connect()-ed UDP socket: POSIX reports ECONNREFUSED, Windows
# WSAECONNRESET (on the next receive). Both mean "nothing listens on that port".
PORT_UNREACHABLE: tuple[type[OSError], ...] = (ConnectionRefusedError, ConnectionResetError)

_SIO_UDP_CONNRESET = 0x9800000C  # _WSAIOW(IOC_VENDOR, 12), mswsock.h


def bind_udp_exclusive(sock: socket.socket, address: tuple[str, int]) -> None:
    """Bind a telemetry listener so that no other process can bind the same port as well.

    POSIX: ``SO_REUSEADDR`` as before (a restarted pitwall can rebind at once; a second process still gets
    ``EADDRINUSE`` for the same unicast address and port). Windows: ``SO_REUSEADDR`` would let any other process
    bind the *same* port and receive the game's packets in our place, so it is never set there; instead
    ``SO_EXCLUSIVEADDRUSE`` stops even a ``SO_REUSEADDR`` socket from sharing it (Windows has no
    ``TIME_WAIT`` for UDP, so a restart does not need address reuse).
    """
    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(address)


def ignore_udp_port_unreachable(sock: socket.socket) -> bool:
    """Windows only: stop ICMP "port unreachable" replies to datagrams this socket *sent* from failing its next
    ``recvfrom`` with ``WSAECONNRESET`` (``SIO_UDP_CONNRESET`` off). For sockets that send to peers which may not
    be listening (heartbeats, a fake game server whose client went away) and receive on the same socket.

    A no-op returning False elsewhere: POSIX never reports ICMP errors on an unconnected UDP socket. Best effort:
    a failure is logged and the caller carries on (its receive loop must tolerate ``ConnectionResetError``).
    ``WSAIoctl`` is called through ctypes because ``socket.ioctl`` only accepts three other control codes.
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        ws2 = ctypes.WinDLL("ws2_32", use_last_error=True)
        wsa_ioctl = ws2.WSAIoctl
        wsa_ioctl.argtypes = [
            ctypes.c_size_t,  # SOCKET (UINT_PTR)
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        wsa_ioctl.restype = ctypes.c_int
        report = wintypes.BOOL(False)
        returned = wintypes.DWORD(0)
        rc = wsa_ioctl(
            sock.fileno(),
            _SIO_UDP_CONNRESET,
            ctypes.byref(report),
            ctypes.sizeof(report),
            None,
            0,
            ctypes.byref(returned),
            None,
            None,
        )
        if rc != 0:
            raise OSError(ctypes.get_last_error(), "WSAIoctl(SIO_UDP_CONNRESET) failed")
    except Exception as e:  # never fatal: the receive loops tolerate WSAECONNRESET anyway
        log.debug("cannot disable UDP connection-reset reporting: %s", e)
        return False
    return True


def is_port_unreachable(e: BaseException) -> bool:
    """``e`` is an ICMP "port unreachable" report on a UDP socket (``ECONNREFUSED`` / ``WSAECONNRESET``)."""
    if isinstance(e, PORT_UNREACHABLE):
        return True
    return isinstance(e, OSError) and e.errno in (errno.ECONNREFUSED, errno.ECONNRESET)
