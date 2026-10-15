"""The brand mark's files (README logo, PWA icons, favicon) are generated from one geometry by
scripts/make_brand_icons.py; they must match it byte for byte, and the dashboard's own mark must draw it too."""

from __future__ import annotations

import importlib.util
import struct
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_brand_icons", ROOT / "scripts" / "make_brand_icons.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["make_brand_icons"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_brand_files_are_up_to_date() -> None:
    assert _module().main(["--check"]) == 0, "run: uv run python scripts/make_brand_icons.py"


def test_the_icons_are_the_sizes_the_manifest_and_html_name() -> None:
    sizes = {"icon-192.png": 192, "icon-512.png": 512, "icon-maskable-512.png": 512, "apple-touch-icon.png": 180}
    manifest = (ROOT / "web-react" / "public" / "manifest.webmanifest").read_text()
    for name, size in sizes.items():
        data = (ROOT / "web-react" / "public" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", data[16:24]) == (size, size), name
        assert name == "apple-touch-icon.png" or f'"{name}"' in manifest


def test_the_dashboard_mark_draws_the_same_geometry() -> None:
    tsx = (ROOT / "web-react" / "src" / "components" / "Brand.tsx").read_text()
    for part in (
        "M4.5 11 L4.5 8 L27.5 8 L27.5 11",
        'x="8" y="13" width="7" height="5"',
        'x="17" y="13"',
        "M5 21 L27 21",
    ):
        assert part in tsx
    assert "M8 21 L8 27 M24 21 L24 27" in tsx
