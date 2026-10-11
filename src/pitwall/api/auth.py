"""Access policy for HTTP and WebSocket requests.

* Direct loopback connections (this Mac) are trusted.
* Requests proxied by Tailscale Serve arrive from loopback or (on macOS, via the network extension) from this
  machine's OWN tailnet address. They are recognised by their forwarding headers and authenticated by
  **Tailscale identity**: ``Tailscale-User-Login`` must be an allowed login (by default the tailnet owner,
  auto-detected). Tailscale headers are only honoured from those proxy peers, so a LAN or tailnet client
  connecting directly (from its own address) cannot spoof them.
* Everything else (LAN devices on 0.0.0.0) needs the access token (header, ``?token=`` or cookie).

The server must run with uvicorn ``proxy_headers=False`` so ``request.client`` is the real TCP peer.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# The app's own CLI first (macOS app bundle / Windows installer default), then PATH.
if sys.platform == "win32":
    TAILSCALE_CLI_CANDIDATES: tuple[str, ...] = (
        str(Path(os.environ.get("PROGRAMFILES") or r"C:\Program Files") / "Tailscale" / "tailscale.exe"),
        "tailscale",
    )
else:
    TAILSCALE_CLI_CANDIDATES = ("/Applications/Tailscale.app/Contents/MacOS/Tailscale", "tailscale")
_PROXY_HEADERS = ("tailscale-user-login", "x-forwarded-for", "forwarded", "x-real-ip")


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    if host in ("testclient", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class AuthDecision:
    allowed: bool
    via: str  # "local" | "tailscale:<login>" | "token" | "denied"
    set_cookie: bool = False


class AccessPolicy:
    def __init__(
        self,
        token: str,
        tailscale_logins: frozenset[str] = frozenset(),
        proxy_peers: frozenset[str] = frozenset(),
    ) -> None:
        self.token = token
        self.tailscale_logins = tailscale_logins
        self.proxy_peers = proxy_peers  # this machine's own tailnet IPs (where Tailscale Serve connects from)

    def check(
        self,
        peer_host: str | None,
        headers: Mapping[str, str],
        query_token: str | None,
        cookie_token: str | None,
    ) -> AuthDecision:
        lower = {k.lower(): v for k, v in headers.items()}
        if is_loopback(peer_host) or (peer_host is not None and peer_host in self.proxy_peers):
            proxied = any(h in lower for h in _PROXY_HEADERS)
            if not proxied:
                return AuthDecision(True, "local")  # a process on this machine
            login = lower.get("tailscale-user-login")
            if login and login in self.tailscale_logins:
                return AuthDecision(True, f"tailscale:{login}")
        supplied = lower.get("x-pitwall-token") or query_token or cookie_token
        if supplied and supplied == self.token:
            return AuthDecision(True, "token", set_cookie=bool(query_token))
        return AuthDecision(False, "denied")


def tailscale_cli() -> str | None:
    for c in TAILSCALE_CLI_CANDIDATES:
        if Path(c).is_file() or shutil.which(c):
            return c
    return None


@dataclass(frozen=True, slots=True)
class TailscaleSelf:
    owner_login: str | None
    ips: frozenset[str]
    dns_name: str | None


def detect_tailscale(timeout_s: float = 3.0) -> TailscaleSelf | None:
    """This node's owner login, tailnet IPs and DNS name, or None if Tailscale is unavailable."""
    cli = tailscale_cli()
    if cli is None:
        return None
    try:
        # TAILSCALE_BE_CLI: the standalone macOS app binary otherwise tries to launch its GUI when started
        # from a non-interactive context (launchd), printing an error instead of JSON.
        env = {**os.environ, "TAILSCALE_BE_CLI": "1"}
        out = subprocess.run(
            [cli, "status", "--json"],
            capture_output=True,
            encoding="utf-8",  # JSON is UTF-8; Windows' locale code page would garble non-ASCII login names
            errors="replace",
            timeout=timeout_s,
            check=True,
            env=env,
        )
        data = json.loads(out.stdout)
        me = data["Self"]
        login = data["User"][str(me["UserID"])]["LoginName"]
        return TailscaleSelf(
            owner_login=str(login) if login else None,
            ips=frozenset(str(ip) for ip in me.get("TailscaleIPs") or []),
            dns_name=str(me.get("DNSName") or "").rstrip(".") or None,
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as e:
        log.info("tailscale detection unavailable: %s", e)
        return None
