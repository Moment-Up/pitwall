"""The package version is written in two places: they must agree.

``/api/health``, the dashboard's Server card and the User-Agent show ``pitwall.__version__``; ``pyproject.toml``'s
``version`` is the package's. A git checkout compares ``v`` + ``__version__`` with GitHub's releases, so a stale one
would say "Update available" for ever (the release workflow also requires both to match a stable tag)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pitwall

ROOT = Path(__file__).resolve().parents[2]


def test_dunder_version_matches_pyproject() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert pitwall.__version__ == project["version"], (
        "src/pitwall/__init__.py __version__ and pyproject.toml version differ: set both to the release without the v"
    )
