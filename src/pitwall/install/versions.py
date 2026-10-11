"""Release tags, SemVer 2.0 ordering, the running version and the kind of folder the code runs from."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pitwall
from pitwall import __version__

# The same pattern as scripts/package_release.py and the release workflow.
VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
RELEASE_LINE_RE = re.compile(r"^Pitwall (v\S+)$")
# The first release that ships `pitwall install-finish` (the one-line installers and `pitwall update` need it).
MIN_MANAGED = (0, 2, 0)

InstallKind = Literal["managed", "release", "git", "unknown"]


@dataclass(frozen=True, slots=True)
class Version:
    tag: str  # "v1.2.3-rc.1"
    core: tuple[int, int, int]
    pre: tuple[str, ...]  # () for a release

    @property
    def is_pre(self) -> bool:
        return bool(self.pre)

    def key(self) -> tuple[int, int, int, int, tuple[tuple[int, int, str], ...]]:
        """SemVer 2.0 precedence: a pre-release sorts below its release; numeric identifiers compare as numbers and
        below alphanumeric ones; a longer list of equal identifiers sorts higher (rc.2 < rc.10 < the release)."""
        ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in self.pre)
        return (*self.core, 0 if self.pre else 1, ids)

    def __lt__(self, other: Version) -> bool:
        return self.key() < other.key()

    def __le__(self, other: Version) -> bool:
        return self.key() <= other.key()

    def __gt__(self, other: Version) -> bool:
        return self.key() > other.key()

    def __ge__(self, other: Version) -> bool:
        return self.key() >= other.key()


def parse_version(tag: str) -> Version | None:
    """``Version`` for a valid tag (``v1.2.3`` or ``v1.2.3-rc.1``), else ``None``. Tags are validated with this
    before they are used in any path or URL."""
    if not isinstance(tag, str) or not VERSION_RE.fullmatch(tag):
        return None
    core_text, _, pre_text = tag[1:].partition("-")
    major, minor, patch = (int(x) for x in core_text.split("."))
    return Version(tag, (major, minor, patch), tuple(pre_text.split(".")) if pre_text else ())


def is_valid_tag(tag: str) -> bool:
    return parse_version(tag) is not None


def supports_managed(tag: str) -> bool:
    """True when ``tag`` (pre-release suffix ignored) is at least v0.2.0, the first release with install-finish."""
    v = parse_version(tag)
    return v is not None and v.core >= MIN_MANAGED


def code_root() -> Path:
    """The folder this code runs from: a release folder, a git checkout, or something else."""
    return Path(pitwall.__file__).resolve().parents[2]


def release_tag(root: Path) -> str | None:
    """The tag on line 1 of ``RELEASE.txt`` ("Pitwall v0.2.0"), or ``None``."""
    try:
        with (root / "RELEASE.txt").open(encoding="utf-8", errors="replace") as f:
            first = f.readline().strip()
    except OSError:
        return None
    m = RELEASE_LINE_RE.match(first)
    return m.group(1) if m and is_valid_tag(m.group(1)) else None


def current_version(root: Path | None = None) -> str:
    """The running version as a tag: RELEASE.txt's, otherwise ``"v" + pitwall.__version__``."""
    return release_tag(root or code_root()) or f"v{__version__}"


def _listed_in_install_json(root: Path) -> bool:
    try:
        data = json.loads((root.parent / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    tags = [t for t in (data.get("versions") or []) if isinstance(t, str)]
    tags += [t for t in (data.get("current"), data.get("staged")) if isinstance(t, str)]
    return any(is_valid_tag(t) and root.name == f"pitwall-{t}" for t in tags)


def install_kind(root: Path | None = None) -> InstallKind:
    """``git`` (``.git`` file or folder), ``managed`` (a release folder listed in its parent's install.json),
    ``release`` (an unzipped release installed by hand: can be adopted), or ``unknown``."""
    r = root or code_root()
    if (r / ".git").exists():
        return "git"
    if (r / "RELEASE.txt").is_file():
        return "managed" if _listed_in_install_json(r) else "release"
    return "unknown"
