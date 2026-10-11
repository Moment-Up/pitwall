"""Staging a release: SHA-256, zip safety, exec bits, resume and skip. Downloads and ``uv`` are fakes."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from pitwall.install.layout import EXIT_VERIFY, InstallError
from pitwall.install.stage import StageDeps, safe_extract, stage_release, verify_sha256
from tests.install_support import release_zip, sha_line

TAG = "v0.2.0"


class Fake:
    def __init__(self, zip_bytes: bytes, sha: str, uv_code: int = 0) -> None:
        self.zip_bytes = zip_bytes
        self.sha = sha
        self.uv_code = uv_code
        self.downloads: list[str] = []
        self.runs: list[list[str]] = []
        self.envs: list[dict[str, str]] = []

    def download(self, url: str, dest: Path, echo: object) -> None:
        self.downloads.append(url)
        dest.write_bytes(self.zip_bytes if url.endswith(".zip") else self.sha.encode())

    def run(self, cmd: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, str]:
        self.runs.append(cmd)
        self.envs.append(env)
        if cmd[1:2] == ["sync"]:
            (cwd / ".venv").mkdir(exist_ok=True)
            return self.uv_code, "uv output"
        return 0, ""

    def deps(self) -> StageDeps:
        return StageDeps(run=self.run, download=self.download, echo=lambda _m: None, uv="/fake/uv")


def good() -> Fake:
    data = release_zip(TAG)
    return Fake(data, sha_line(data, f"pitwall-{TAG}.zip"))


def test_stage_downloads_verifies_unpacks_and_marks_ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIRTUAL_ENV", "/elsewhere/.venv")
    f = good()
    vdir = stage_release(tmp_path, TAG, f.deps())
    assert vdir == tmp_path / f"pitwall-{TAG}"
    assert [u.rsplit("/", 1)[1] for u in f.downloads] == [f"pitwall-{TAG}.zip.sha256", f"pitwall-{TAG}.zip"]
    assert f.runs[0] == ["/fake/uv", "sync", "--locked", "--all-extras"]
    assert f.runs[1][1:] == ["-c", "import pitwall.api.app, pitwall.core.runtime"]
    assert all("VIRTUAL_ENV" not in e for e in f.envs)
    ready = json.loads((vdir / ".pitwall-ready").read_text())
    assert ready["tag"] == TAG and len(ready["sha256"]) == 64
    if sys.platform != "win32":
        assert (vdir / "scripts" / "pitwall-service.sh").stat().st_mode & stat.S_IXUSR
        assert not (vdir / "RELEASE.txt").stat().st_mode & stat.S_IXUSR
    assert not (tmp_path / "downloads").exists() and not list(tmp_path.glob(".staging-*"))
    # again: already ready, nothing is downloaded or run
    f2 = good()
    assert stage_release(tmp_path, TAG, f2.deps()) == vdir
    assert f2.downloads == [] and f2.runs == []


def test_failed_uv_sync_resumes_next_time(tmp_path: Path) -> None:
    f = good()
    f.uv_code = 1
    with pytest.raises(InstallError, match="uv sync failed"):
        stage_release(tmp_path, TAG, f.deps())
    vdir = tmp_path / f"pitwall-{TAG}"
    assert vdir.is_dir() and not (vdir / ".pitwall-ready").exists()
    f2 = good()
    stage_release(tmp_path, TAG, f2.deps())
    assert f2.downloads == []  # resumed, not downloaded again
    assert json.loads((vdir / ".pitwall-ready").read_text())["sha256"] is None


@pytest.mark.parametrize(
    ("case", "kw"),
    [
        ("zip slip", {"extra": [(f"pitwall-{TAG}/../evil.txt", b"x", 0o644)]}),
        ("absolute", {"extra": [("/tmp/pitwall-evil.txt", b"x", 0o644)]}),
        ("windows drive", {"extra": [("C:/evil.txt", b"x", 0o644)]}),
        ("symlink", {"symlink": f"pitwall-{TAG}/link"}),
        ("wrong prefix", {"extra": [("other/x.txt", b"x", 0o644)]}),
        ("duplicate", {"duplicate": True}),
    ],
)
def test_unsafe_zips_are_refused(tmp_path: Path, case: str, kw: dict[str, object]) -> None:
    data = release_zip(TAG, **kw)  # type: ignore[arg-type]
    f = Fake(data, sha_line(data, f"pitwall-{TAG}.zip"))
    with pytest.raises(InstallError) as e:
        stage_release(tmp_path, TAG, f.deps())
    assert e.value.code == EXIT_VERIFY, case
    assert not (tmp_path / f"pitwall-{TAG}").exists()
    assert not (tmp_path / "evil.txt").exists() and not Path("/tmp/pitwall-evil.txt").exists()
    assert not list(tmp_path.glob(".staging-*"))
    assert f.runs == []


def test_sha256_mismatch_and_wrong_name(tmp_path: Path) -> None:
    z = tmp_path / f"pitwall-{TAG}.zip"
    z.write_bytes(release_zip(TAG))
    sha = tmp_path / f"{z.name}.sha256"
    sha.write_text("0" * 64 + f"  {z.name}\n")
    with pytest.raises(InstallError) as e:
        verify_sha256(z, sha, TAG)
    assert e.value.code == EXIT_VERIFY and "mismatch" in e.value.message
    sha.write_text(sha_line(z.read_bytes(), "pitwall-v9.9.9.zip"))
    with pytest.raises(InstallError) as e:
        verify_sha256(z, sha, TAG)
    assert e.value.code == EXIT_VERIFY and "does not name" in e.value.message
    sha.write_text(sha_line(z.read_bytes(), z.name).replace("  ", " *"))  # binary-mode marker is fine
    assert len(verify_sha256(z, sha, TAG)) == 64


def test_from_zip_is_never_deleted_and_must_be_named_for_the_tag(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    data = release_zip(TAG)
    z = src / f"pitwall-{TAG}.zip"
    z.write_bytes(data)
    (src / f"{z.name}.sha256").write_text(sha_line(data, z.name))
    home = tmp_path / "home"
    f = good()
    stage_release(home, TAG, f.deps(), from_zip=z)
    assert z.exists() and f.downloads == []
    other = src / "pitwall-v0.3.0.zip"
    other.write_bytes(data)
    with pytest.raises(InstallError):
        stage_release(home, "v0.3.0", f.deps(), from_zip=z)


def test_an_old_release_without_install_finish_is_refused(tmp_path: Path) -> None:
    data = release_zip(TAG, managed=False)
    f = Fake(data, sha_line(data, f"pitwall-{TAG}.zip"))
    with pytest.raises(InstallError) as e:
        stage_release(tmp_path, TAG, f.deps())
    assert e.value.code == 2 and not (tmp_path / f"pitwall-{TAG}").exists()


def test_leftover_staging_without_data_is_removed(tmp_path: Path) -> None:
    junk = tmp_path / ".staging-v0.1.0-123"
    (junk / "pitwall-v0.1.0").mkdir(parents=True)
    keep = tmp_path / ".staging-v0.1.0-456"
    (keep / "pitwall-v0.1.0" / "data").mkdir(parents=True)
    stage_release(tmp_path, TAG, good().deps())
    assert not junk.exists() and keep.exists()


def test_safe_extract_keeps_everything_inside(tmp_path: Path) -> None:
    z = tmp_path / "a.zip"
    z.write_bytes(release_zip(TAG))
    out = safe_extract(z, f"pitwall-{TAG}", tmp_path / "x")
    assert (out / "RELEASE.txt").read_text().startswith(f"Pitwall {TAG}")
