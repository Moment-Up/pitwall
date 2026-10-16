"""``pitwall doctor``: every check runs against fakes (no real ports, subprocesses or network), so the same tests
pass on macOS, Windows and Linux. One test binds real ephemeral loopback ports to prove the bind probe."""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import pytest
from typer.testing import CliRunner

from pitwall import doctor
from pitwall.config import Settings
from pitwall.doctor import (
    MAC_TTS_HOME,
    REPO_ROOT,
    WEB_DIR,
    WEB_REACT_DIR,
    Check,
    Host,
    HttpReply,
    Probes,
    Report,
    RunResult,
    firewall_rule_names,
    format_text,
    run_doctor,
)

HTTP_PORT = 8794
UDP_PORT = 20794


class Fake:
    """Scripted machine: HTTP replies by URL suffix, busy ports, command outputs by substring."""

    def __init__(self) -> None:
        self.http: dict[str, HttpReply] = {}
        self.busy: set[tuple[str, int]] = set()
        self.runs: dict[str, RunResult] = {
            "socketfilterfw --getglobalstate": RunResult(0, "Firewall is disabled. (State = 0)\n"),
            "node --version": RunResult(0, "v22.12.0\n"),
        }
        self.tools: dict[str, str | None] = {
            "uv": "/bin/uv",
            "node": "node",
            "npm": "/bin/npm",
            "say": "/usr/bin/say",
            "netsh": "netsh",
            "powershell": "powershell",
        }
        self.modules = {"parakeet_mlx": True, "mlx": True}
        self.lan: str | None = "192.168.1.20"
        self.acc_pages = "absent"  # ACC's shared memory: present | absent | denied: ... (never the real machine's)
        self.tailscale: str | None = None
        self.http_calls: list[str] = []
        self.bind_calls: list[tuple[str, str, int]] = []
        self.run_calls: list[str] = []

    def http_get(self, url: str, timeout_s: float) -> HttpReply | None:
        self.http_calls.append(url)
        return next((r for suffix, r in self.http.items() if url.endswith(suffix)), None)

    def bind_error(self, proto: Literal["tcp", "udp"], host: str, port: int) -> str | None:
        self.bind_calls.append((proto, host, port))
        return "is in use by another program" if (proto, port) in self.busy else None

    def run(self, cmd: Sequence[str] | str, timeout_s: float) -> RunResult | None:
        text = cmd if isinstance(cmd, str) else " ".join(cmd)
        self.run_calls.append(text)
        matches = [key for key in self.runs if key in text]
        return self.runs[max(matches, key=len)] if matches else None  # the most specific key wins

    def probes(self) -> Probes:
        return Probes(
            http_get=self.http_get,
            bind_error=self.bind_error,
            run=self.run,
            which=lambda name: self.tools.get(name),
            has_module=lambda name: self.modules.get(name, False),
            lan_ip=lambda: self.lan,
            tailscale_cli=lambda: self.tailscale,
            acc_pages=lambda: self.acc_pages,
        )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".venv").mkdir(parents=True)
    return root


@pytest.fixture(autouse=True)
def plenty_of_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    class Usage:
        free = 500e9

    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda _p: Usage())


def host(repo: Path, system: str = "Darwin", machine: str = "arm64", **kw: Any) -> Host:
    args: dict[str, Any] = {
        "system": system,
        "release": {"Darwin": "26.4", "Windows": "11"}.get(system, "6.8"),
        "version": "10.0.26100" if system == "Windows" else "",
        "machine": machine,
        "python": (3, 12, 13),
        "prefix": repo / ".venv",
        "base_prefix": repo.parent / "python",
        "cwd": repo,
        "home": repo.parent,
    }
    args.update(kw)
    return Host(**args)


def settings(repo: Path, **kw: Any) -> Settings:
    tts = repo.parent / "tts"
    values: dict[str, Any] = {
        "data_dir": repo / "data",
        "http_port": HTTP_PORT,
        "f1_udp_port": UDP_PORT,
        "llm_enabled": False,
        "tts_worker_python": tts / "tts-venv" / "bin" / "python",
        "tts_hf_home": tts / "hf",
    }
    values.update(kw)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


def build_react(repo: Path, base: str = "/", stale: bool = False) -> None:
    src = repo / WEB_REACT_DIR / "src"
    src.mkdir(parents=True)
    (src / "main.tsx").write_text("export {}", encoding="utf-8")
    dist = repo / WEB_REACT_DIR / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        f'<script type="module" src="{base}assets/index-abc.js"></script>', encoding="utf-8"
    )
    old, new = time.time() - 1000, time.time()
    os.utime(src / "main.tsx", (new, new) if stale else (old, old))
    os.utime(dist / "index.html", (old + 10, old + 10) if stale else (new, new))


def build_svelte(repo: Path) -> None:
    dist = repo / WEB_DIR / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")


def ready_voice_and_token(repo: Path) -> None:
    py = repo.parent / "tts" / "tts-venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    (repo.parent / "tts" / "hf").mkdir()
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / "access_token").write_text("tok-SECRET-123", encoding="utf-8")


def by_id(report: Report) -> dict[str, Check]:
    return {c.id: c for c in report.checks}


def run(repo: Path, fake: Fake, s: Settings | None = None, **kw: Any) -> Report:
    h = kw.pop("host", None) or host(repo)
    return run_doctor(s or settings(repo), probes=fake.probes(), host=h, repo_root=repo, **kw)


# --------------------------------------------------------------------------------------------- whole report
def test_healthy_mac_is_all_ok_and_serialisable(repo: Path) -> None:
    build_react(repo)
    ready_voice_and_token(repo)
    fake = Fake()
    report = run(repo, fake)
    checks = by_id(report)
    assert report.overall == "ok", format_text(report)
    assert report.exit_code == 0
    assert {"system", "python_env", "settings", "data_dir", "dashboard", "node", "http_port", "udp_f1"} <= set(checks)
    assert {"firewall", "lan_ip", "access_token", "telemetry", "llm", "voice_stt", "voice_tts", "tailscale"} <= set(
        checks
    )
    assert "network_profile" not in checks  # Windows only
    assert checks["llm"].detail.startswith("off (deterministic answers only)")
    assert checks["telemetry"].status == "info"  # no server running
    assert ("tcp", "0.0.0.0", HTTP_PORT) in fake.bind_calls
    assert ("udp", "0.0.0.0", UDP_PORT) in fake.bind_calls
    data = json.loads(json.dumps(report.to_dict()))
    assert data["schema"] == 1
    assert data["summary"]["overall"] == "ok"
    assert data["summary"]["fail"] == 0
    assert data["urls"] == {"local": f"http://127.0.0.1:{HTTP_PORT}/", "lan": f"http://192.168.1.20:{HTTP_PORT}/"}
    assert data["server"] == {"running": False, "version": None, "udp_port": None, "telemetry": None, "synthetic": None}
    assert data["firewall_rules"] == []  # Windows Defender Firewall rule names: Windows only
    assert "data_private" not in checks  # Windows only
    assert all(set(c) == {"id", "title", "status", "detail", "fix"} for c in data["checks"])
    text = format_text(report)
    text.encode("ascii")  # Windows consoles may not be UTF-8
    assert "Result: OK" in text


