"""Record the README's animated Drive › Coach demo from a real capture streamed to an isolated Pitwall.

Dev-time only (needs Playwright's Chromium and Pillow, which are not Pitwall dependencies)::

    uv run --with playwright==1.61.0 --with pillow python scripts/demo/record_drive_gif.py \\
        --capture <capture.pwcap> --segment 0:1790:8 --segment 1790:1828:1 --record 1809.8:1823.8 \\
        --dist <a web-react/dist built for "/"> --out docs/screenshots/00-drive-coach-live.gif

Without ``--capture`` it uses the committed F1 25 Austria excerpt (``--segment 0:270:1 --record 95:110``), whose
gaps leave every lap incomplete, so Drive › Coach shows its "first visit" empty states.

How it works:

1. A temporary Pitwall (``pitwall serve`` with the dashboard from ``--dist``) on 127.0.0.1 with a temporary
   working and data folder, no ``.env``, the language model, voice, raw recording and update checks off, and the
   driver named "Driver". Ports default to 8830 (HTTP) and 20830 (UDP); ports in use, 8770, 20777 and SYNTHETIC
   captures are refused.
2. The capture is streamed over loopback UDP: packets inside each ``--segment START:END:SPEED`` (capture seconds)
   at that speed, gaps over 2 s shortened to 0.5 s, packets outside every segment skipped.
3. Headless Chromium (1180x820, dark) shows ``#/drive/coach`` with the screen wake lock granted (as a tablet that
   keeps its screen on; without it the page shows "Screen may sleep"); screenshots are taken only while capture time
   is inside ``--record START:END``, at ``--fps``.
4. Gates, checked on the page text once a second; any failure means no GIF:
   - none of the capture's participant names (``scripts/scrub_capture.py`` collects them from every packet; whole
     words of 3 or more characters, case-sensitive), no IPv4 address but 127.0.0.1, no ``token=``, no "SYNTHETIC";
   - ``--strict`` (default): in at least 80 % of the samples a live delta (``+0.12``), a next corner (``T3``) and a
     reference lap chip (``Lap 64 · 1:10.549``), and in at least 60 % a coaching point (``T3: braked later…``,
     not "No note for T1").
5. Pillow: one 128-colour palette (median cut over the first, middle and last frames), no dithering, 125 ms per
   frame on average (GIF delays are in 10 ms steps, so 120 and 130 ms alternate: real time at 8 fps), looping;
   refused above 6 MB or outside 10-15 s.

The temporary server is stopped (terminate, then kill after 10 s) and the temporary folders and frames are deleted
in every case. The capture is only read; nothing from it is copied.
"""

from __future__ import annotations

import argparse
import importlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXCERPT = ROOT / "tests" / "fixtures" / "recorded" / "f1_25_2025_ps5_austria_race-excerpt.pwcap"
FORBIDDEN_PORTS = {8770, 20777}
VIEWPORT = {"width": 1180, "height": 820}
MAX_BYTES = 6_000_000
MIN_S, MAX_S = 10.0, 15.0
FRAME_MS = 125
IPV4 = re.compile(r"(?<![\d.])\d{1,3}(?:\.\d{1,3}){3}(?![\d.])")
DELTA = re.compile(r"(?m)^\s*[+−-]\d+\.\d\d\s*$")
NEXT_CORNER = re.compile(r"(?is)next corner.{0,120}?\bT\d+\b")
REF_CHIP = re.compile(r"Lap \d+ · \d:\d\d\.\d{3}")
COACH_NOTE = re.compile(r"(?m)\bT\d+: \S")  # "T3: braked later, 4 km/h slower out"


class GateError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Segment:
    start: float
    end: float
    speed: float


@dataclass(slots=True)
class Run:
    entered: threading.Event = field(default_factory=threading.Event)
    left: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    sent: int = 0
    error: str | None = None


# ------------------------------------------------------------------------------------------------ helpers
def parse_segment(text: str) -> Segment:
    a, b, c = (float(x) for x in text.split(":"))
    if not (0 <= a < b and c > 0):
        raise argparse.ArgumentTypeError(f"--segment {text!r}: START:END:SPEED with START < END and SPEED > 0")
    return Segment(a, b, c)


