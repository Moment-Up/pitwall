"""Files of the rig validation kit: ``<data_dir>/validation/<run_id>/{run.json, report.json, report.md}``.

Nothing else is written, and nothing outside that folder. Writes are atomic (a ``.tmp`` sibling, then
``compat.replace_file``). Run ids are validated everywhere (``RUN_ID``), so a request can never reach another path.
No retention policy: runs are small and ``pitwall validate`` never deletes.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

import orjson

from pitwall.compat import replace_file
from pitwall.validate.model import FORMAT, RESULTS

log = logging.getLogger(__name__)

RUN_ID_PATTERN = r"^\d{8}-\d{6}-[0-9a-f]{4}$"
_RUN_ID_LEN = 20
RUN_FILE = "run.json"
_HEAD_BYTES = 1024  # label <= 80 characters: "status" is always inside the first kilobyte
_ACTIVE = re.compile(rb'"status"\s*:\s*"active"')
REPORT_JSON = "report.json"
REPORT_MD = "report.md"


def is_run_id(run_id: str) -> bool:
    if len(run_id) != _RUN_ID_LEN:
        return False
    date, _, rest = run_id.partition("-")
    clock, _, tag = rest.partition("-")
    return (
        len(date) == 8
        and date.isascii()
        and date.isdigit()
        and len(clock) == 6
        and clock.isascii()
        and clock.isdigit()
        and len(tag) == 4
        and all(ch in "0123456789abcdef" for ch in tag)
    )


def new_run_id(now: float | None = None) -> str:
    t = time.localtime(time.time() if now is None else now)
    return time.strftime("%Y%m%d-%H%M%S", t) + "-" + secrets.token_hex(2)


def dumps(data: Any) -> bytes:
    return orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS)


class ValidationStore:
    def __init__(self, data_dir: Path) -> None:
        self.root = Path(data_dir) / "validation"

    def run_dir(self, run_id: str) -> Path:
        if not is_run_id(run_id):
            raise ValueError(f"invalid run id {run_id!r}")
        return self.root / run_id

    # ------------------------------------------------------------------ writes (call from a worker thread)
    def write_bytes(self, run_id: str, name: str, data: bytes) -> Path:
        if name not in (RUN_FILE, REPORT_JSON, REPORT_MD):
            raise ValueError(f"not a validation file: {name!r}")
        folder = self.run_dir(run_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        tmp = folder / (name + ".tmp")
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        replace_file(tmp, path)
        return path

    def save_run(self, run_id: str, data: bytes) -> Path:
        return self.write_bytes(run_id, RUN_FILE, data)

    def save_report(self, run_id: str, report: dict[str, Any], markdown: str) -> None:
        self.write_bytes(run_id, REPORT_JSON, dumps(report))
        self.write_bytes(run_id, REPORT_MD, markdown.encode("utf-8"))

    # ------------------------------------------------------------------ reads
    def load_run(self, run_id: str) -> dict[str, Any] | None:
        path = self.run_dir(run_id) / RUN_FILE
        if not path.is_file():
            return None
        data = orjson.loads(path.read_bytes())
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a validation run")
        return data

    def load_report(self, run_id: str) -> dict[str, Any] | None:
        path = self.run_dir(run_id) / REPORT_JSON
        if not path.is_file():
            return None
        data = orjson.loads(path.read_bytes())
        return data if isinstance(data, dict) else None

    def load_report_md(self, run_id: str) -> str | None:
        path = self.run_dir(run_id) / REPORT_MD
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def run_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted((p.name for p in self.root.iterdir() if p.is_dir() and is_run_id(p.name)), reverse=True)

    def list_runs(self) -> list[dict[str, Any]]:
        """``RunSummary`` of every readable run, newest first. Unreadable or unknown-format files are skipped with a
        warning (never raised)."""
        out: list[dict[str, Any]] = []
        for run_id in self.run_ids():
            try:
                data = self.load_run(run_id)
            except (OSError, ValueError) as e:
                log.warning("validation run %s unreadable: %s", run_id, e)
                continue
            if data is None:
                continue
            if data.get("format") != FORMAT:
                log.warning("validation run %s: unknown format %r", run_id, data.get("format"))
                continue
            out.append(summary_of(data))
        return out

    def find_active(self) -> str | None:
        """The newest run whose status is ``active`` (at most one should exist). Only files whose head says so are
        parsed (``run.json`` starts with format, id, label, status), so start-up never reads every past run."""
        for run_id in self.run_ids():
            path = self.run_dir(run_id) / RUN_FILE
            try:
                with path.open("rb") as f:
                    head = f.read(_HEAD_BYTES)
            except OSError:
                continue
            if not _ACTIVE.search(head):
                continue
            try:
                data = self.load_run(run_id)
            except (OSError, ValueError):
                continue
            if data is not None and data.get("status") == "active" and data.get("format") == FORMAT:
                return run_id
        return None


def summary_of(data: dict[str, Any]) -> dict[str, Any]:
    """``RunSummary`` from a ``run.json`` dict (only the summary keys are read)."""
    counts = dict.fromkeys(RESULTS, 0)
    tiers: set[str] = set()
    for it in data.get("items") or []:
        r = it.get("result")
        if r in counts:
            counts[r] += 1
    ev = data.get("evidence")
    if isinstance(ev, dict):
        for key in ("cues", "ptt", "proactive", "laps", "switches", "synth", "sessions", "input_phases"):
            for rec in ev.get(key) or []:
                if isinstance(rec, dict) and rec.get("tier"):
                    tiers.add(str(rec["tier"]))
    order = ("live", "recorded", "synthetic", "loopback", "unknown")
    return {
        "id": data.get("id"),
        "label": data.get("label"),
        "status": data.get("status"),
        "started_unix": data.get("started_unix"),
        "ended_unix": data.get("ended_unix"),
        "current_item": data.get("current_item"),
        "counts": counts,
        "tiers": [t for t in order if t in tiers],
    }
