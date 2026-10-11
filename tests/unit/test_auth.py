"""Access policy: local trust, Tailscale Serve identity, LAN token, and header-spoofing resistance."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pitwall.api.auth import AccessPolicy
from pitwall.config import Settings

OWNER = "owner@example.com"
# Example addresses only: 100.64.0.x stand for tailnet (CGNAT) IPs, 192.0.2.x (RFC 5737) for LAN clients.
P = AccessPolicy("tok", frozenset({OWNER}), proxy_peers=frozenset({"100.64.0.1"}))


def test_direct_loopback_is_trusted() -> None:
    assert P.check("127.0.0.1", {}, None, None).via == "local"
    assert P.check("::1", {}, None, None).allowed


def test_tailscale_serve_owner_is_allowed_without_token() -> None:
    d = P.check("127.0.0.1", {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.2"}, None, None)
    assert d.allowed and d.via == f"tailscale:{OWNER}"


def test_tailscale_serve_other_user_needs_token() -> None:
    hdr = {"Tailscale-User-Login": "guest@example.com", "X-Forwarded-For": "100.64.0.3"}
    assert not P.check("127.0.0.1", hdr, None, None).allowed
    assert P.check("127.0.0.1", hdr, None, "tok").allowed


def test_proxied_without_identity_is_not_treated_as_local() -> None:
    # e.g. a tagged node or another reverse proxy: forwarding header present, no Tailscale identity
    assert not P.check("127.0.0.1", {"X-Forwarded-For": "100.1.2.3"}, None, None).allowed


def test_macos_serve_connects_from_own_tailnet_ip() -> None:
    hdr = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.2"}
    assert P.check("100.64.0.1", hdr, None, None).via == f"tailscale:{OWNER}"


def test_other_tailnet_device_connecting_directly_cannot_spoof() -> None:
    assert not P.check("100.64.0.34", {"Tailscale-User-Login": OWNER}, None, None).allowed


def test_lan_client_cannot_spoof_tailscale_identity() -> None:
    d = P.check("192.0.2.50", {"Tailscale-User-Login": OWNER}, None, None)
    assert not d.allowed
    assert P.check("192.0.2.50", {}, "tok", None).set_cookie


def test_app_honours_tailscale_identity(tmp_path: Path) -> None:
    from pitwall.api.app import create_app

    s = Settings(
        data_dir=tmp_path,
        llm_enabled=False,
        access_token="tok",
        tailscale_trust_owner=False,
        tailscale_allowed_logins=[OWNER],
    )
    app = create_app(s, start_udp=False)
    with TestClient(app, client=("127.0.0.1", 40000)) as c:
        assert (
            c.get("/api/health", headers={"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.9.9.9"}).status_code
            == 200
        )
        assert (
            c.get("/api/health", headers={"Tailscale-User-Login": "x@y.z", "X-Forwarded-For": "100.9.9.9"}).status_code
            == 401
        )
    with TestClient(app, client=("192.0.2.9", 40000)) as c:
        assert c.get("/api/health", headers={"Tailscale-User-Login": OWNER}).status_code == 401
