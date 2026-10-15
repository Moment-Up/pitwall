"""Pitwall's brand mark - the pit wall stand: a canopy, two screens and the desk on its legs - as SVG and PNG icons,
all drawn from the one geometry below.

Run from the repository root::

    uv run python scripts/make_brand_icons.py          # write the files, print the favicon data URI
    uv run python scripts/make_brand_icons.py --check  # exit 1 when a file is out of date

Writes ``docs/brand/pitwall-mark.svg`` (README) and the PNG icons in ``web-react/public`` (the PWA manifest's ``any``
and ``maskable`` icons, the Apple touch icon), and checks that ``web-react/index.html`` carries the favicon data URI.
The dashboard's own mark (``web-react/src/components/Brand.tsx``) draws the same geometry in the theme's colours.

Standard library and numpy only: an anti-aliased signed-distance rasteriser (4 x 4 supersampling) and a plain PNG
writer, so no image library is needed and the output is byte-for-byte reproducible.
"""

from __future__ import annotations

import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TILE = "#06080b"  # the dashboard's dark background (manifest theme_color)
ACCENT = "#ff6a2b"  # --accent, dark theme
SCREEN = "#f2f4f7"  # the light screen
GRID = 32.0  # the mark is drawn on a 32 x 32 grid
TILE_RADIUS = 7.0
MASKABLE_SCALE = 0.72  # keeps the mark inside the maskable icon's safe circle (radius 40 % of the size)
SUPERSAMPLE = 4


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    r: float
    color: str


@dataclass(frozen=True, slots=True)
class Stroke:
    points: tuple[tuple[float, float], ...]
    width: float
    color: str


# Drawn in this order. The canopy's corners and every line end are round.
MARK: tuple[Rect | Stroke, ...] = (
    Stroke(((4.5, 11.0), (4.5, 8.0), (27.5, 8.0), (27.5, 11.0)), 2.4, ACCENT),  # canopy
    Rect(8.0, 13.0, 7.0, 5.0, 1.0, SCREEN),  # screens
    Rect(17.0, 13.0, 7.0, 5.0, 1.0, ACCENT),
    Stroke(((5.0, 21.0), (27.0, 21.0)), 2.6, ACCENT),  # desk
    Stroke(((8.0, 21.0), (8.0, 27.0)), 2.4, ACCENT),  # legs
    Stroke(((24.0, 21.0), (24.0, 27.0)), 2.4, ACCENT),
)


# ---------------------------------------------------------------------------------------------- SVG
def _num(v: float) -> str:
    return f"{v:g}"


def mark_svg_elements() -> str:
    """The mark's SVG elements on the 32 grid (no tile)."""
    out: list[str] = []
    for s in MARK:
        if isinstance(s, Rect):
            out.append(
                f"<rect x='{_num(s.x)}' y='{_num(s.y)}' width='{_num(s.w)}' height='{_num(s.h)}' rx='{_num(s.r)}' "
                f"fill='{s.color}'/>"
            )
        else:
            d = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in s.points)
            out.append(
                f"<path d='{d}' stroke='{s.color}' stroke-width='{_num(s.width)}' fill='none' "
                "stroke-linecap='round' stroke-linejoin='round'/>"
            )
    return "".join(out)


def tile_svg() -> str:
    """The mark on its dark rounded tile (favicon, README)."""
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
        f"<rect width='32' height='32' rx='{_num(TILE_RADIUS)}' fill='{TILE}'/>{mark_svg_elements()}</svg>"
    )


def favicon_data_uri() -> str:
    return "data:image/svg+xml," + quote(tile_svg(), safe="/:=' ")


# ---------------------------------------------------------------------------------------------- raster
def _rgb(color: str) -> np.ndarray:
    return np.array([int(color[i : i + 2], 16) for i in (1, 3, 5)], dtype=np.float64) / 255.0


def _rrect_sdf(px: np.ndarray, py: np.ndarray, x: float, y: float, w: float, h: float, r: float) -> np.ndarray:
    qx = np.abs(px - (x + w / 2)) - (w / 2 - r)
    qy = np.abs(py - (y + h / 2)) - (h / 2 - r)
    outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
    return np.asarray(outside + np.minimum(np.maximum(qx, qy), 0.0) - r)


