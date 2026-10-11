"""Release tags, SemVer 2.0 ordering, the running version and the kind of folder the code runs from."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pitwall import __version__
from pitwall.install.versions import (
    current_version,
    install_kind,
    is_valid_tag,
    parse_version,
    release_tag,
    supports_managed,
)


@pytest.mark.parametrize("tag", ["v0.1.0", "v1.2.3", "v10.20.30", "v0.2.0-rc.1", "v0.2.0-test.2", "v1.0.0-alpha-1.x"])
def test_valid_tags(tag: str) -> None:
    assert is_valid_tag(tag)
    v = parse_version(tag)
    assert v is not None and v.tag == tag


@pytest.mark.parametrize(
    "tag",
    [
        "",
        "0.1.0",
        "v1.2",
        "v1.2.3.4",
        "v1.2.3-",
        "v1.2.3-.rc",
        "v1.2.3+build",
        "v1.2.3/../x",
        "v1.2.3\n",
        " v1.2.3",
        "V1.2.3",
    ],
)
def test_rejected_tags(tag: str) -> None:
    assert not is_valid_tag(tag)
    assert parse_version(tag) is None


def test_semver_ordering() -> None:
    order = [
        "v0.1.0",
        "v0.2.0-alpha",
        "v0.2.0-alpha.1",
        "v0.2.0-alpha.beta",
        "v0.2.0-beta.2",
        "v0.2.0-beta.11",
        "v0.2.0-rc.1",
        "v0.2.0-rc.2",
        "v0.2.0-rc.10",
        "v0.2.0",
        "v0.2.1",
        "v0.10.0",
        "v1.0.0",
    ]
    parsed = [parse_version(t) for t in order]
    assert all(p is not None for p in parsed)
    shuffled = sorted(parsed, key=lambda p: p.tag)  # type: ignore[union-attr]
    assert [p.tag for p in sorted(shuffled)] == order  # type: ignore[union-attr,type-var]
    a, b = parse_version("v0.2.0-rc.2"), parse_version("v0.2.0-rc.10")
    assert a is not None and b is not None and a < b and b > a and a <= a and b >= b
    num, alpha = parse_version("v1.0.0-1"), parse_version("v1.0.0-alpha")
    assert num is not None and alpha is not None and num < alpha  # numeric identifiers sort first


def test_minimum_for_the_one_line_installer_ignores_the_suffix() -> None:
    assert supports_managed("v0.2.0") and supports_managed("v0.2.0-test.1") and supports_managed("v1.0.0")
    assert not supports_managed("v0.1.0") and not supports_managed("v0.1.9-rc.1") and not supports_managed("bad")


def test_current_version_from_release_txt(tmp_path: Path) -> None:
    assert current_version(tmp_path) == f"v{__version__}"
    (tmp_path / "RELEASE.txt").write_text("Pitwall v0.3.0-rc.1\n\nCommit: abc\n", encoding="utf-8")
    assert release_tag(tmp_path) == "v0.3.0-rc.1" and current_version(tmp_path) == "v0.3.0-rc.1"
    (tmp_path / "RELEASE.txt").write_text("Pitwall ../../etc\n", encoding="utf-8")
    assert current_version(tmp_path) == f"v{__version__}"


def test_install_kind(tmp_path: Path) -> None:
    home = tmp_path / "Pitwall"
    folder = home / "pitwall-v0.2.0"
    folder.mkdir(parents=True)
    assert install_kind(folder) == "unknown"
    (folder / "RELEASE.txt").write_text("Pitwall v0.2.0\n", encoding="utf-8")
    assert install_kind(folder) == "release"
    (home / "install.json").write_text(json.dumps({"schema": 1, "current": "v0.1.0", "versions": ["v0.1.0"]}))
    assert install_kind(folder) == "release"  # install.json does not list this folder
    (home / "install.json").write_text(json.dumps({"schema": 1, "current": "v0.2.0", "versions": ["v0.2.0"]}))
    assert install_kind(folder) == "managed"
    (home / "install.json").write_text("{not json")
    assert install_kind(folder) == "release"
    (folder / ".git").write_text("gitdir: elsewhere\n")  # a worktree's .git is a file
    assert install_kind(folder) == "git"