def parse_window(text: str) -> tuple[float, float]:
    a, b = (float(x) for x in text.split(":"))
    if not 0 <= a < b:
        raise argparse.ArgumentTypeError(f"--record {text!r}: START:END with START < END")
    return a, b


def port_free(port: int, kind: int) -> bool:
    with socket.socket(socket.AF_INET, kind) as s:
        if kind == socket.SOCK_STREAM:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def health(port: int) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            data = json.loads(r.read())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def participant_words(capture: Path) -> set[str]:
    """Every word (3+ characters) of every participant / lobby name in the capture (scrub_capture's own parser)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    scrub = importlib.import_module("scrub_capture")
    from pitwall.ingest.capture import CaptureReader

    stats = scrub.Stats()
    for i, pkt in enumerate(CaptureReader(capture)):
        scrub.scrub_f1(pkt.data, stats, i)
    words: set[str] = set()
    for raw in stats.originals:
        name = raw.decode("utf-8", "replace").strip()
        if len(name) >= 3:
            words.add(name)
        words.update(w for w in re.split(r"[\s_.\-]+", name) if len(w) >= 3)
    return words


def check_text(text: str, words: set[str], strict_hits: dict[str, int]) -> None:
    for w in words:
        if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text):
            raise GateError("a participant name from the capture is on the page")
    for m in IPV4.finditer(text):
        try:
            ip = ipaddress.IPv4Address(m.group(0))
        except ValueError:
            continue
        if str(ip) != "127.0.0.1":
            raise GateError("an IPv4 address other than 127.0.0.1 is on the page")
    if "token=" in text:
        raise GateError("an access token link is on the page")
    if "SYNTHETIC" in text.upper():
        raise GateError("the page says SYNTHETIC")
    strict_hits["samples"] += 1
    strict_hits["delta"] += bool(DELTA.search(text))
    strict_hits["next_corner"] += bool(NEXT_CORNER.search(text))
    strict_hits["ref_chip"] += bool(REF_CHIP.search(text))
    strict_hits["coach_note"] += bool(COACH_NOTE.search(text))


# ------------------------------------------------------------------------------------------------ sender
def stream(capture: Path, port: int, segments: list[Segment], window: tuple[float, float], run: Run) -> None:
    from pitwall.ingest.capture import CaptureReader

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        first: int | None = None
        last: int | None = None
        due = 0
        end = max(s.end for s in segments)
        for pkt in CaptureReader(capture):
            first = pkt.t_recv_ns if first is None else first
            rel = (pkt.t_recv_ns - first) / 1e9
            if rel >= end:
                break
            seg = next((s for s in segments if s.start <= rel < s.end), None)
            if seg is None:
                last = None
                continue
            if last is None:
                due = time.perf_counter_ns()
            else:
                gap = (pkt.t_recv_ns - last) / 1e9
                gap = 0.5 if gap > 2.0 else gap
                due += int(gap / seg.speed * 1e9)
                wait = (due - time.perf_counter_ns()) / 1e9
                if wait > 0.001:
                    time.sleep(wait)
            last = pkt.t_recv_ns
            sock.sendto(pkt.data, ("127.0.0.1", port))
            run.sent += 1
            if rel >= window[0]:
                run.entered.set()
            if rel >= window[1]:
                run.left.set()
        sock.close()
    except Exception as e:  # reported by the main thread
        run.error = f"{type(e).__name__}: {e}"
    finally:
        run.entered.set()
        run.left.set()
        run.done.set()


# ------------------------------------------------------------------------------------------------ main
LAUNCHER = """
import sys
from pathlib import Path
import pitwall.api.app as app_module
app_module.WEB_REACT_DIST = Path(sys.argv[1])
from pitwall.cli import app
app(["serve", "--host", "127.0.0.1", "--port", sys.argv[2]])
"""


def record(args: argparse.Namespace) -> int:
    from PIL import Image
    from playwright.sync_api import sync_playwright

    from pitwall.ingest.capture import CaptureReader

    capture: Path = args.capture
    dist: Path = args.dist
    if not (dist / "index.html").is_file():
        raise SystemExit(f"{dist} has no index.html: build the dashboard for / (npm run build:root)")
    for port, kind in ((args.http_port, socket.SOCK_STREAM), (args.udp_port, socket.SOCK_DGRAM)):
        if port in FORBIDDEN_PORTS:
            raise SystemExit(f"port {port} belongs to the running Pitwall service: choose another")
        if not port_free(port, kind):
            raise SystemExit(f"port {port} is in use")
    if CaptureReader(capture).meta.synthetic:
        raise SystemExit(f"{capture.name} is SYNTHETIC: the README demo must come from a recorded session")

    print(f"collecting participant names from {capture.name} (never printed)...", flush=True)
    words = participant_words(capture)
    print(f"  {len(words)} name words to keep off the page", flush=True)

    work = Path(tempfile.mkdtemp(prefix="pitwall-gif-"))
    frames_dir = work / "frames"
    frames_dir.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PITWALL_", "VIRTUAL_ENV"))}
    env.update(
        PITWALL_DATA_DIR=str(work / "data"),
        PITWALL_HTTP_HOST="127.0.0.1",
        PITWALL_UDP_BIND="127.0.0.1",
        PITWALL_F1_UDP_PORT=str(args.udp_port),
        PITWALL_LLM_ENABLED="false",
        PITWALL_VOICE_ENABLED="false",
        PITWALL_RECORD_RAW="false",
        PITWALL_UPDATE_CHECK="off",
        PITWALL_DRIVER_NAME="Driver",
        PYTHONUNBUFFERED="1",
    )
    log = (work / "server.log").open("wb")
    server = subprocess.Popen(
        [sys.executable, "-c", LAUNCHER, str(dist.resolve()), str(args.http_port)],
        cwd=work,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    run = Run()
    frames: list[Path] = []
    hits = {"samples": 0, "delta": 0, "next_corner": 0, "ref_chip": 0, "coach_note": 0}
    try:
        deadline = time.monotonic() + 60
        while health(args.http_port) is None:
            if server.poll() is not None or time.monotonic() > deadline:
                raise SystemExit("the temporary Pitwall did not start (see its log above)")
            time.sleep(0.3)
        print(f"temporary Pitwall on http://127.0.0.1:{args.http_port}/ (data in a temporary folder)", flush=True)
        sender = threading.Thread(
            target=stream, args=(capture, args.udp_port, args.segment, args.record, run), daemon=True
        )
        with sync_playwright() as p:
            browser = p.chromium.launch()
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=args.scale, color_scheme="dark")
            # Headless Chromium refuses the screen wake lock unless it is granted (the page then says "Screen may
            # sleep", which a tablet on a stand would not).
            ctx.grant_permissions(["screen-wake-lock"], origin=f"http://127.0.0.1:{args.http_port}")
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{args.http_port}/#/drive/coach")
            page.wait_for_timeout(1500)
            print("streaming...", flush=True)
            sender.start()
            run.entered.wait()
            if run.error:
                raise SystemExit(f"sender failed: {run.error}")
            print(f"recording ({args.fps:g} fps)...", flush=True)
            every = 1.0 / args.fps
            t0 = time.monotonic()
            i = 0
            next_text = 0.0
            while not run.left.is_set():
                path = frames_dir / f"f{i:05d}.png"
                page.screenshot(path=str(path))
                frames.append(path)
                now = time.monotonic() - t0
                if now >= next_text:
                    text = page.inner_text("body")
                    if args.dump_text and hits["samples"] == 0:
                        print("---- page text (first sample) ----\n" + text + "\n----", flush=True)
                    check_text(text, words, hits)
                    next_text += 1.0
                i += 1
                time.sleep(max(0.0, t0 + i * every - time.monotonic()))
            elapsed = time.monotonic() - t0
            browser.close()
        run.done.wait(timeout=30)
        if run.error:
            raise SystemExit(f"sender failed: {run.error}")
        print(
            f"{len(frames)} frames in {elapsed:.1f} s; {run.sent} packets sent; page text samples: {hits}", flush=True
        )
        if args.strict:
            n = max(1, hits["samples"])
            weak = [k for k in ("delta", "next_corner", "ref_chip") if hits[k] / n < 0.8]
            if hits["coach_note"] / n < 0.6:
                weak.append("coach_note (60 %)")
            if weak:
                raise GateError(f"--strict: under 80 % of samples show {', '.join(weak)} ({hits})")
        duration = len(frames) * FRAME_MS / 1000
        if not MIN_S <= duration <= MAX_S:
            raise GateError(f"{len(frames)} frames make {duration:.1f} s, outside {MIN_S:g}-{MAX_S:g} s")

        images = [Image.open(f).convert("RGB") for f in frames]
        if args.scale != 1:  # sharper text: render at a higher scale, then downsample to the iPad-sized frame
            size = (VIEWPORT["width"], VIEWPORT["height"])
            images = [im.resize(size, Image.Resampling.LANCZOS) for im in images]
        w, h = images[0].size
        sample = Image.new("RGB", (w, h * 3))
        for k, idx in enumerate((0, len(images) // 2, len(images) - 1)):
            sample.paste(images[idx], (0, h * k))
        palette = sample.quantize(colors=args.colours, method=Image.Quantize.MEDIANCUT)
        quantized = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
        args.out.parent.mkdir(parents=True, exist_ok=True)
        part = args.out.with_name(args.out.name + ".part")
        # GIF delays are centiseconds: alternate 120/130 ms so the average is FRAME_MS (125) and playback is real time
        durations = [FRAME_MS - 5 if k % 2 == 0 else FRAME_MS + 5 for k in range(len(quantized))]
        quantized[0].save(
            part,
            format="GIF",
            save_all=True,
            append_images=quantized[1:],
            duration=durations,
            loop=0,
            optimize=True,
            disposal=1,
        )
        size = part.stat().st_size
        if size > MAX_BYTES:
            part.unlink()
            raise GateError(f"the GIF is {size / 1e6:.2f} MB, over {MAX_BYTES / 1e6:g} MB")
        part.replace(args.out)
        print(f"wrote {args.out} ({size / 1e6:.2f} MB, {len(frames)} frames, {duration:.1f} s, {w}x{h})", flush=True)
        return 0
    except GateError as e:
        print(f"GATE FAILED, no GIF written: {e}", file=sys.stderr, flush=True)
        return 1
    finally:
        run.left.set()
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
        log.close()
        if args.keep_log:
            shutil.copy(work / "server.log", args.keep_log)
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Record the README's Drive › Coach GIF from a real capture.")
    ap.add_argument("--capture", type=Path, default=None, help="a recorded F1 capture (default: the Austria excerpt)")
    ap.add_argument("--segment", type=parse_segment, action="append", default=None, metavar="START:END:SPEED")
    ap.add_argument("--record", type=parse_window, default=None, metavar="START:END")
    ap.add_argument("--dist", type=Path, default=ROOT / "web-react" / "dist", help="a web-react/dist built for /")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots" / "00-drive-coach-live.gif")
    ap.add_argument("--http-port", type=int, default=8830)
    ap.add_argument("--udp-port", type=int, default=20830)
    ap.add_argument("--fps", type=float, default=8.0)
    ap.add_argument("--scale", type=float, default=1.0, help="device scale factor of the screenshots")
    ap.add_argument("--colours", type=int, default=128)
    ap.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--dump-text", action="store_true", help="print the first page-text sample (for tuning)")
    ap.add_argument("--keep-log", type=Path, default=None, help="copy the temporary server's log here")
    args = ap.parse_args(argv)
    if args.capture is None:
        args.capture = EXCERPT
        args.segment = args.segment or [Segment(0, 270, 1)]
        args.record = args.record or (95.0, 110.0)
    if not args.segment or args.record is None:
        ap.error("--capture needs at least one --segment and a --record window")
    if not args.capture.is_file():
        ap.error(f"{args.capture} not found")
    return record(args)


if __name__ == "__main__":
    sys.exit(main())
