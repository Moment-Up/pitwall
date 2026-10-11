"""``scripts/changelog_section.py``: the release notes' "What changed" list from CHANGELOG.md."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from pitwall.install.github import extract_notes

ROOT = Path(__file__).resolve().parents[2]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("changelog_section", ROOT / "scripts" / "changelog_section.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["changelog_section"] = mod
    spec.loader.exec_module(mod)
    return mod


cs = _module()

TEXT = """# Changelog

Intro text.

## Unreleased

- Coming soon

## v0.2.0 - 2026-10-20

- One-line install
- **Updates** in [Settings](https://example.com)

## v0.1.0 - 2026-10-11

- First release
"""


def test_section_of_a_release_and_the_unreleased_fallback() -> None:
    assert cs.section_for(TEXT, "v0.2.0") == "- One-line install\n- **Updates** in [Settings](https://example.com)"
    assert cs.section_for(TEXT, "v0.1.0") == "- First release"
    assert cs.section_for(TEXT, "v0.3.0-rc.1") == "- Coming soon"  # pre-release: Unreleased
    assert cs.section_for(TEXT, "v0.3.0") is None  # a stable tag never falls back


def test_cli_require_and_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(TEXT, encoding="utf-8")
    assert cs.main(["--version", "v0.2.0", "--changelog", str(path), "--require"]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("- One-line install")
    # the notes pipeline: release body "## What changed" + this list -> pitwall update's list
    assert extract_notes("## What changed\n\n" + printed) == ["One-line install", "Updates in Settings"]
    assert cs.main(["--version", "v0.3.0", "--changelog", str(path), "--require"]) == 1
    assert cs.main(["--version", "v0.3.0", "--changelog", str(path)]) == 0
    assert capsys.readouterr().out == ""
    assert cs.main(["--version", "0.3.0", "--changelog", str(path)]) == 2


def test_the_real_changelog_has_the_running_version_and_v010(capsys: pytest.CaptureFixture[str]) -> None:
    """A stable tag needs its own section (install D5): the version in pyproject.toml / ``__version__`` has one, and
    it passes the release workflow's ``--require`` check (no bullet over 200 characters)."""
    import pitwall

    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert cs.section_for(text, "v0.1.0")
    version = f"v{pitwall.__version__}"
    if "-" not in version:  # a pre-release may use "## Unreleased" instead
        assert cs.main(["--version", version, "--changelog", str(ROOT / "CHANGELOG.md"), "--require"]) == 0
        assert capsys.readouterr().out.strip()
    for v in ("v0.1.0", version):
        notes = extract_notes("## What changed\n" + (cs.section_for(text, v) or ""))
        assert notes and all(len(n) <= 200 for n in notes)


def test_bullets_match_the_dashboard_and_long_ones_fail(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pitwall.install import github

    assert cs.MAX_NOTE_CHARS == github.MAX_NOTE_CHARS
    body = "- **Bold** with a [link](https://x) and `code`\n- Wrapped over\n  two lines\n- " + "long words " * 25 + "\n"
    assert cs.bullets(body)[:2] == extract_notes("## What changed\n" + body)[:2]
    assert len(cs.too_long(body)) == 1
    path = tmp_path / "CHANGELOG.md"
    path.write_text("# Changelog\n\n## v0.2.0 - 2026-10-20\n\n" + body, encoding="utf-8")
    assert cs.main(["--version", "v0.2.0", "--changelog", str(path), "--require"]) == 1
    assert "over 200" in capsys.readouterr().err
    assert cs.main(["--version", "v0.2.0", "--changelog", str(path)]) == 0  # without --require: a warning only
    assert "warning:" in capsys.readouterr().err


def test_the_real_unreleased_bullets_fit_without_a_cut() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    body = cs.section_for(text, "v0.2.0-rc.1") or ""
    assert cs.too_long(body) == []
    assert not any(n.endswith("…") for n in extract_notes("## What changed\n" + body))
