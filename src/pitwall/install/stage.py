"""Stage a release next to the current one: download, SHA-256, safe unzip, ``uv sync``, ``.pitwall-ready``.

The same steps as install.sh / install.ps1 (steps 7-9), in Python for ``pitwall update``. A folder is ready when
it has ``.pitwall-ready``; staging a ready folder again does nothing, and a folder without the marker (an earlier
run stopped during ``uv sync``) is resumed. Downloads and the ``.staging-*`` area are ours and are removed; a
version folder, ``data/`` and any ``.env`` never are.

SHA-256 from the same release proves the download is complete and unchanged on the way, not who made it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from pitwall.install.github import download_url, zip_name
from pitwall.install.layout import (
    EXIT_ERROR,
    EXIT_NEEDS_USER,
    EXIT_VERIFY,
    MIN_FREE_BYTES,
    READY_MARKER,
    InstallError,
    free_bytes,
    version_dir,
)

IMPORT_CHECK = "import pitwall.api.app, pitwall.core.runtime"
Echo = Callable[[str], None]


# ------------------------------------------------------------------------------------------- verification
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(zip_path: Path, sha_path: Path, tag: str) -> str:
    """Check ``pitwall-<tag>.zip.sha256``: it must name exactly ``pitwall-<tag>.zip`` and match. Exit 5 if not."""
    want_name = zip_name(tag)
    try:
        text = sha_path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as e:
        raise InstallError(EXIT_VERIFY, f"cannot read {sha_path.name}: {e}") from e
    parts = text.split()
    if len(parts) != 2 or parts[1].lstrip("*") != want_name or len(parts[0]) != 64:
        raise InstallError(EXIT_VERIFY, f"{sha_path.name} does not name {want_name}: refusing to install it")
    digest = sha256_file(zip_path)
    if digest.lower() != parts[0].lower():
        raise InstallError(EXIT_VERIFY, f"SHA-256 mismatch for {want_name}: the download is damaged or not the release")
    return digest


def check_zip(zf: zipfile.ZipFile, prefix: str) -> list[zipfile.ZipInfo]:
    """Every entry under ``<prefix>/``, relative, no ``..``, no symlinks, no duplicates. Exit 5 otherwise."""
    seen: set[str] = set()
    infos = zf.infolist()
    if not infos:
        raise InstallError(EXIT_VERIFY, "the zip is empty")
    for zi in infos:
        name = zi.filename
        p = PurePosixPath(name)
        if name.startswith(("/", "\\")) or "\\" in name or (len(name) > 1 and name[1] == ":") or p.is_absolute():
            raise InstallError(EXIT_VERIFY, f"unsafe path in the zip (absolute): {name!r}")
        if ".." in p.parts:
            raise InstallError(EXIT_VERIFY, f"unsafe path in the zip (..): {name!r}")
        if not p.parts or p.parts[0] != prefix:
            raise InstallError(EXIT_VERIFY, f"unexpected path in the zip (not under {prefix}/): {name!r}")
        if stat.S_ISLNK(zi.external_attr >> 16):
            raise InstallError(EXIT_VERIFY, f"the zip holds a symbolic link: {name!r}")
        key = name.rstrip("/")
        if key in seen:
            raise InstallError(EXIT_VERIFY, f"duplicate entry in the zip: {name!r}")
        seen.add(key)
    return infos


def safe_extract(zip_path: Path, prefix: str, dest: Path) -> Path:
    """Unzip into ``dest`` (which must be empty or absent) after ``check_zip``; restore exec bits."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        zf = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as e:
        raise InstallError(EXIT_VERIFY, f"{zip_path.name} is not a readable zip: {e}") from e
    with zf:
        infos = check_zip(zf, prefix)
        root = dest.resolve()
        for zi in infos:
            target = (root / zi.filename).resolve()
            if root not in target.parents and target != root:
                raise InstallError(EXIT_VERIFY, f"unsafe path in the zip: {zi.filename!r}")
            if zi.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(zi) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            mode = (zi.external_attr >> 16) & 0o777
            if sys.platform != "win32":
                target.chmod(0o755 if mode & 0o111 else 0o644)
    out_dir = dest / prefix
    if not out_dir.is_dir():
        raise InstallError(EXIT_VERIFY, f"the zip has no {prefix}/ folder")
    return out_dir


# ------------------------------------------------------------------------------------------- tools
def find_uv() -> str | None:
    """uv on PATH, else where its installers put it."""
    found = shutil.which("uv")
    if found:
        return found
    home = Path.home()
    exe = "uv.exe" if sys.platform == "win32" else "uv"
    candidates = [home / ".local" / "bin" / exe, home / ".cargo" / "bin" / exe]
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidates.append(Path(local) / "Microsoft" / "WinGet" / "Links" / exe)
    return next((str(c) for c in candidates if c.is_file()), None)


def venv_bin(folder: Path, name: str) -> Path:
    if sys.platform == "win32":
        return folder / ".venv" / "Scripts" / f"{name}.exe"
    return folder / ".venv" / "bin" / name


def is_ready(folder: Path) -> bool:
    return (folder / READY_MARKER).is_file()


def write_ready(folder: Path, tag: str, digest: str | None) -> None:
    data = {"tag": tag, "sha256": digest, "unix": round(time.time(), 3)}
    (folder / READY_MARKER).write_text(json.dumps(data) + "\n", encoding="utf-8")


def clean_env() -> dict[str, str]:
    """The environment for ``uv sync`` in another folder: never an outer virtual environment."""
    env = dict(os.environ)
    for k in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"):
        env.pop(k, None)
    return env


# ------------------------------------------------------------------------------------------- staging
Runner = Callable[[list[str], Path, dict[str, str]], tuple[int, str]]


def _run(cmd: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, str]:
    r = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return r.returncode, r.stdout.decode("utf-8", "replace")


def _download(url: str, dest: Path, echo: Echo) -> None:
    import httpx

    from pitwall.install.github import CONNECT_TIMEOUT_S, READ_TIMEOUT_S, request_headers

    headers = request_headers()
    headers["Accept"] = "application/octet-stream"
    part = dest.with_name(dest.name + ".part")
    timeout = httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
    try:
        with (
            httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client,
            client.stream("GET", url) as r,
        ):
            if r.status_code != 200:
                raise InstallError(EXIT_ERROR, f"download failed: HTTP {r.status_code} for {url}")
            with part.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
    except httpx.HTTPError as e:
        part.unlink(missing_ok=True)
        raise InstallError(EXIT_ERROR, f"download failed ({type(e).__name__}): {url}") from e
    part.replace(dest)


@dataclass(slots=True)
class StageDeps:
    """Side effects of staging (fakes in tests)."""

    run: Runner = _run
    download: Callable[[str, Path, Echo], None] = _download
    echo: Echo = print
    uv: str | None = field(default_factory=find_uv)


def clean_leftovers(home: Path) -> None:
    """Remove ``.staging-*`` folders (ours) that hold no ``data/`` folder; never anything else."""
    for p in home.glob(".staging-*"):
        if p.is_dir() and not (p / "data").exists() and not any(p.glob("*/data")):
            shutil.rmtree(p, ignore_errors=True)


def install_packages(folder: Path, deps: StageDeps) -> None:
    """``uv sync --locked --all-extras`` in ``folder`` and the server import check."""
    if deps.uv is None:
        raise InstallError(
            EXIT_NEEDS_USER, "uv is not installed: https://docs.astral.sh/uv/getting-started/installation/"
        )
    env = clean_env()
    code, out = deps.run([deps.uv, "sync", "--locked", "--all-extras"], folder, env)
    if code != 0:
        tail = "\n".join(out.strip().splitlines()[-15:])
        raise InstallError(EXIT_ERROR, f"uv sync failed in {folder} (exit {code}):\n{tail}")
    py = venv_bin(folder, "python")
    code, out = deps.run([str(py), "-c", IMPORT_CHECK], folder, env)
    if code != 0:
        tail = "\n".join(out.strip().splitlines()[-10:])
        raise InstallError(EXIT_ERROR, f"Pitwall installed in {folder}, but its server does not import:\n{tail}")


def stage_release(home: Path, tag: str, deps: StageDeps, *, from_zip: Path | None = None) -> Path:
    """Make ``<home>/pitwall-<tag>`` ready. The caller holds the install lock. Returns the version folder."""
    target = version_dir(home, tag)
    if is_ready(target):
        deps.echo(f"{target.name} is already installed (skipping the download).")
        return target
    clean_leftovers(home)
    digest: str | None = None
    if not target.exists():
        if free_bytes(home) < MIN_FREE_BYTES:
            raise InstallError(EXIT_NEEDS_USER, f"less than 2 GB free in {home}: free some space and try again")
        name = zip_name(tag)
        if from_zip is not None:
            zip_path, sha_path, downloads = from_zip, from_zip.with_name(from_zip.name + ".sha256"), None
            if from_zip.name != name:
                raise InstallError(EXIT_VERIFY, f"{from_zip.name} is not {name}")
        else:
            downloads = home / "downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            zip_path, sha_path = downloads / name, downloads / f"{name}.sha256"
            deps.echo(f"Downloading {name}…")
            deps.download(download_url(tag, f"{name}.sha256"), sha_path, deps.echo)
            deps.download(download_url(tag, name), zip_path, deps.echo)
            deps.echo(f"Downloaded {name} ({zip_path.stat().st_size / 1e6:.1f} MB)")
        deps.echo("Checking SHA-256…")
        digest = verify_sha256(zip_path, sha_path, tag)
        deps.echo("Checking SHA-256… OK")
        staging = home / f".staging-{tag}-{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            deps.echo("Unpacking…")
            extracted = safe_extract(zip_path, target.name, staging)
            if not (extracted / "src" / "pitwall" / "install" / "activate.py").is_file():
                raise InstallError(
                    2, f"{name} is older than the one-line installer: install it by hand (docs/install.md)"
                )
            if target.exists():
                raise InstallError(EXIT_ERROR, f"{target} appeared while unpacking: not replacing it")
            extracted.rename(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if downloads is not None:
            zip_path.unlink(missing_ok=True)
            sha_path.unlink(missing_ok=True)
            if downloads.is_dir() and not any(downloads.iterdir()):
                downloads.rmdir()
    else:
        deps.echo(f"Resuming the unfinished install in {target}")
    deps.echo("Installing Python packages (uv sync)…")
    install_packages(target, deps)
    write_ready(target, tag, digest)
    deps.echo("Installing Python packages (uv sync)… done")
    return target
