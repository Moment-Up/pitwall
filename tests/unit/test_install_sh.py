"""``scripts/install/install.sh`` under ``sh`` and ``dash`` against a fake GitHub on 127.0.0.1, with fake release
zips built here and a fake ``uv`` (``uv sync`` makes a stub ``.venv`` whose ``pitwall`` records its arguments).

Each run is a new session without a controlling terminal, as with ``curl ... | sh`` from a script (questions then
need ``--yes``). Nothing contacts the real network.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.install_support import FakeGitHub, fake_release, release_zip, serve, sha_line

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "install" / "install.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX installer")

SHELLS = [s for s in ("/bin/sh", "/bin/dash") if Path(s).exists()]

FAKE_UV = """#!/bin/sh
echo "uv $*" >> "$FAKE_LOG_DIR/uv.log"
if [ "$1" = sync ]; then
  [ -z "${VIRTUAL_ENV:-}" ] || { echo "VIRTUAL_ENV leaked" >> "$FAKE_LOG_DIR/uv.log"; exit 9; }
  mkdir -p .venv/bin
  printf '#!/bin/sh\\nexit 0\\n' > .venv/bin/python
  cat > .venv/bin/pitwall <<'EOF'
#!/bin/sh
{ pwd; for a in "$@"; do printf '%s\\n' "$a"; done; } > "$FAKE_LOG_DIR/pitwall.args"
exit 0
EOF
  chmod +x .venv/bin/python .venv/bin/pitwall
fi
exit "${FAKE_UV_EXIT:-0}"
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def box(tmp_path: Path) -> dict[str, Path]:
    home = tmp_path / "userhome"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8")
    uv.chmod(0o755)
    logs = tmp_path / "logs"
    logs.mkdir()
    return {"home": home, "bin": bin_dir, "logs": logs, "install": tmp_path / "Pitwall", "tmp": tmp_path}