def _stroke_sdf(px: np.ndarray, py: np.ndarray, s: Stroke) -> np.ndarray:
    d = np.full(px.shape, np.inf)
    for (ax, ay), (bx, by) in zip(s.points, s.points[1:], strict=False):
        dx, dy = bx - ax, by - ay
        t = np.clip(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy), 0.0, 1.0)
        d = np.minimum(d, np.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return np.asarray(d - s.width / 2)


def render(size: int, variant: str) -> np.ndarray:
    """RGBA float image. ``tile``: the rounded tile, transparent corners; ``square``: full-bleed background (the
    Apple touch icon, which iOS rounds itself); ``maskable``: full-bleed with the mark shrunk into the safe zone."""
    n = size * SUPERSAMPLE
    c = (np.arange(n) + 0.5) / n * GRID  # sample centres on the 32 grid
    px, py = np.meshgrid(c, c)
    rgb = np.zeros((n, n, 3))
    alpha = np.zeros((n, n))
    if variant == "tile":
        bg = (_rrect_sdf(px, py, 0, 0, GRID, GRID, TILE_RADIUS) <= 0).astype(np.float64)
    else:
        bg = np.ones((n, n))
    rgb[:] = _rgb(TILE)
    alpha[:] = bg
    if variant == "maskable":  # sample the mark on a grid scaled about the centre
        mx = (px - GRID / 2) / MASKABLE_SCALE + GRID / 2
        my = (py - GRID / 2) / MASKABLE_SCALE + GRID / 2
    else:
        mx, my = px, py
    for s in MARK:
        sdf = _rrect_sdf(mx, my, s.x, s.y, s.w, s.h, s.r) if isinstance(s, Rect) else _stroke_sdf(mx, my, s)
        inside = (sdf <= 0).astype(np.float64)
        rgb = rgb * (1 - inside[..., None]) + _rgb(s.color) * inside[..., None]
        alpha = np.maximum(alpha, inside)
    # box-filter the supersamples down (premultiplied, so transparent corners stay clean)
    pre = np.concatenate([rgb * alpha[..., None], alpha[..., None]], axis=2)
    pre = pre.reshape(size, SUPERSAMPLE, size, SUPERSAMPLE, 4).mean(axis=(1, 3))
    a = pre[..., 3:4]
    out = np.where(a > 0, pre[..., :3] / np.maximum(a, 1e-9), 0.0)
    return np.concatenate([out, a], axis=2)


def png_bytes(img: np.ndarray) -> bytes:
    h, w, _ = img.shape
    raw = np.clip(np.rint(img * 255), 0, 255).astype(np.uint8)
    rows = b"".join(b"\x00" + raw[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return len(data).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    header = w.to_bytes(4, "big") + h.to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


# ---------------------------------------------------------------------------------------------- files
def outputs() -> dict[Path, bytes]:
    pub = ROOT / "web-react" / "public"
    svg = tile_svg().replace("<svg ", "<svg width='256' height='256' ", 1) + "\n"
    return {
        ROOT / "docs" / "brand" / "pitwall-mark.svg": svg.encode(),
        pub / "icon-192.png": png_bytes(render(192, "tile")),
        pub / "icon-512.png": png_bytes(render(512, "tile")),
        pub / "icon-maskable-512.png": png_bytes(render(512, "maskable")),
        pub / "apple-touch-icon.png": png_bytes(render(180, "square")),
    }


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = [p for p, data in outputs().items() if not p.exists() or p.read_bytes() != data]
    html = (ROOT / "web-react" / "index.html").read_text()
    uri = favicon_data_uri()
    if uri not in html:
        stale.append(ROOT / "web-react" / "index.html")
    if check:
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    for p, data in outputs().items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        print(f"wrote {p.relative_to(ROOT)}")
    if uri not in html:
        print(f"web-react/index.html needs this favicon href:\n{uri}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