def test_only_loopback_and_no_llm_traffic_with_no_llm(repo: Path) -> None:
    fake = Fake()
    report = run(repo, fake, settings(repo, llm_enabled=True), probe_llm=False)
    assert all(u.startswith(f"http://127.0.0.1:{HTTP_PORT}/") for u in fake.http_calls), fake.http_calls
    assert by_id(report)["llm"].status == "info"
    assert "not contacted" in by_id(report)["llm"].detail


# --------------------------------------------------------------------------------------------- system / env
def test_unsupported_python_fails(repo: Path) -> None:
    report = run(repo, Fake(), host=host(repo, python=(3, 11, 9)))
    c = by_id(report)["system"]
    assert c.status == "fail"
    assert "uv python install 3.12" in c.fix
    assert report.exit_code == 1


def test_outside_a_venv_fails_and_another_venv_warns(repo: Path, tmp_path: Path) -> None:
    py = tmp_path / "system-python"
    py.mkdir()
    c = by_id(run(repo, Fake(), host=host(repo, prefix=py, base_prefix=py)))["python_env"]
    assert c.status == "fail"
    assert "uv run pitwall doctor" in c.fix
    other = tmp_path / "other-venv"
    other.mkdir()
    assert by_id(run(repo, Fake(), host=host(repo, prefix=other)))["python_env"].status == "warn"


def test_missing_uv_warns(repo: Path) -> None:
    fake = Fake()
    fake.tools["uv"] = None
    c = by_id(run(repo, fake))["python_env"]
    assert c.status == "warn"
    assert "docs.astral.sh/uv" in c.fix


def test_unreadable_settings_file_warns_without_touching_it(repo: Path) -> None:
    (repo / "data").mkdir()
    bad = repo / "data" / "settings.json"
    bad.write_text("{not json", encoding="utf-8")
    c = by_id(run(repo, Fake()))["settings"]
    assert c.status == "warn"
    assert bad.read_text(encoding="utf-8") == "{not json"  # pitwall itself moves it aside; the doctor only reports


def test_data_dir_not_writable_fails(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(**_kw: Any) -> Any:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(doctor.tempfile, "NamedTemporaryFile", denied)
    c = by_id(run(repo, Fake()))["data_dir"]
    assert c.status == "fail"
    assert "PITWALL_DATA_DIR" in c.fix


def test_relative_data_dir_outside_the_repo_warns(repo: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    c = by_id(run(repo, Fake(), settings(repo, data_dir=Path("data")), host=host(repo, cwd=elsewhere)))["data_dir"]
    assert c.status == "warn"
    assert str(repo) in c.fix


# --------------------------------------------------------------------------------------------- dashboard / node
@pytest.mark.parametrize(
    ("setup", "status", "words"),
    [
        ("root", "ok", "React + HeroUI dashboard"),
        ("next", "warn", "built for /next/"),
        ("stale", "warn", "older than its source"),
        ("svelte", "ok", "Svelte dashboard"),
        ("none", "fail", "no dashboard built"),
    ],
)
def test_dashboard_states(repo: Path, setup: str, status: str, words: str) -> None:
    if setup in ("root", "next", "stale"):
        build_react(repo, base="/next/" if setup == "next" else "/", stale=setup == "stale")
    elif setup == "svelte":
        build_svelte(repo)
    c = by_id(run(repo, Fake()))["dashboard"]
    assert c.status == status
    assert words in c.detail
    if status != "ok":
        assert "npm" in c.fix


def test_windows_dashboard_fix_uses_the_installer(repo: Path) -> None:
    c = by_id(run(repo, _windows_fake(), host=host(repo, system="Windows", machine="AMD64")))["dashboard"]
    assert c.status == "fail"
    assert r"scripts\windows\install.ps1 -NonInteractive -Dashboard svelte" in c.fix


def test_node_needed_only_when_nothing_is_built(repo: Path) -> None:
    fake = Fake()
    fake.tools["node"] = None
    assert by_id(run(repo, fake))["node"].status == "fail"
    build_svelte(repo)
    assert by_id(run(repo, fake))["node"].status == "info"


@pytest.mark.parametrize(
    ("version", "status"),
    [("v18.20.4", "warn"), ("v20.11.1", "warn"), ("v20.19.0", "ok"), ("v22.11.0", "warn"), ("v24.10.0", "ok")],
)
def test_node_versions_vite_can_use(repo: Path, version: str, status: str) -> None:
    fake = Fake()
    fake.runs["node --version"] = RunResult(0, version + "\n")
    c = by_id(run(repo, fake))["node"]
    assert c.status == status, c.detail
    if version == "v20.19.0":
        assert "asks for 22.12+" in c.detail


# --------------------------------------------------------------------------------------------- ports / server
def test_http_port_used_by_another_program(repo: Path) -> None:
    fake = Fake()
    fake.busy.add(("tcp", HTTP_PORT))
    c = by_id(run(repo, fake))["http_port"]
    assert c.status == "fail"
    assert "PITWALL_HTTP_PORT" in c.fix
    fake = Fake()
    fake.http["/api/health"] = HttpReply(404, b"not found")
    c = by_id(run(repo, fake))["http_port"]
    assert c.status == "fail"
    assert "not Pitwall" in c.detail


def test_loopback_only_http_host_warns(repo: Path) -> None:
    c = by_id(run(repo, Fake(), settings(repo, http_host="127.0.0.1")))["http_port"]
    assert c.status == "warn"
    assert "PITWALL_HTTP_HOST=0.0.0.0" in c.fix


def _health(status: str = "live", **conn: Any) -> HttpReply:
    body = {
        "version": "0.1.0",
        "connection": {"status": status, "packets": 5000, "packets_per_s": 60.0, "source": "udp:20794", **conn},
        "udp_port": UDP_PORT,
        "db_writer_errors": 0,
        "analysis_errors": 0,
    }
    return HttpReply(200, json.dumps(body).encode())


def test_running_pitwall_reports_its_own_listeners_without_binding(repo: Path) -> None:
    fake = Fake()
    fake.http["/api/health"] = _health()
    rows = [
        {"key": "f1", "enabled": True, "port": UDP_PORT, "listening": True, "listens": True},
        {"key": "gt7", "enabled": True, "port": 33740, "listening": False, "error": "port in use", "listens": True},
        {"key": "forza", "enabled": False, "port": 5301, "listening": False, "listens": True},
    ]
    fake.http["/api/integrations"] = HttpReply(200, json.dumps(rows).encode())
    report = run(repo, fake)
    checks = by_id(report)
    assert checks["http_port"].status == "ok"
    assert "already running" in checks["http_port"].detail
    assert checks["udp_f1"].status == "ok"
    assert checks["udp_gt7"].status == "fail"
    assert "port in use" in checks["udp_gt7"].detail
    assert "udp_forza" not in checks
    assert not [b for b in fake.bind_calls if b[0] == "udp"]  # never bind a port a running Pitwall owns
    assert checks["telemetry"].status == "ok"
    assert "60.0 packets/s" in checks["telemetry"].detail
    assert report.to_dict()["server"] == {
        "running": True,
        "version": "0.1.0",
        "udp_port": UDP_PORT,
        "telemetry": "live",
        "synthetic": False,
    }
    win = run(repo, fake, host=host(repo, system="Windows", machine="AMD64"))
    assert win.firewall_rules == [f"Pitwall HTTP {HTTP_PORT}", f"Pitwall UDP {UDP_PORT}", "Pitwall UDP 33740"]


def test_udp_port_in_use_fails_with_a_fix(repo: Path) -> None:
    fake = Fake()
    fake.busy.add(("udp", UDP_PORT))
    c = by_id(run(repo, fake))["udp_f1"]
    assert c.status == "fail"
    assert "Setup > Connect" in c.fix


def test_enabled_games_from_dashboard_settings_are_checked(repo: Path) -> None:
    (repo / "data").mkdir()
    store = {"integrations": {"gt7": {"enabled": True}, "ac": {"enabled": True}}}
    (repo / "data" / "settings.json").write_text(json.dumps(store), encoding="utf-8")
    report = run(repo, Fake(), host=host(repo, system="Windows", machine="AMD64"))
    checks = by_id(report)
    assert checks["udp_gt7"].status == "ok"
    assert checks["udp_ac"].status == "warn"  # AC needs the console's IP
    assert "console" in checks["udp_ac"].fix
    assert "Pitwall UDP 33740" in report.firewall_rules
    assert "Pitwall UDP 9996" not in report.firewall_rules  # AC binds nothing here


def test_telemetry_rejected_packets_warn(repo: Path) -> None:
    fake = Fake()
    fake.http["/api/health"] = _health("no_data", packets=0, rejected=12)
    c = by_id(run(repo, fake))["telemetry"]
    assert c.status == "warn"
    assert "UDP Format" in c.fix


def test_synthetic_demo_telemetry_is_info_never_ok(repo: Path) -> None:
    """The demo proves the install, not a game: synthetic packets alone never make telemetry "ok"."""
    for status, extra in (("live", {}), ("stale", {"last_packet_age_s": 229.0})):
        fake = Fake()
        fake.http["/api/health"] = _health(status, synthetic=True, **extra)
        report = run(repo, fake)
        c = by_id(report)["telemetry"]
        assert c.status == "info", (status, c)
        assert "SYNTHETIC" in c.detail and "no game telemetry yet" in c.detail
        assert f"192.168.1.20:{UDP_PORT}" in c.fix
        assert report.to_dict()["server"]["synthetic"] is True
    fake = Fake()
    fake.http["/api/health"] = _health("stale", last_packet_age_s=12.0)
    c = by_id(run(repo, fake))["telemetry"]
    assert c.status == "ok" and "last packet 12 s ago" in c.detail


def test_telemetry_no_data_points_at_the_lan_ip(repo: Path) -> None:
    fake = Fake()
    fake.http["/api/health"] = _health("no_data", packets=0)
    c = by_id(run(repo, fake))["telemetry"]
    assert c.status == "info"
    assert f"192.168.1.20:{UDP_PORT}" in c.fix


def test_no_lan_address_or_a_vpn_address_warns(repo: Path) -> None:
    fake = Fake()
    fake.lan = None
    assert by_id(run(repo, fake))["lan_ip"].status == "warn"
    fake.lan = "8.8.4.4"
    assert by_id(run(repo, fake))["lan_ip"].status == "warn"


# --------------------------------------------------------------------------------------------- Windows
ME_SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
PRIVATE_ACL = [(ME_SID, 2032127), ("S-1-5-18", 2032127), ("S-1-5-32-544", 2032127)]
# a folder under C:\ inherits Users: ReadAndExecute and Authenticated Users: Modify (inherit-only GENERIC_* too)
DRIVE_ROOT_ACL = [*PRIVATE_ACL, ("S-1-5-32-545", 1179817), ("S-1-5-11", 1245631), ("S-1-5-11", -536805376)]


def _fw_line(
    name: str, enabled: str = "True", action: str = "Allow", profile: str = "Private", remote: str = "LocalSubnet"
) -> str:
    return f"FWRULE|{name}|{enabled}|{action}|Inbound|{profile}|{remote}"


def _windows_fake(
    profile: str = "Private",
    missing_udp: bool = False,
    udp_rule: str | None = None,
    acl: list[tuple[str, int]] | None = None,
    data_missing: bool = False,
    with_rules: bool = True,
) -> Fake:
    fake = Fake()
    fake.runs[f'name="Pitwall HTTP {HTTP_PORT}"'] = RunResult(0, "Rule Name: Pitwall HTTP\n")
    fake.runs[f'name="Pitwall UDP {UDP_PORT}"'] = RunResult(1 if missing_udp else 0, "")
    lines = [f"PROFILE|Wi-Fi|{profile}"]
    if with_rules:
        lines.append(_fw_line(f"Pitwall HTTP {HTTP_PORT}"))
        if missing_udp:
            lines.append(f"FWRULE|Pitwall UDP {UDP_PORT}|MISSING")
        else:
            lines.append(udp_rule or _fw_line(f"Pitwall UDP {UDP_PORT}"))
    if data_missing:
        lines.append("DATAACL|MISSING")
    else:
        lines.append(f"ME|{ME_SID}")
        lines.extend(f"DATAACL|{sid}|{rights}" for sid, rights in (PRIVATE_ACL if acl is None else acl))
        lines.append("DATAACL|CHECKED")
    lines += ["VOICE|Microsoft David Desktop", "VOICE|Microsoft Zira Desktop", "DONE|"]
    fake.runs["Get-NetConnectionProfile"] = RunResult(0, "\r\n".join(lines) + "\r\n")
    return fake


def _win(repo: Path) -> Host:
    return host(repo, system="Windows", machine="AMD64")


def test_windows_missing_firewall_rule_and_public_network_warn(repo: Path) -> None:
    fake = _windows_fake(profile="Public", missing_udp=True)
    report = run(repo, fake, host=_win(repo))
    checks = by_id(report)
    fw = checks["firewall"]
    assert fw.status == "warn"
    assert f'"Pitwall UDP {UDP_PORT}"' in fw.detail
    assert f"Pitwall HTTP {HTTP_PORT}" not in fw.detail
    assert r"scripts\windows\firewall.ps1 add" in fw.fix
    assert checks["network_profile"].status == "warn"
    assert "Private" in checks["network_profile"].fix
    assert checks["voice_tts"].status == "ok"
    assert "Microsoft David Desktop" in checks["voice_tts"].detail
    assert checks["voice_stt"].status == "warn"  # lane handsfree: the voice extra installs sherpa-onnx on Windows
    assert "sherpa-onnx is not installed" in checks["voice_stt"].detail
    assert checks["voice_stt"].fix == "uv sync --all-extras"
    assert checks["voice_handsfree"].detail == "needs speech recognition (see Speech input)"
    assert not any("socketfilterfw" in c for c in fake.run_calls)
    assert not any(c.startswith("netsh") for c in fake.run_calls)  # PowerShell read the rules: no netsh needed
    ps = [c for c in fake.run_calls if "Get-NetConnectionProfile" in c]
    assert len(ps) == 1  # one PowerShell start for every Windows fact
    assert f"'Pitwall HTTP {HTTP_PORT}','Pitwall UDP {UDP_PORT}'" in ps[0]
    assert report.system["platform"] == "win32"
    assert report.firewall_rules == [f"Pitwall HTTP {HTTP_PORT}", f"Pitwall UDP {UDP_PORT}"]


def test_windows_rules_present_on_a_private_network_are_ok(repo: Path) -> None:
    checks = by_id(run(repo, _windows_fake(), host=_win(repo)))
    assert checks["firewall"].status == "ok"
    assert "enabled (Private, local subnet)" in checks["firewall"].detail
    assert checks["network_profile"].status == "ok"
    assert checks["network_profile"].detail == "Wi-Fi: Private"


@pytest.mark.parametrize(
    ("rule", "words"),
    [
        (_fw_line(f"Pitwall UDP {UDP_PORT}", enabled="False"), "is disabled"),
        (_fw_line(f"Pitwall UDP {UDP_PORT}", action="Block"), "not an inbound Allow rule"),
        (_fw_line(f"Pitwall UDP {UDP_PORT}", profile="Public"), "Public profile, not Private"),
        (_fw_line(f"Pitwall UDP {UDP_PORT}", remote="Any"), "accept any address"),
    ],
)
def test_windows_edited_or_disabled_rule_is_not_ok(repo: Path, rule: str, words: str) -> None:
    """A rule that exists is not enough: disabled, Block, Public-only or opened to any address all warn."""
    fw = by_id(run(repo, _windows_fake(udp_rule=rule), host=_win(repo)))["firewall"]
    assert fw.status == "warn", fw
    assert words in fw.detail
    assert f"Pitwall UDP {UDP_PORT}" in fw.detail and f"Pitwall HTTP {HTTP_PORT}" not in fw.detail
    assert "firewall.ps1 add" in fw.fix


def test_windows_rule_on_every_profile_counts(repo: Path) -> None:
    rule = _fw_line(f"Pitwall UDP {UDP_PORT}", profile="Domain, Private, Public")
    assert by_id(run(repo, _windows_fake(udp_rule=rule), host=_win(repo)))["firewall"].status == "ok"
    rule = _fw_line(f"Pitwall UDP {UDP_PORT}", profile="Any")
    assert by_id(run(repo, _windows_fake(udp_rule=rule), host=_win(repo)))["firewall"].status == "ok"


def test_windows_firewall_falls_back_to_netsh_without_powershell_facts(repo: Path) -> None:
    fake = _windows_fake(missing_udp=True, with_rules=False)
    fw = by_id(run(repo, fake, host=_win(repo)))["firewall"]
    assert fw.status == "warn" and f'"Pitwall UDP {UDP_PORT}"' in fw.detail
    assert any(c.startswith("netsh advfirewall firewall show rule name=") for c in fake.run_calls)


def test_windows_data_folder_readable_by_other_accounts_warns(repo: Path) -> None:
    (repo / "data").mkdir()
    c = by_id(run(repo, _windows_fake(acl=DRIVE_ROOT_ACL), host=_win(repo)))["data_private"]
    assert c.status == "warn"
    assert "Authenticated Users, Users can open" in c.detail
    assert "access token" in c.detail
    assert c.fix == (
        f'in PowerShell: icacls "{repo / "data"}" /inheritance:r /grant:r "*{ME_SID}:(OI)(CI)F" '
        '"*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F"'
    )
    everyone = [*PRIVATE_ACL, ("S-1-1-0", 1)]  # read access alone is enough to warn
    assert by_id(run(repo, _windows_fake(acl=everyone), host=_win(repo)))["data_private"].status == "warn"
    traverse_only = [*PRIVATE_ACL, ("S-1-1-0", 0x20)]  # Everyone may traverse: cannot read or write files
    assert by_id(run(repo, _windows_fake(acl=traverse_only), host=_win(repo)))["data_private"].status == "ok"


def test_windows_private_or_missing_data_folder(repo: Path) -> None:
    c = by_id(run(repo, _windows_fake(), host=_win(repo)))["data_private"]
    assert c.status == "ok"
    c = by_id(run(repo, _windows_fake(data_missing=True), host=_win(repo)))["data_private"]
    assert c.status == "info" and "does not exist yet" in c.detail


def test_windows_facts_script_quotes_paths_and_names() -> None:
    data = Path("C:/Users/o'brien/pitwall/data")
    script = doctor._win_facts_script(data, ["Pitwall HTTP 8770"])
    assert f"$d = '{str(data).replace(chr(39), chr(39) * 2)}';" in script  # PowerShell single quotes: ' doubled
    assert "o''brien" in script
    assert "Get-Acl" not in script and "Test-Path" not in script  # .NET only: no module to load
    assert "@('Pitwall HTTP 8770')" in script
    assert script.endswith("'DONE|'")


def test_windows_sapi_voice_setting_is_checked(repo: Path) -> None:
    win = host(repo, system="Windows", machine="AMD64")
    s = settings(repo)
    if not hasattr(s, "tts_sapi_voice"):
        pytest.skip("this build has no Windows SAPI voice setting")
    c = by_id(run(repo, _windows_fake(), settings(repo, tts_sapi_voice="Zira"), host=win))["voice_tts"]
    assert c.status == "ok"
    assert "'Microsoft Zira Desktop'" in c.detail
    c = by_id(run(repo, _windows_fake(), settings(repo, tts_sapi_voice="Hazel"), host=win))["voice_tts"]
    assert c.status == "warn"
    assert "PITWALL_TTS_SAPI_VOICE" in c.fix


def test_windows_without_powershell_is_info_not_failure(repo: Path) -> None:
    fake = _windows_fake()
    fake.tools["powershell"] = None
    checks = by_id(run(repo, fake, host=_win(repo)))
    assert checks["network_profile"].status == "info"
    assert checks["voice_tts"].status == "info"
    assert checks["data_private"].status == "info"
    assert checks["firewall"].status == "ok"  # netsh still finds the rules


def test_firewall_rule_names_are_unique_and_sorted() -> None:
    assert firewall_rule_names(8770, [33740, 20777, 20777]) == [
        "Pitwall HTTP 8770",
        "Pitwall UDP 20777",
        "Pitwall UDP 33740",
    ]


# --------------------------------------------------------------------------------------------- macOS specifics
def test_mac_firewall_block_all_warns(repo: Path) -> None:
    fake = Fake()
    fake.runs["socketfilterfw --getglobalstate"] = RunResult(0, "Firewall is enabled. (State = 1)\n")
    fake.runs["--getblockall"] = RunResult(0, "Firewall has block all state set to enabled.\n")
    assert by_id(run(repo, fake))["firewall"].status == "warn"
    fake.runs["--getblockall"] = RunResult(0, "Firewall has block all state set to disabled.\n")
    assert by_id(run(repo, fake))["firewall"].status == "info"


def test_mac_voice_not_installed(repo: Path) -> None:
    fake = Fake()
    fake.modules = {}
    checks = by_id(run(repo, fake))
    assert checks["voice_stt"].status == "warn"
    assert checks["voice_stt"].fix == "uv sync --all-extras"
    assert checks["voice_tts"].status == "info"  # falls back to `say`
    assert "scripts/setup-tts.sh" in checks["voice_tts"].fix


def test_voice_disabled_is_one_info_line(repo: Path) -> None:
    checks = by_id(run(repo, Fake(), settings(repo, voice_enabled=False)))
    assert checks["voice"].status == "info"
    assert "voice_stt" not in checks


# --------------------------------------------------------------------------------------------- LLM
def test_llm_unreachable_warns_and_reachable_is_ok(repo: Path) -> None:
    fake = Fake()
    s = settings(repo, llm_enabled=True)
    c = by_id(run(repo, fake, s))["llm"]
    assert c.status == "warn"
    assert "deterministic" in c.detail
    assert "http://127.0.0.1:8081/v1/models" in fake.http_calls
    fake.http["/v1/models"] = HttpReply(200, b'{"data": []}')
    assert by_id(run(repo, fake, s))["llm"].status == "ok"
    fake.http["/v1/models"] = HttpReply(401, b"")
    c = by_id(run(repo, fake, s))["llm"]
    assert c.status == "ok"
    assert "Settings > AI engineer" in c.detail


def test_saved_llm_section_wins_and_invalid_one_is_reported(repo: Path) -> None:
    (repo / "data").mkdir()
    path = repo / "data" / "settings.json"
    path.write_text(json.dumps({"llm": {"enabled": False, "primary": {"provider": "ollama"}}}), encoding="utf-8")
    c = by_id(run(repo, Fake(), settings(repo, llm_enabled=True)))["llm"]
    assert c.detail == "off (deterministic answers only)"
    path.write_text(json.dumps({"llm": {"enabled": "yes"}}), encoding="utf-8")
    c = by_id(run(repo, Fake(), settings(repo, llm_enabled=False)))["llm"]
    assert "invalid" in c.detail


# --------------------------------------------------------------------------------------------- secrets
def test_token_is_reported_but_never_printed(repo: Path) -> None:
    ready_voice_and_token(repo)
    report = run(repo, Fake())
    c = by_id(report)["access_token"]
    assert c.status == "ok"
    assert "uv run pitwall token" in c.detail
    assert "tok-SECRET-123" not in format_text(report)
    assert "tok-SECRET-123" not in json.dumps(report.to_dict())
    env_report = run(repo, Fake(), settings(repo, access_token="env-SECRET-456"))
    assert "env-SECRET-456" not in json.dumps(env_report.to_dict())
    (repo / "data" / "access_token").unlink()
    assert by_id(run(repo, Fake()))["access_token"].status == "warn"


# --------------------------------------------------------------------------------------------- Tailscale
def _tailscale_fake(proxy_port: int) -> Fake:
    fake = Fake()
    fake.tailscale = "tailscale"
    fake.runs["status --json"] = RunResult(0, json.dumps({"Self": {"DNSName": "box.example.ts.net."}}))
    serve = {
        "TCP": {"443": {"HTTPS": True}, "8443": {"HTTPS": True}},
        "Web": {
            "box.example.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:18789"}}},
            "box.example.ts.net:8443": {"Handlers": {"/": {"Proxy": f"http://127.0.0.1:{proxy_port}"}}},
        },
    }
    fake.runs["serve status --json"] = RunResult(0, json.dumps(serve))
    return fake


