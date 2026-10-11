"""``scripts/install/install.ps1`` on Windows (Windows PowerShell 5.1): syntax, refusals and verification, with a
``uv.cmd`` stub. The full install (real uv, real zip) is the release workflow's Windows ``verify`` job, and the
one-line ``irm | iex`` command is its ``installer-smoke`` job; neither runs here.

Every run uses ``-FromZip`` or a pinned old ``-Version``, so nothing contacts the network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.install_support import release_zip, sha_line

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install" / "install.ps1"
POWERSHELL = shutil.which("powershell") if sys.platform == "win32" else None

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="Windows PowerShell only")

UV_CMD = '@echo off\r\necho uv %* >> "%FAKE_LOG_DIR%\\uv.log"\r\nexit /b 1\r\n'


def test_ascii_only() -> None:
    SCRIPT.read_bytes().decode("ascii")  # Windows PowerShell 5.1 reads a file without a BOM as ANSI


@pytest.fixture
def box(tmp_path: Path) -> dict[str, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv.cmd").write_text(UV_CMD, encoding="ascii", newline="")
    logs = tmp_path / "logs"
    logs.mkdir()
    return {"bin": bin_dir, "logs": logs, "install": tmp_path / "Pitwall", "tmp": tmp_path}


def run_file(box: dict[str, Path], *args: str) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    env = dict(os.environ)
    env["PATH"] = str(box["bin"]) + os.pathsep + env.get("PATH", "")
    env["FAKE_LOG_DIR"] = str(box["logs"])
    env["PITWALL_HTTP_PORT"] = "8833"
    env["PITWALL_RELEASES_API"] = "http://127.0.0.1:9/api"
    cmd = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)]
    cmd += ["-InstallHome", str(box["install"]), *args]
    r = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300, check=False)
    print(r.stdout, r.stderr)  # shown in full when a test fails (assertion messages are shortened)
    return r


def write_zip(box: dict[str, Path], tag: str, *, sha: str | None = None, **kw: object) -> Path:
    data = release_zip(tag, **kw)  # type: ignore[arg-type]
    z = box["tmp"] / f"pitwall-{tag}.zip"
    z.write_bytes(data)
    (box["tmp"] / f"{z.name}.sha256").write_text(sha or sha_line(data, z.name), encoding="ascii")
    return z


def test_parses_without_errors() -> None:
    assert POWERSHELL is not None
    ps = (
        "$e = $null; $null = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT}', [ref]$null, [ref]$e); if ($e.Count) {{ $e | ForEach-Object {{ $_.ToString() }}; exit 1 }}"
    )
    r = subprocess.run([POWERSHELL, "-NoProfile", "-Command", ps], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr


def test_unpacks_then_reports_a_failed_uv_sync(box: dict[str, Path]) -> None:
    z = write_zip(box, "v0.2.0-test.1")
    r = run_file(box, "-FromZip", str(z), "-Yes", "-Service", "no")
    assert r.returncode == 1, r.stdout + r.stderr
    vdir = box["install"] / "pitwall-v0.2.0-test.1"
    assert (vdir / "RELEASE.txt").is_file() and not (vdir / ".pitwall-ready").exists()
    assert "sync --locked --all-extras" in (box["logs"] / "uv.log").read_text()
    assert not (box["install"] / ".install.lock").exists()
    assert not list(box["install"].glob(".staging-*"))
    assert z.exists()


@pytest.mark.parametrize(
    "case",
    ["sha mismatch", "zip slip", "wrong prefix", "duplicate"],
)
def test_verification_failures_exit_5(box: dict[str, Path], case: str) -> None:
    tag = "v0.2.0-test.1"
    if case == "sha mismatch":
        z = write_zip(box, tag, sha="0" * 64 + f"  pitwall-{tag}.zip\n")
    elif case == "zip slip":
        z = write_zip(box, tag, extra=[(f"pitwall-{tag}/../evil.txt", b"x", 0o644)])
    elif case == "wrong prefix":
        z = write_zip(box, tag, extra=[("other/x.txt", b"x", 0o644)])
    else:
        z = write_zip(box, tag, duplicate=True)
    r = run_file(box, "-FromZip", str(z), "-Yes", "-Service", "no")
    assert r.returncode == 5, (case, r.stdout, r.stderr)
    assert not (box["install"] / f"pitwall-{tag}").exists()
    assert not (box["tmp"] / "evil.txt").exists()
    assert not (box["install"] / ".install.lock").exists()


def test_too_old_and_bad_input_exit_2(box: dict[str, Path]) -> None:
    r = run_file(box, "-Version", "v0.1.0", "-Yes")
    assert r.returncode == 2, r.stdout + r.stderr
    r = run_file(box, "-Version", "0.2.0", "-Yes")
    assert r.returncode == 2, r.stdout + r.stderr


def test_script_block_form_never_closes_the_window(box: dict[str, Path]) -> None:
    """Run the way `irm | iex` / [scriptblock]::Create runs it: no `exit`, the code lands in $LASTEXITCODE."""
    assert POWERSHELL is not None
    ps = (
        f"& ([scriptblock]::Create([IO.File]::ReadAllText('{SCRIPT}'))) -InstallHome '{box['install']}' "
        "-Version v0.1.0 -Yes; Write-Output ('still here, code=' + $LASTEXITCODE)"
    )
    r = subprocess.run(
        [POWERSHELL, "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=120, check=False
    )
    assert "still here, code=2" in r.stdout, r.stdout + r.stderr
