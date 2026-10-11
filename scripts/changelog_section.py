"""Print the bullet points of one release from CHANGELOG.md (for the release notes' "What changed").

Usage::

    python scripts/changelog_section.py --version v0.2.0 [--require] [--changelog CHANGELOG.md]

It prints the body of the ``## v0.2.0 - <date>`` (or ``## v0.2.0``) section. A pre-release (``v0.2.0-rc.1``)
without a section of its own uses ``## Unreleased``. Without ``--require`` a missing section prints nothing and
exits 0; with ``--require`` (stable tags in the release workflow) it exits 1 with a message. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$")
HEADING_RE = re.compile(r"^##\s+(\S+)(?:\s+-\s+.*)?\s*$")


def sections(text: str) -> dict[str, list[str]]:
    """``{"v0.2.0": [lines], "Unreleased": [lines]}`` for every ``## `` heading (case kept)."""
    out: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("## "):
            m = HEADING_RE.match(line)
            current = out.setdefault(m.group(1), []) if m else None
            continue
        if line.startswith("# "):
            current = None
            continue
        if current is not None:
            current.append(line)
    return out


def section_for(text: str, version: str) -> str | None:
    found = sections(text)
    body = found.get(version)
    if body is None and "-" in version:
        body = next((v for k, v in found.items() if k.lower() == "unreleased"), None)
    if body is None:
        return None
    result = "\n".join(body).strip("\n")
    return result if result.strip() else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Print one release's section of CHANGELOG.md.")
    ap.add_argument("--version", required=True, help="release tag, e.g. v0.2.0")
    ap.add_argument("--require", action="store_true", help="fail when the version has no section")
    ap.add_argument("--changelog", default=str(Path(__file__).resolve().parents[1] / "CHANGELOG.md"))
    args = ap.parse_args(argv)
    if not VERSION_RE.match(args.version):
        print(f"error: --version {args.version!r} must look like v1.2.3 or v1.2.3-rc.1", file=sys.stderr)
        return 2
    try:
        text = Path(args.changelog).read_text(encoding="utf-8")
    except OSError as e:
        print(f"error: cannot read {args.changelog}: {e}", file=sys.stderr)
        return 1
    body = section_for(text, args.version)
    if body is None:
        if args.require:
            print(
                f"error: CHANGELOG.md has no '## {args.version} - <date>' section: add one (rename '## Unreleased') "
                "and commit before tagging",
                file=sys.stderr,
            )
            return 1
        return 0
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