def test_tailscale_serve_for_pitwall_is_found(repo: Path) -> None:
    c = by_id(run(repo, _tailscale_fake(HTTP_PORT)))["tailscale"]
    assert c.status == "ok"
    assert "https://box.example.ts.net:8443/" in c.detail


def test_tailscale_fix_never_suggests_a_port_already_served(repo: Path) -> None:
    c = by_id(run(repo, _tailscale_fake(8770)))["tailscale"]
    assert c.status == "info"
    assert "443, 8443" in c.detail
    assert c.fix == f"optional: tailscale serve --bg --https=8444 http://127.0.0.1:{HTTP_PORT}"


# --------------------------------------------------------------------------------------------- real probes / sync
def test_real_bind_probe_sees_a_held_port() -> None:
    for kind, proto in ((socket.SOCK_DGRAM, "udp"), (socket.SOCK_STREAM, "tcp")):
        held = socket.socket(socket.AF_INET, kind)
        held.bind(("127.0.0.1", 0))
        if kind == socket.SOCK_STREAM:
            held.listen(1)
        port = held.getsockname()[1]
        try:
            err = doctor._bind_error(proto, "127.0.0.1", port)  # type: ignore[arg-type]
            assert err is not None
            assert "in use" in err
        finally:
            held.close()


def test_paths_match_the_server_and_the_tts_worker() -> None:
    from pitwall.api.app import WEB_DIST, WEB_REACT_DIST
    from pitwall.voice.tts import TTS_HOME

    assert REPO_ROOT / WEB_REACT_DIR / "dist" == WEB_REACT_DIST
    assert REPO_ROOT / WEB_DIR / "dist" == WEB_DIST
    if sys.platform == "darwin":  # the Kokoro worker only exists on macOS
        assert MAC_TTS_HOME == TTS_HOME