def run(
    shell: str,
    box: dict[str, Path],
    gh: FakeGitHub | None,
    *args: str,
    uv: bool = True,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    path = [str(box["bin"])] if uv else []
    path += ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    env = {
        "PATH": os.pathsep.join(path),
        "HOME": str(box["home"]),
        "FAKE_LOG_DIR": str(box["logs"]),
        "PITWALL_HTTP_PORT": str(_free_port()),
        "LC_ALL": "C",
        "VIRTUAL_ENV": "/somewhere/else/.venv",  # must never reach `uv sync`
    }
    if gh is not None:
        env.update(gh.env())
    env.update(extra_env or {})
    return subprocess.run(
        [shell, str(SCRIPT), "--home", str(box["install"]), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        start_new_session=True,  # no controlling terminal: /dev/tty cannot be opened
        stdin=subprocess.DEVNULL,
        check=False,
    )


def finish_args(box: dict[str, Path]) -> list[str]:
    return (box["logs"] / "pitwall.args").read_text(encoding="utf-8").splitlines()


def standard_github() -> FakeGitHub:
    return FakeGitHub(
        releases=[
            fake_release("v0.3.0-rc.1", prerelease=True),
            fake_release("v0.2.0"),
            fake_release("v0.1.0", managed=False),
            fake_release("v0.2.1", assets=["pitwall-v0.2.1.zip"]),  # no .sha256: never chosen
        ]
    )


def assert_clean(box: dict[str, Path]) -> None:
    home = box["install"]
    if home.exists():
        left = [p.name for p in home.iterdir() if p.name.startswith((".staging-", ".install.lock", "downloads"))]
        assert left == [], left


@pytest.mark.parametrize("shell", SHELLS)
def test_installs_latest_stable_and_hands_over(shell: str, box: dict[str, Path]) -> None:
    with serve(standard_github()) as gh:
        r = run(shell, box, gh, "--yes", "--no-service")
    assert r.returncode == 0, r.stdout + r.stderr
    vdir = box["install"] / "pitwall-v0.2.0"
    assert (vdir / "RELEASE.txt").read_text().startswith("Pitwall v0.2.0")
    ready = json.loads((vdir / ".pitwall-ready").read_text())
    assert ready["tag"] == "v0.2.0" and len(ready["sha256"]) == 64 and ready["unix"] > 0
    mode = (vdir / "scripts" / "pitwall-service.sh").stat().st_mode
    assert mode & stat.S_IXUSR, "exec bit not restored"
    assert not (vdir / "RELEASE.txt").stat().st_mode & stat.S_IXUSR
    args = finish_args(box)
    assert Path(args[0]).resolve() == vdir.resolve()  # pitwall runs from the version folder (.env is read there)
    assert args[1:] == [
        "install-finish", "--home", str(box["install"]), "--version-dir", str(vdir),
        "--installer", "install.sh", "--yes", "--service", "no",
    ]  # fmt: skip
    uv_log = (box["logs"] / "uv.log").read_text()
    assert "uv sync --locked --all-extras" in uv_log and "VIRTUAL_ENV leaked" not in uv_log
    assert "Checking SHA-256... OK" in r.stdout
    assert_clean(box)
    assert not (box["install"] / "pitwall-v0.3.0-rc.1").exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_pre_release_and_rerun_skips_the_download(shell: str, box: dict[str, Path]) -> None:
    with serve(standard_github()) as gh:
        r = run(shell, box, gh, "--yes", "--pre", "--wait-idle", "5")
        assert r.returncode == 0, r.stdout + r.stderr
        assert (box["install"] / "pitwall-v0.3.0-rc.1" / ".pitwall-ready").is_file()
        assert finish_args(box)[-2:] == ["--wait-idle", "5"]
        downloads = [p for p in gh.requests if p.startswith("/download/")]
        assert len(downloads) == 2
        r2 = run(shell, box, gh, "--yes", "--pre")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "already installed" in r2.stdout
        assert len([p for p in gh.requests if p.startswith("/download/")]) == 2  # nothing downloaded again
    assert_clean(box)


@pytest.mark.parametrize("shell", SHELLS)
def test_resume_after_a_failed_uv_sync(shell: str, box: dict[str, Path]) -> None:
    with serve(standard_github()) as gh:
        r = run(shell, box, gh, "--yes", extra_env={"FAKE_UV_EXIT": "1"})
        assert r.returncode == 1 and "uv sync failed" in r.stderr
        vdir = box["install"] / "pitwall-v0.2.0"
        assert vdir.is_dir() and not (vdir / ".pitwall-ready").exists()
        r2 = run(shell, box, gh, "--yes")
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert "Resuming" in r2.stdout and (vdir / ".pitwall-ready").is_file()
    assert_clean(box)


BAD_ZIPS = {
    "sha mismatch": lambda: (release_zip("v0.2.0"), "0" * 64 + "  pitwall-v0.2.0.zip\n"),
    "sha names another file": lambda: (z := release_zip("v0.2.0"), sha_line(z, "pitwall-v9.9.9.zip")),
    "zip slip": lambda: (z := release_zip("v0.2.0", extra=[("pitwall-v0.2.0/../evil.txt", b"x", 0o644)]), sha_line(z, "pitwall-v0.2.0.zip")),
    "absolute path": lambda: (z := release_zip("v0.2.0", extra=[("/tmp/pitwall-evil.txt", b"x", 0o644)]), sha_line(z, "pitwall-v0.2.0.zip")),
    "symlink": lambda: (z := release_zip("v0.2.0", symlink="pitwall-v0.2.0/link"), sha_line(z, "pitwall-v0.2.0.zip")),
    "wrong prefix": lambda: (z := release_zip("v0.2.0", extra=[("other/x.txt", b"x", 0o644)]), sha_line(z, "pitwall-v0.2.0.zip")),
    "duplicate": lambda: (z := release_zip("v0.2.0", duplicate=True), sha_line(z, "pitwall-v0.2.0.zip")),
}  # fmt: skip


@pytest.mark.parametrize("shell", SHELLS)
@pytest.mark.parametrize("case", sorted(BAD_ZIPS))
def test_verification_failures_exit_5_and_leave_nothing(shell: str, case: str, box: dict[str, Path]) -> None:
    data, sha = BAD_ZIPS[case]()
    gh = FakeGitHub(releases=[fake_release("v0.2.0")])
    gh.releases[0].zip_bytes, gh.releases[0].sha_text = data, sha
    with serve(gh) as g:
        r = run(shell, box, g, "--yes")
    assert r.returncode == 5, (case, r.stdout, r.stderr)
    assert not (box["install"] / "pitwall-v0.2.0").exists()
    assert not (box["tmp"] / "evil.txt").exists() and not Path("/tmp/pitwall-evil.txt").exists()
    assert not (box["logs"] / "pitwall.args").exists()
    assert_clean(box)


@pytest.mark.parametrize("shell", SHELLS)
def test_too_old_release_exits_2(shell: str, box: dict[str, Path]) -> None:
    with serve(standard_github()) as gh:
        r = run(shell, box, gh, "--yes", "--version", "v0.1.0")
    assert r.returncode == 2 and "install v0.1.0 by hand" in r.stderr.replace("$TAG", "v0.1.0")
    assert not (box["install"] / "pitwall-v0.1.0").exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_missing_uv_without_a_terminal_exits_4(shell: str, box: dict[str, Path]) -> None:
    with serve(standard_github()) as gh:
        r = run(shell, box, gh, uv=False)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "no terminal" in r.stderr
    assert not (box["install"] / "pitwall-v0.2.0").exists()


@pytest.mark.parametrize("shell", SHELLS)
def test_yes_installs_uv_with_the_stub_installer(shell: str, box: dict[str, Path]) -> None:
    installer = (
        '#!/bin/sh\n[ "$UV_NO_MODIFY_PATH" = 1 ] || exit 7\nmkdir -p "$HOME/.local/bin"\n'
        f'cat > "$HOME/.local/bin/uv" <<"EOS"\n{FAKE_UV}EOS\nchmod +x "$HOME/.local/bin/uv"\n'
    )
    gh = standard_github()
    gh.files["/uv-install.sh"] = installer.encode()
    with serve(gh) as g:
        r = run(shell, box, g, "--yes", uv=False, extra_env={"PITWALL_INSTALL_UV_URL": f"{g.base}/uv-install.sh"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert (box["home"] / ".local" / "bin" / "uv").is_file()
    assert (box["install"] / "pitwall-v0.2.0" / ".pitwall-ready").is_file()
    assert not list(box["install"].glob(".uv-install-*"))


@pytest.mark.parametrize("shell", SHELLS)
def test_live_telemetry_exits_3_before_downloading(shell: str, box: dict[str, Path]) -> None:
    gh = standard_github()
    gh.health = {"version": "0.2.0", "connection": {"status": "live", "decode": {"a": 1}}, "replay": None}
    with serve(gh) as g:
        r = run(shell, box, g, "--yes", extra_env={"PITWALL_HTTP_PORT": str(g.port)})
        downloads = [p for p in g.requests if p.startswith("/download/")]
    assert r.returncode == 3, r.stdout + r.stderr
    assert "someone is driving" in r.stderr
    assert downloads == []


@pytest.mark.parametrize("shell", SHELLS)
def test_from_zip_needs_no_network(shell: str, box: dict[str, Path], tmp_path: Path) -> None:
    data = release_zip("v0.2.0-test.1")
    z = tmp_path / "pitwall-v0.2.0-test.1.zip"
    z.write_bytes(data)
    (tmp_path / "pitwall-v0.2.0-test.1.zip.sha256").write_text(sha_line(data, z.name))
    r = run(
        shell,
        box,
        None,
        "--yes",
        "--no-service",
        "--from-zip",
        str(z),
        extra_env={"PITWALL_RELEASES_API": "http://127.0.0.1:9/"},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert (box["install"] / "pitwall-v0.2.0-test.1" / ".pitwall-ready").is_file()
    assert z.exists()  # a --from-zip file is the caller's: never deleted


@pytest.mark.parametrize("shell", SHELLS)
def test_unsupported_platform_root_and_bad_urls_exit_2(shell: str, box: dict[str, Path]) -> None:
    fake = box["bin"]
    (fake / "uname").write_text('#!/bin/sh\n[ "$1" = -s ] && echo FreeBSD || echo amd64\n')
    (fake / "uname").chmod(0o755)
    r = run(shell, box, None, "--yes")
    assert r.returncode == 2 and "not supported" in r.stderr
    (fake / "uname").unlink()
    (fake / "id").write_text("#!/bin/sh\necho 0\n")
    (fake / "id").chmod(0o755)
    r = run(shell, box, None, "--yes")
    assert r.returncode == 2 and "root" in r.stderr
    (fake / "id").unlink()
    r = run(shell, box, None, "--yes", extra_env={"PITWALL_RELEASES_API": "http://example.com/api"})
    assert r.returncode == 2 and "https://" in r.stderr
    r = run(shell, box, None, "--version", "1.2.3")
    assert r.returncode == 2
    r = run(shell, box, None, "--bogus")
    assert r.returncode == 2


def test_truncated_download_runs_nothing(box: dict[str, Path], tmp_path: Path) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    cut = tmp_path / "cut.sh"
    cut.write_text(text[: text.index('main "$@"')], encoding="utf-8")
    r = subprocess.run(["/bin/sh", str(cut), "--yes"], capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    assert text.rstrip().endswith('main "$@"')


def test_shellcheck_if_present() -> None:
    sc = shutil.which("shellcheck")
    if sc is None:
        pytest.skip("shellcheck not installed (CI runs it)")
    r = subprocess.run([sc, "-s", "sh", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout
