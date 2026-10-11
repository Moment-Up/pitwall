"""Package a Pitwall release: ``pitwall-<version>.zip`` with the prebuilt dashboard, and its SHA-256.

The zip holds one folder, ``pitwall-<version>/``, with:

- Pitwall's source at the commit (``git archive HEAD``: tracked files only, so never ``data/``, ``.env`` or
  ``node_modules``);
- ``web-react/dist/``: the React dashboard, prebuilt for "/" (minified, no source maps), so people without a HeroUI
  Pro licence (and without Node.js) get the new dashboard;
- ``THIRD_PARTY_NOTICES.txt`` (``web-react/scripts/notices.mjs``, plus the licences of third-party data in the
  source tree) and ``RELEASE.txt`` (version, commit, dates).

Usage (after ``cd web-react && npm ci && npm run build:root``)::

    uv run python scripts/package_release.py --version v0.2.0 --out <dir>

It writes ``<dir>/pitwall-<version>.zip`` and ``<dir>/pitwall-<version>.zip.sha256`` and prints the SHA-256.

HeroUI Pro conditions (docs/releasing.md): the compiled dashboard ships only inside this full application archive,
minified, never with source maps, never with node_modules and never with a token. The script refuses to package when
dist was built for /next/, contains a ``*.map`` file or a ``sourceMappingURL``, or when a tracked file is ``.env``,
``data/``, ``node_modules`` or an ``.npmrc`` with credentials; and, when ``HEROUI_AUTH_TOKEN`` (or another npm token
variable) is set, when its value appears in any file of the zip.

Privacy and links: it also refuses when a ``.pwcap`` capture in the zip still holds a player's name or a LAN address
(``scripts/scrub_capture.py --check``, run in the project's environment with ``uv run``), and when ``docs/install.md``
at the commit lacks the "Install from a release" section that RELEASE.txt and the release notes link to.

Standard library only; runs on macOS, Linux and Windows (needs ``git``, ``node`` and ``uv`` on PATH). The source
part is the committed HEAD, so uncommitted changes are not included: the script refuses to run when tracked files are
modified or the dashboard's build inputs have untracked files (the dashboard would not match the commit), unless
``--allow-dirty``.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web-react"
DIST = WEB / "dist"
NOTICES_SCRIPT = WEB / "scripts" / "notices.mjs"
SCRUB_SCRIPT = ROOT / "scripts" / "scrub_capture.py"
INSTALL_DOC = "docs/install.md"
# RELEASE.txt and the release notes (release.yml) link to docs/install.md#install-from-a-release
INSTALL_SECTION_RE = re.compile(r"(?m)^## Install from a release[ \t]*$")

VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
LICENCE_FILE_RE = re.compile(r"^(licen[cs]e|copying|notice|copyright)([-._].*)?$", re.IGNORECASE)
NPMRC_SECRET_RE = re.compile(rb"(?im)^\s*[^#;\s]*(_authToken|_auth|_password|//[^\s=]*:_)\s*=")
ENV_FILE_RE = re.compile(r"^\.env(\..+)?$")
ENV_FILE_OK = {".env.example", ".env.sample", ".env.template"}
# Dashboard build inputs: an untracked or modified file here means dist was not built from the commit.
BUILD_INPUTS = (
    "web-react/src",
    "web-react/public",
    "web-react/index.html",
    "web-react/package.json",
    "web-react/package-lock.json",
    "web-react/vite.config.ts",
    "web-react/tsconfig.json",
)
TOKEN_ENV_VARS = ("HEROUI_AUTH_TOKEN", "NODE_AUTH_TOKEN", "NPM_TOKEN")
MIN_ZIP_TIME = 315532800  # 1980-01-01, the earliest time a zip entry can hold


class PackagingError(Exception):
    pass


@dataclass(slots=True)
class Entry:
    path: str  # repo-relative, POSIX
    data: bytes
    mode: int  # permission bits
    mtime: int


def info(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr, flush=True)


def run(cmd: list[str], *, cwd: Path = ROOT, show_stderr: bool = False) -> bytes:
    """Run a command and return its stdout; its stderr is shown live (show_stderr) or in the error."""
    try:
        r = subprocess.run(
            cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=None if show_stderr else subprocess.PIPE, check=False
        )
    except FileNotFoundError as e:
        raise PackagingError(f"{cmd[0]} not found on PATH ({e})") from e
    if r.returncode != 0:
        err = "" if show_stderr else r.stderr.decode("utf-8", "replace").strip()
        raise PackagingError(f"`{' '.join(cmd)}` failed (exit {r.returncode})" + (f":\n{err}" if err else ""))
    return r.stdout


def git(*args: str) -> str:
    return run(["git", "-C", str(ROOT), *args]).decode("utf-8").rstrip()


# ----------------------------------------------------------------------------------------------- checks


def check_version(version: str) -> None:
    if not VERSION_RE.match(version):
        raise PackagingError(f"--version {version!r} must look like v1.2.3 or v1.2.3-rc.1")


def check_worktree(allow_dirty: bool) -> bool:
    """True when the working tree matches HEAD for everything that goes into the zip."""
    tracked = [ln for ln in git("status", "--porcelain", "--untracked-files=no").splitlines() if ln.strip()]
    inputs = git("status", "--porcelain", "--untracked-files=all", "--", *BUILD_INPUTS).splitlines()
    untracked_inputs = [ln for ln in inputs if ln.startswith("??")]
    dirty = tracked + untracked_inputs
    if not dirty:
        return True
    listing = "\n  ".join(dirty[:20]) + ("\n  ..." if len(dirty) > 20 else "")
    if not allow_dirty:
        raise PackagingError(
            "the working tree differs from HEAD (the zip's source is HEAD, but the dashboard is built from the "
            f"working tree):\n  {listing}\nCommit or stash the changes, or pass --allow-dirty for a test package."
        )
    warn(f"packaging with uncommitted changes (--allow-dirty); RELEASE.txt says so:\n  {listing}")
    return False


def check_dist() -> list[Path]:
    """Validate web-react/dist and return its files (sorted)."""
    index = DIST / "index.html"
    if not index.is_file():
        raise PackagingError(
            "web-react/dist/index.html not found: build the dashboard first "
            "(cd web-react && npm ci && npm run build:root)"
        )
    html = index.read_text(encoding="utf-8")
    refs = re.findall(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""", html)
    local = [r for r in refs if not re.match(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", r, re.IGNORECASE)]
    if '"/next/' in html or any(r.startswith("/next/") for r in local):
        raise PackagingError("web-react/dist was built for /next/ (npm run build): rebuild with `npm run build:root`")
    if not any(r.startswith("/assets/") for r in local):
        raise PackagingError("web-react/dist/index.html loads nothing from /assets/: rebuild with `npm run build:root`")
    bad = [r for r in local if not r.startswith("/")]
    if bad:
        raise PackagingError(f"web-react/dist/index.html has relative asset URLs {bad[:3]}: build it for '/'")
    for ref in local:
        target = DIST / ref.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        if not target.is_file():
            raise PackagingError(f"web-react/dist/index.html references {ref}, which is not in dist (stale build?)")

    files = sorted((p for p in DIST.rglob("*") if not p.is_dir()), key=lambda p: p.relative_to(DIST).as_posix())
    maps = [p.relative_to(DIST).as_posix() for p in files if p.name.lower().endswith(".map")]
    if maps:
        raise PackagingError(
            f"source maps in web-react/dist ({', '.join(maps[:5])}): a release must never contain source maps "
            "(HeroUI Pro terms). Build without `build.sourcemap` and package again."
        )
    for p in files:
        rel = p.relative_to(DIST).as_posix()
        if p.is_symlink() or not p.is_file():
            raise PackagingError(f"web-react/dist/{rel} is not a regular file")
        if "node_modules" in PurePosixPath(rel).parts:
            raise PackagingError(f"web-react/dist/{rel}: node_modules must never be shipped")
        if p.name == ".npmrc" or (ENV_FILE_RE.match(p.name) and p.name not in ENV_FILE_OK):
            raise PackagingError(f"web-react/dist/{rel} must not be shipped")
        if p.suffix.lower() in {".js", ".mjs", ".cjs", ".css", ".html"} and b"sourceMappingURL=" in p.read_bytes():
            raise PackagingError(f"web-react/dist/{rel} references a source map (sourceMappingURL)")

    src = WEB / "src"
    if src.is_dir():
        newest = max((p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0.0)
        if newest > index.stat().st_mtime:
            warn("web-react/src has files newer than web-react/dist/index.html: is the build stale?")
    return files


def check_tracked(entry: Entry) -> None:
    """Things that must never be in a release, even if someone commits them."""
    p = PurePosixPath(entry.path)
    if p.parts[0] == "data":
        raise PackagingError(f"{entry.path} is tracked: data/ (sessions, tokens, keys) must never be released")
    if "node_modules" in p.parts:
        raise PackagingError(f"{entry.path} is tracked: node_modules must never be released")
    if p.parts[:2] == ("web-react", "dist"):
        raise PackagingError(f"{entry.path} is tracked: web-react/dist comes from the build, not from git")
    if ENV_FILE_RE.match(p.name) and p.name not in ENV_FILE_OK:
        raise PackagingError(f"{entry.path} is tracked: .env files hold secrets and must never be released")
    if p.name.lower().endswith(".map"):
        raise PackagingError(f"{entry.path} is a tracked source map: releases must not contain source maps")
    if p.name == ".npmrc" and NPMRC_SECRET_RE.search(entry.data):
        raise PackagingError(f"{entry.path} contains npm credentials")


def check_install_doc(entries: list[Entry]) -> None:
    """The install guide must have the section RELEASE.txt and the release notes send people to."""
    doc = next((e for e in entries if e.path == INSTALL_DOC), None)
    if doc is None or not INSTALL_SECTION_RE.search(doc.data.decode("utf-8", "replace")):
        raise PackagingError(
            f'{INSTALL_DOC} at HEAD has no "## Install from a release" section, which RELEASE.txt and the release '
            "notes link to (#install-from-a-release): add it and commit before packaging"
        )


def check_captures(entries: list[Entry], uv: str) -> int:
    """Real captures carry other players' online IDs: every ``.pwcap`` in the release must pass
    ``scripts/scrub_capture.py --check`` (no original name, no LAN address in its metadata). The checker needs
    Pitwall's own packages, so it runs in the project's environment (``uv run``). Returns the number checked."""
    captures = [e for e in entries if e.path.lower().endswith(".pwcap")]
    if not captures:
        return 0
    if not SCRUB_SCRIPT.is_file():
        raise PackagingError(f"{SCRUB_SCRIPT.relative_to(ROOT)} is missing: it checks the captures in the release")
    exe = shutil.which(uv)
    if exe is None:
        raise PackagingError(f"{uv!r} not found: it runs scripts/scrub_capture.py --check on the captures")
    with tempfile.TemporaryDirectory(prefix="pitwall-captures-") as tmp:
        files = []
        for i, e in enumerate(captures):  # the bytes that go into the zip (HEAD), not the working tree
            dest = Path(tmp) / f"{i:03d}-{PurePosixPath(e.path).name}"
            dest.write_bytes(e.data)
            files.append(str(dest))
        cmd = [exe, "run", "--project", str(ROOT), "--quiet", "python", str(SCRUB_SCRIPT), "--check", *files]
        try:
            run(cmd, show_stderr=True)
        except PackagingError as e:
            raise PackagingError(
                f"recorded captures are not scrubbed (or could not be checked): {e}\n"
                "Run `uv run python scripts/scrub_capture.py <capture>` on each, commit, and package again."
            ) from e
    return len(captures)


def secret_values() -> list[tuple[str, bytes]]:
    out = []
    for name in TOKEN_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if len(value) >= 8:
            out.append((name, value.encode()))
    return out


# ----------------------------------------------------------------------------------------------- content


def source_entries(excludes: list[str]) -> tuple[list[Entry], list[str]]:
    """Tracked files at HEAD (git archive: honours export-ignore), minus --exclude matches."""
    raw = run(["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD"])
    entries: list[Entry] = []
    excluded: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        for m in tar:
            if m.isdir():
                continue
            if m.issym() or m.islnk():
                raise PackagingError(f"{m.name} is a link; links are not supported in a release zip")
            if not m.isfile():
                continue
            if any(fnmatch.fnmatchcase(m.name, pat) for pat in excludes):
                excluded.append(m.name)
                continue
            f = tar.extractfile(m)
            assert f is not None
            entry = Entry(m.name, f.read(), 0o755 if m.mode & 0o111 else 0o644, int(m.mtime))
            check_tracked(entry)
            entries.append(entry)
    if not entries:
        raise PackagingError("git archive HEAD is empty")
    for pat in excludes:
        if not any(fnmatch.fnmatchcase(p, pat) for p in excluded):
            warn(f"--exclude {pat!r} matched no tracked file")
    return entries, excluded


def source_tree_notices(entries: list[Entry]) -> str:
    """Licence files of third-party material vendored in the source tree (e.g. src/**/third_party/**/LICENSE)."""
    found = [
        e
        for e in entries
        if "third_party" in PurePosixPath(e.path).parts and LICENCE_FILE_RE.match(PurePosixPath(e.path).name)
    ]
    if not found:
        return ""
    rule = "-" * 100
    lines = [
        "",
        "Third-party material in Pitwall's source tree",
        "=" * 100,
        "These files ship in this archive next to the material they cover, under their own licences.",
    ]
    for e in sorted(found, key=lambda x: x.path):
        text = e.data.decode("utf-8", "replace").replace("\r\n", "\n").strip()
        lines += ["", rule, e.path, "", text]
    return "\n".join(lines) + "\n"


def dashboard_notices(node: str, workdir: Path) -> str:
    exe = shutil.which(node)
    if exe is None:
        raise PackagingError(f"{node!r} not found: Node.js is needed to list the dashboard's licences")
    if not NOTICES_SCRIPT.is_file():
        raise PackagingError(f"{NOTICES_SCRIPT.relative_to(ROOT)} is missing")
    dest = workdir / "THIRD_PARTY_NOTICES.txt"
    run([exe, str(NOTICES_SCRIPT), "--out", str(dest), "--quiet"], cwd=WEB, show_stderr=True)
    text = dest.read_text(encoding="utf-8")
    if "@heroui-pro/react" not in text or "NextUI Inc." not in text:
        raise PackagingError("THIRD_PARTY_NOTICES lacks the HeroUI Pro attribution: is HeroUI Pro installed?")
    return text


def release_txt(version: str, commit: str, commit_date: str, clean: bool, excluded: list[str]) -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    built = datetime.fromtimestamp(int(epoch), UTC) if epoch and epoch.isdigit() else datetime.now(UTC)
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pkg_version = pyproject.get("project", {}).get("version", "unknown")
    if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_RUN_ID"):
        server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
        built_by = f"{server}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    else:
        built_by = "a local build (scripts/package_release.py)"
    tree = "clean" if clean else "DIRTY - packaged with --allow-dirty; the dashboard may not match the commit"
    fields = [
        ("Commit", commit),
        ("Commit date", commit_date),
        ("Packaged", built.strftime("%Y-%m-%dT%H:%M:%SZ")),
        ("Built by", built_by),
        ("Python package", f"pitwall {pkg_version} (pyproject.toml)"),
        ("Working tree", tree),
    ]
    if excluded:
        fields.append(("Left out", f"{len(excluded)} tracked file(s) (--exclude), e.g. {excluded[0]}"))
    lines = [f"Pitwall {version}", ""] + [f"{k + ':':<16}{v}" for k, v in fields]
    lines += [
        "",
        "Contents",
        "  Pitwall's source at the commit above (git archive), plus:",
        '  web-react/dist/          the dashboard, prebuilt for "/" (minified, no source maps). Pitwall serves it',
        "                           at http://127.0.0.1:8770/; no Node.js, npm or HeroUI Pro licence is needed.",
        "  THIRD_PARTY_NOTICES.txt  licences of the dashboard's third-party packages and of third-party data.",
        "  RELEASE.txt              this file.",
        "",
        "The dashboard includes HeroUI Pro (@heroui-pro/react), © NextUI Inc., used under licence and not covered",
        "by Pitwall's terms. It may not be extracted from the dashboard or redistributed separately.",
        "",
        'Install: docs/install.md, section "Install from a release".',
    ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------------------------- zip


def zip_info(name: str, mtime: int, mode: int) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(name, date_time=time.gmtime(max(mtime, MIN_ZIP_TIME))[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.create_system = 3  # Unix, so unzip restores the permission bits (executable scripts)
    zi.external_attr = (stat.S_IFREG | mode) << 16
    return zi


def write_zip(path: Path, prefix: str, entries: list[Entry]) -> None:
    names = Counter(f"{prefix}/{e.path}" for e in entries)
    dupes = [n for n, k in names.items() if k > 1]
    if dupes:
        raise PackagingError(f"duplicate paths in the release: {sorted(dupes)[:5]}")
    part = path.with_name(path.name + ".part")
    with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for e in entries:
            zf.writestr(zip_info(f"{prefix}/{e.path}", e.mtime, e.mode), e.data)
    part.replace(path)


def verify_zip(path: Path, prefix: str, secrets: list[tuple[str, bytes]]) -> dict[str, int]:
    counts = {"files": 0, "dashboard": 0}
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise PackagingError(f"{path.name}: CRC error in {bad}")
        names = zf.namelist()
        required = [f"{prefix}/{n}" for n in ("web-react/dist/index.html", "THIRD_PARTY_NOTICES.txt", "RELEASE.txt")]
        required.append(f"{prefix}/pyproject.toml")
        missing = [n for n in required if n not in names]
        if missing:
            raise PackagingError(f"{path.name} lacks {missing}")
        for n in names:
            p = PurePosixPath(n)
            if p.is_absolute() or ".." in p.parts or p.parts[0] != prefix:
                raise PackagingError(f"{path.name}: unsafe path {n}")
            if "node_modules" in p.parts or p.name.lower().endswith(".map"):
                raise PackagingError(f"{path.name}: forbidden file {n}")
            if p.parts[1:2] == ("data",) or (ENV_FILE_RE.match(p.name) and p.name not in ENV_FILE_OK):
                raise PackagingError(f"{path.name}: forbidden file {n}")
            counts["files"] += 1
            if p.parts[1:3] == ("web-react", "dist"):
                counts["dashboard"] += 1
            if secrets or p.name == ".npmrc":
                data = zf.read(n)
                if p.name == ".npmrc" and NPMRC_SECRET_RE.search(data):
                    raise PackagingError(f"{path.name}: {n} contains npm credentials")
                for var, value in secrets:
                    if value in data:
                        raise PackagingError(f"{path.name}: the value of ${var} appears in {n}")
    return counts


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------------------------- main


def package(args: argparse.Namespace) -> Path:
    version: str = args.version
    check_version(version)
    out = Path(args.out).resolve()
    if out == DIST or DIST in out.parents:
        raise PackagingError("--out must not be inside web-react/dist")
    prefix = f"pitwall-{version}"

    clean = check_worktree(args.allow_dirty)
    dist_files = check_dist()
    commit = git("rev-parse", "HEAD")
    commit_date = git("show", "-s", "--format=%cI", "HEAD")
    commit_time = int(git("show", "-s", "--format=%ct", "HEAD"))

    source, excluded = source_entries(args.exclude)
    check_install_doc(source)
    n_captures = check_captures(source, args.uv)
    if n_captures:
        info(f"{n_captures} recorded capture(s) checked: no player names, no LAN addresses")
    with tempfile.TemporaryDirectory(prefix="pitwall-release-") as tmp:
        notices = dashboard_notices(args.node, Path(tmp)) + source_tree_notices(source)

    entries = list(source)
    for p in dist_files:
        rel = p.relative_to(DIST).as_posix()
        entries.append(Entry(f"web-react/dist/{rel}", p.read_bytes(), 0o644, commit_time))
    entries.append(Entry("THIRD_PARTY_NOTICES.txt", notices.encode("utf-8"), 0o644, commit_time))
    rel_txt = release_txt(version, commit, commit_date, clean, excluded)
    entries.append(Entry("RELEASE.txt", rel_txt.encode("utf-8"), 0o644, commit_time))

    secrets = secret_values()
    for e in entries:
        for var, value in secrets:
            if value in e.data:
                raise PackagingError(f"the value of ${var} appears in {e.path}; refusing to package")

    out.mkdir(parents=True, exist_ok=True)
    zip_path = out / f"{prefix}.zip"
    sha_path = out / f"{prefix}.zip.sha256"
    sha_path.unlink(missing_ok=True)
    write_zip(zip_path, prefix, entries)
    counts = verify_zip(zip_path, prefix, secrets)
    digest = sha256_of(zip_path)
    with sha_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(f"{digest}  {zip_path.name}\n")

    size_mb = zip_path.stat().st_size / 1e6
    info(f"{zip_path}")
    info(
        f"  {size_mb:.1f} MB, {counts['files']} files: {len(source)} from git (commit {commit[:12]}), "
        f"{counts['dashboard']} dashboard, THIRD_PARTY_NOTICES.txt, RELEASE.txt"
        + (f"; {len(excluded)} excluded" if excluded else "")
    )
    info(f"sha256 {digest}  {zip_path.name}")
    info(f"{sha_path}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with Path(gh_out).open("a", encoding="utf-8") as f:
            f.write(f"zip={zip_path}\nsha256_file={sha_path}\nsha256={digest}\n")
    return zip_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Package a Pitwall release zip (source at HEAD + prebuilt dashboard + notices).",
        epilog="See docs/releasing.md.",
    )
    ap.add_argument("--version", required=True, help="release version, e.g. v0.2.0 or v0.2.0-rc.1")
    ap.add_argument("--out", required=True, help="output folder for the zip and its .sha256")
    ap.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="leave tracked files matching GLOB (repo-relative, fnmatch: * also matches /) out; repeatable",
    )
    ap.add_argument("--allow-dirty", action="store_true", help="package even if the working tree differs from HEAD")
    ap.add_argument("--node", default="node", help="Node.js executable for notices.mjs (default: node)")
    ap.add_argument("--uv", default="uv", help="uv executable for the capture privacy check (default: uv)")
    args = ap.parse_args(argv)
    try:
        package(args)
    except PackagingError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