# --------------------------------------------------------------------------------------------- CLI
def test_cli_json_and_exit_code(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    from pitwall.cli import app

    seen: dict[str, Any] = {}

    def fake_run(s: Settings, *, probe_llm: bool = True) -> Report:
        seen["probe_llm"] = probe_llm
        return Report(
            system={"os": "macOS"},
            checks=[Check("dashboard", "Dashboard", "fail", "no dashboard built", "in web/: npm run build")],
            http_port=HTTP_PORT,
        )

    monkeypatch.setattr(doctor, "get_settings", lambda: settings(repo))
    monkeypatch.setattr(doctor, "run_doctor", fake_run)
    result = CliRunner().invoke(app, ["doctor", "--json", "--no-llm"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["summary"] == {"overall": "fail", "ok": 0, "info": 0, "warn": 0, "fail": 1}
    assert seen["probe_llm"] is False
    text = CliRunner().invoke(app, ["doctor"])
    assert "FAIL  Dashboard" in text.output


def test_invalid_environment_is_reported_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Settings:
        raise ValueError("1 validation error for Settings\nhttp_port\n  Input should be a valid integer")

    monkeypatch.setattr(doctor, "get_settings", broken)
    out: list[str] = []
    assert doctor.main(False, False, echo=out.append) == 1
    assert "FAIL" in out[0]
    assert "http_port" in out[0]


# --------------------------------------------------------------------------------------------- game selection
def _store(repo: Path, sections: dict[str, Any]) -> None:
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / "settings.json").write_text(json.dumps(sections), encoding="utf-8")


def _selected(game_id: str, **integrations: Any) -> dict[str, Any]:
    return {"game": {"selected": game_id, "since_unix": 1.0, "source": "cli"}, "integrations": integrations}


@pytest.mark.parametrize(
    ("sections", "status", "detail", "fix"),
    [
        ({}, "info", "no game selected", "uv run pitwall game set <id>"),
        (_selected("acc:ps5"), "warn", "Pitwall can't read Assetto Corsa Competizione (PS5) telemetry", "game list"),
        (_selected("other:any"), "info", "another game: Pitwall can record its packets", "Record another game"),
        (_selected("gt7:ps5"), "warn", "selected but its telemetry input is off", "uv run pitwall game set gt7:ps5"),
        (
            _selected("ac:ps5", ac={"enabled": True}),
            "warn",
            "Assetto Corsa needs the console's IP",
            "uv run pitwall game set ac:ps5 --console-ip <console IP>",
        ),
        (
            _selected("gt7:ps4", gt7={"enabled": True}),
            "info",
            "no console IP: Pitwall searches the network for the console",
            "--console-ip <PS5 IP>",
        ),
        (_selected("f1_25:ps5"), "ok", f"F1 25 (PS5) - Tested live; input on (UDP {UDP_PORT})", ""),
        (
            _selected("ac:ps4", ac={"enabled": True, "console_ip": "192.168.1.50"}),
            "ok",
            "Assetto Corsa (PS4) - Built from community docs; input on (contacts 192.168.1.50)",
            "",
        ),
    ],
)
def test_game_check_rows(repo: Path, sections: dict[str, Any], status: str, detail: str, fix: str) -> None:
    _store(repo, sections)
    report = run(repo, Fake())
    c = by_id(report)["game"]
    assert (c.status, c.title) == (status, "Game"), c
    assert detail in c.detail and fix in c.fix, c
    format_text(report).encode("ascii")  # menu paths stay ASCII in the text report


def test_game_mismatch_from_a_running_server(repo: Path) -> None:
    _store(repo, _selected("gt7:ps5", gt7={"enabled": True, "console_ip": "192.168.1.100"}))
    fake = Fake()
    fake.http["/api/health"] = _health()
    rows = [
        {"key": "f1", "enabled": True, "port": UDP_PORT, "listening": True, "listens": True},
        {"key": "gt7", "enabled": True, "port": 33740, "listening": True, "console_ip": "192.168.1.100"},
    ]
    fake.http["/api/integrations"] = HttpReply(200, json.dumps(rows).encode())
    state = {
        "selected": {"id": "gt7:ps5", "since_unix": 1.0, "source": "dashboard"},
        "detected": {"entry_id": "f1_25:ps5", "adapter_game": "f1_25", "real": True, "status": "live"},
        "mismatch": {
            "kind": "game",
            "selected_id": "gt7:ps5",
            "detected_id": "f1_25:ps5",
            "text": "Receiving F1 25, but Gran Turismo 7 (PS5) is selected.",
        },
    }
    fake.http["/api/game"] = HttpReply(200, json.dumps(state).encode())
    report = run(repo, fake)
    c = by_id(report)["game"]
    assert c.status == "warn" and c.detail == "Receiving F1 25, but Gran Turismo 7 (PS5) is selected."
    assert c.fix == "uv run pitwall game set f1_25:ps5"
    assert report.to_dict()["game"] == {
        "selected": "gt7:ps5",
        "label": "Gran Turismo 7",
        "support": "live_validated",  # GT7 on PS5: validated live on 2026-10-11
        "integration": "gt7",
        "detected": "f1_25:ps5",
        "mismatch": "game",
    }
    assert any(u.endswith("/api/game") for u in fake.http_calls)


def test_an_older_server_falls_back_to_the_settings_file(repo: Path) -> None:
    _store(repo, _selected("forza_motorsport:pc", forza={"enabled": True}))
    fake = Fake()
    fake.http["/api/health"] = _health("no_data", packets=0)
    fake.http["/api/game"] = HttpReply(404, b'{"detail":"Not Found"}')
    report = run(repo, fake)
    c = by_id(report)["game"]
    assert c.status == "ok" and c.detail.startswith("Forza Motorsport (2023) on PC - Built from community docs")
    game = report.to_dict()["game"]
    assert game["selected"] == "forza_motorsport:pc" and game["detected"] is None and game["mismatch"] is None
    t = by_id(report)["telemetry"]
    assert t.status == "info" and "Data Out telemetry" in t.fix and "port 5301" in t.fix  # the selected game's way
    format_text(report).encode("ascii")


def test_game_block_without_a_selection(repo: Path) -> None:
    data = run(repo, Fake()).to_dict()
    assert data["schema"] == 1
    assert data["game"] == {
        "selected": None,
        "label": None,
        "support": None,
        "integration": None,
        "detected": None,
        "mismatch": None,
    }


# --------------------------------------------------------------------------------------------- updates
# --- lane install ---
def _cache(repo: Path, **kw: Any) -> None:
    data = {"schema": 1, "checked_unix": 1_000_000.0, "ok_unix": 1_000_000.0, "error": None, "releases": []}
    data.update(kw)
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / "update_check.json").write_text(json.dumps(data), encoding="utf-8")


def test_update_check_reads_only_the_cache(repo: Path) -> None:
    from pitwall.doctor import check_update

    fake = Fake()
    report = run(repo, fake)
    assert by_id(report)["update"].status == "info" and by_id(report)["update"].detail == "not checked yet"
    assert by_id(report)["update"].fix == "uv run pitwall update --check"
    assert all(u.startswith("http://127.0.0.1:") for u in fake.http_calls)  # the doctor never asks GitHub
    (repo / "RELEASE.txt").write_text("Pitwall v0.2.0\n", encoding="utf-8")
    rel = {"version": "v0.3.0", "published_at": "2026-10-12T09:00:00Z", "prerelease": False, "notes": [], "url": ""}
    _cache(repo, releases=[rel])
    ctx = doctor._Ctx(settings(repo), host(repo), fake.probes(), repo, False, {}, None)
    c = check_update(ctx, now=1_000_000.0 + 3 * 3600)
    assert c.status == "info" and c.detail == "Pitwall v0.3.0 is available (you have v0.2.0; checked 3 h ago)"
    assert c.fix == f'cd "{repo}" && uv run pitwall update'
    _cache(repo, releases=[{**rel, "version": "v0.2.0"}])
    c = check_update(ctx, now=1_000_000.0 + 120)
    assert c.status == "ok" and c.detail == "up to date (v0.2.0; checked 2 min ago)"
    _cache(repo, error="Couldn't reach GitHub (timed out).", checked_unix=1_000_000.0)
    c = check_update(ctx, now=1_000_000.0 + 5)
    assert c.status == "info" and c.detail.startswith("last check failed: Couldn't reach GitHub (timed out).")
    # a failed check after a good one that found an update: the update stays reported
    _cache(repo, error="Couldn't reach GitHub (timed out).", releases=[rel])
    c = check_update(ctx, now=1_000_000.0 + 5)
    assert c.detail.startswith("Pitwall v0.3.0 is available (you have v0.2.0); last check failed: Couldn't reach")
    assert c.fix == f'cd "{repo}" && uv run pitwall update'
    format_text(run(repo, fake)).encode("ascii")


# --- end lane install ---


# --------------------------------------------------------------------------------------------- lane handsfree
def test_windows_speech_input_via_sherpa_onnx(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The voice extra installs sherpa-onnx on Windows: Parakeet on the CPU, its model downloaded on first use."""
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    fake = _windows_fake()
    fake.modules["sherpa_onnx"] = True
    monkeypatch.setattr(doctor, "sherpa_model_state", lambda _s: (repo / "stt" / "m", False))
    checks = by_id(run(repo, fake, host=_win(repo)))
    assert checks["voice_stt"].status == "ok"
    assert "downloads the first time a radio connects" in checks["voice_stt"].detail
    assert checks["voice_handsfree"].status == "info" and checks["voice_handsfree"].detail.startswith("available")
    monkeypatch.setattr(doctor, "sherpa_model_state", lambda _s: (repo / "stt" / "m", True))
    stt = by_id(run(repo, fake, host=_win(repo)))["voice_stt"]
    assert stt.status == "ok" and stt.detail.startswith("Parakeet (English) via sherpa-onnx on the CPU: model ready")


def test_windows_speech_model_offline_and_own_folder(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _windows_fake()
    fake.modules["sherpa_onnx"] = True
    monkeypatch.setattr(doctor, "sherpa_model_state", lambda s: (s.stt_sherpa_dir or repo / "stt", False))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    stt = by_id(run(repo, fake, host=_win(repo)))["voice_stt"]
    assert stt.status == "warn" and "HF_HUB_OFFLINE" in stt.detail and "PITWALL_STT_SHERPA_DIR" in stt.fix
    own = settings(repo, stt_sherpa_dir=repo / "my-model")
    stt = by_id(run(repo, fake, own, host=_win(repo)))["voice_stt"]
    assert stt.status == "warn" and "PITWALL_STT_SHERPA_DIR=" in stt.detail and "tokens.txt" in stt.fix


def test_sherpa_model_state_checks_sizes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pitwall.voice.stt_sherpa import CATALOGUE, ModelFile, SherpaModel

    tiny = SherpaModel("tiny", "r/r", "0" * 40, "tiny", (ModelFile("tokens", "tokens.txt", 3, "0" * 64),), "x", "en")
    monkeypatch.setitem(CATALOGUE, "tiny", tiny)
    folder = repo / "own"
    folder.mkdir()
    s = settings(repo, stt_sherpa_dir=folder, stt_sherpa_model="tiny")
    assert doctor.sherpa_model_state(s) == (folder, False)
    (folder / "tokens.txt").write_bytes(b"abc")
    assert doctor.sherpa_model_state(s) == (folder, True)


def test_handsfree_check_follows_the_switch_and_speech_input(repo: Path) -> None:
    build_react(repo)
    ready_voice_and_token(repo)
    assert by_id(run(repo, Fake()))["voice_handsfree"].detail.startswith("available")
    off = by_id(run(repo, Fake(), settings(repo, voice_handsfree=False)))["voice_handsfree"]
    assert off.status == "info" and off.detail == "off (PITWALL_VOICE_HANDSFREE=false)"
    none = by_id(run(repo, Fake(), settings(repo, stt_engine="none")))["voice_handsfree"]
    assert none.detail == "needs speech recognition (see Speech input)"
    fake = Fake()
    fake.modules = {}
    sherpa = by_id(run(repo, fake, settings(repo, stt_engine="sherpa")))["voice_stt"]
    assert sherpa.status == "warn" and sherpa.fix == "uv sync --all-extras"  # asked for, not installed


# --------------------------------------------------------------------------------------------- ACC (shared memory)
def test_acc_is_info_off_windows_and_never_probed(repo: Path) -> None:
    fake = Fake()
    fake.acc_pages = "present"  # would be wrong on a Mac: the check must not even look
    report = run(repo, fake)
    c = by_id(report)["acc"]
    assert (c.status, c.title) == ("info", "ACC")
    assert "Windows PC that runs it" in c.detail and "this Mac" in c.detail and "run Pitwall on that PC" in c.fix
    assert "udp_acc" not in by_id(report)  # no port, no IP: never a UDP check


@pytest.mark.parametrize(
    ("sections", "pages", "status", "detail", "fix"),
    [
        ({}, "absent", "info", "ACC input is off; ACC is not running", "uv run pitwall game set acc"),
        ({}, "running", "info", "ACC input is off; ACC is running", "uv run pitwall game set acc"),
        ({}, "present", "info", "ACC input is off; ACC's shared memory pages exist but are not changing", "game set"),
        (_selected("acc:pc"), "absent", "info", "ACC input is on; ACC is not running", "uv run pitwall serve"),
        ({"integrations": {"acc": {"enabled": True}}}, "running", "info", "ACC input is on; ACC is running", "serve"),
        (_selected("acc:pc"), "present", "info", "or closed while another app such as SimHub keeps them", "serve"),
        (_selected("acc:pc"), "denied: [Errno 5] access denied", "warn", "running as administrator", "same way"),
        (_selected("acc:pc"), "error: boom", "info", "could not be checked (error: boom)", "serve"),
    ],
)
def test_acc_on_windows_without_a_server(
    repo: Path, sections: dict[str, Any], pages: str, status: str, detail: str, fix: str
) -> None:
    _store(repo, sections)
    fake = Fake()
    fake.acc_pages = pages
    c = by_id(run(repo, fake, host=host(repo, "Windows", "AMD64")))["acc"]
    assert (c.status, c.detail.startswith(detail) or detail in c.detail, fix in c.fix) == (status, True, True), c
    if pages == "present":  # pages alone never prove that ACC runs (another app may keep them after it quit)
        assert "ACC is running" not in c.detail, c


@pytest.mark.parametrize(
    ("reader", "extra", "status", "detail"),
    [
        (
            {"state": "reading", "message": "Reading ACC on this PC \u00b7 60 pages/s."},
            {},
            "ok",
            "Reading ACC on this PC - 60",
        ),
        (
            {
                "state": "waiting",
                "message": "ACC is paused: Pitwall reads it again when you drive on.",
                "last_rx_s_ago": 42,
            },
            {},
            "info",
            "ACC is paused: Pitwall reads it again when you drive on; last snapshot 42 s ago",
        ),
        (
            {"state": "not_running", "message": "ACC is not running on this PC (Pitwall looks for it every 2 s)."},
            {},
            "info",
            "not running",
        ),
        ({"state": "error", "message": "Can't read ACC's shared memory: access denied."}, {}, "warn", "access denied"),
        ({"state": "off", "message": "Off"}, {"active": False, "enabled": False}, "info", "ACC input is off"),
    ],
)
def test_acc_on_windows_from_a_running_server(
    repo: Path, reader: dict[str, Any], extra: dict[str, Any], status: str, detail: str
) -> None:
    fake = Fake()
    fake.acc_pages = "present"
    fake.http["/api/health"] = _health("no_data")
    row = {"key": "acc", "enabled": True, "active": True, "listens": False, "error": None, "reader": reader, **extra}
    rows = [{"key": "f1", "enabled": True, "port": UDP_PORT, "listening": True, "listens": True}, row]
    fake.http["/api/integrations"] = HttpReply(200, json.dumps(rows).encode())
    report = run(repo, fake, host=host(repo, "Windows", "AMD64"))
    c = by_id(report)["acc"]
    assert (c.status, detail in c.detail) == (status, True), c
    assert "udp_acc" not in by_id(report)
    format_text(report).encode("ascii")


def test_acc_game_check(repo: Path) -> None:
    _store(repo, _selected("acc:pc"))
    mac = by_id(run(repo, Fake()))["game"]
    assert mac.status == "warn" and "only on the Windows PC that runs it" in mac.detail
    assert "install Pitwall on that PC" in mac.fix
    pc = by_id(run(repo, Fake(), host=host(repo, "Windows", "AMD64")))["game"]
    assert pc.status == "ok", pc  # selected = on: the reader runs for the selected game
    assert pc.detail.endswith("input on (reads ACC's shared memory on this PC)") and "Partial" in pc.detail
