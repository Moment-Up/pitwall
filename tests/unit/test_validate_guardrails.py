"""Guardrails of the rig validation kit: it never touches capability statuses, SQL or the LLM, writes only under
<data_dir>/validation, and every report carries the fixed disclaimer. The API contract keys match the shared fixture
(``tests/fixtures/validation/example-run.json``, the dashboard's test fixture)."""

from __future__ import annotations

import ast
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pitwall.validate as pkg
from pitwall.capabilities import capability_matrix
from pitwall.core.live import LiveState
from pitwall.validate.kit import ValidationKit
from pitwall.validate.model import run_from_dict
from pitwall.validate.report import DISCLAIMER, build_report, render_markdown

PKG = Path(pkg.__file__).resolve().parent
EXAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "validation" / "example-run.json"
FORBIDDEN = ("pitwall.capabilities", "sqlite3", "pitwall.ai")


def imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}
    return out


def test_no_capabilities_sql_or_llm_imports() -> None:
    files = sorted(PKG.glob("*.py"))
    assert len(files) >= 11
    for f in files:
        bad = [m for m in imports(f) if any(m == x or m.startswith(x + ".") for x in FORBIDDEN)]
        assert not bad, (f.name, bad)
        src = f.read_text(encoding="utf-8")
        assert "execute(" not in src and "SELECT " not in src, f.name  # all SQL stays in storage/repo.py


class _Drivers:
    active_id = 1

    def list_drivers(self) -> list[Any]:
        return [object(), object()]

    def subscribe(self, fn: Any) -> None:
        pass

    def unsubscribe(self, fn: Any) -> None:
        pass


async def test_full_run_changes_no_capability_and_writes_only_its_folder(tmp_path: Path) -> None:
    before = copy.deepcopy(capability_matrix())
    rt = SimpleNamespace(
        live=LiveState(),
        drivers=_Drivers(),
        input_status=lambda: [],
        settings=SimpleNamespace(data_dir=tmp_path, llm_enabled=False),
    )
    kit = ValidationKit(rt.settings, rt, None, asyncio.get_running_loop())
    run = kit.start_run(None, "guardrail", False)
    for it in run.selected_items:
        kit.verdict(run.id, it, "worked", attestations={"times_match": True, "did_not_touch": True})
    kit.client_report(
        {
            "run_id": run.id,
            "client_id": "c1",
            "seq": 1,
            "device": "ipad",
            "standalone": True,
            "secure_context": True,
            "origin_kind": "localhost",
            "visibility": "visible",
            "route": "drive/coach",
            "wake": {"wanted": True, "state": "on"},
            "radio": None,
            "fps_10s": None,
        }
    )
    done = await kit.finish(run.id, "notes")
    await kit.close()
    assert capability_matrix() == before
    written = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if p.is_file())
    assert written and all(
        w.startswith(f"validation/{done.id}/") or w.startswith(f"validation\\{done.id}\\") for w in written
    )
    report = json.loads((tmp_path / "validation" / done.id / "report.json").read_text(encoding="utf-8"))
    assert report["disclaimer"] == DISCLAIMER
    md = (tmp_path / "validation" / done.id / "report.md").read_text(encoding="utf-8")
    assert DISCLAIMER in md and "## What this run can support (for the maintainer)" in md
    # nothing passes without live evidence, whatever the driver says (driver-only items aside)
    for it in done.items:
        assert it.result != "pass" or it.auto.verdict == "driver_only", it.id


def test_api_shapes_match_the_shared_fixture() -> None:
    """Golden check of the contract: the backend's Run and ValidationReport carry every key of the fixture."""
    ex = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    run = run_from_dict(ex["run"])
    rt = SimpleNamespace(
        live=LiveState(), drivers=_Drivers(), settings=SimpleNamespace(data_dir=Path(), llm_enabled=False)
    )
    kit = ValidationKit.__new__(ValidationKit)
    kit.rt = rt  # run_api reads nothing else
    api = ValidationKit.run_api(kit, run, "full", 1791834625.0)
    assert set(api) == set(ex["run"])
    assert set(api["context"]) == set(ex["run"]["context"])
    assert all(set(a) == set(b) for a, b in zip(api["items"], ex["run"]["items"], strict=True))
    for key, records in ex["run"]["evidence"].items():
        for mine, theirs in zip(api["evidence"][key], records, strict=True):
            assert set(theirs) <= set(mine), key  # additive keys allowed, none missing
    rep = build_report(run, 1791834625.0)
    assert set(rep) == set(ex["report_excerpt"])
    assert set(rep["run"]) == set(ex["report_excerpt"]["run"])
    assert set(rep["items"][0]) == set(ex["report_excerpt"]["items"][0])
    assert set(rep["candidates"][0]) == set(ex["report_excerpt"]["candidates"][0])
    assert set(rep["tiers"]) == set(ex["report_excerpt"]["tiers"])
    cues = next(
        t for it in rep["items"] if it["id"] == "cues_timing" for t in it["evidence_tables"] if t["title"] == "Calls"
    )
    assert cues["columns"][:6] == ex["report_excerpt"]["items"][0]["evidence_tables"][0]["columns"]
    assert cues["rows"][0][:6] == ex["report_excerpt"]["items"][0]["evidence_tables"][0]["rows"][0]
    md = render_markdown(rep, run)
    assert "−3.4" in md  # minus sign U+2212 in the Markdown
    assert "voice on (Kokoro, Parakeet)" in md
    text_only = {**rep, "run": {**rep["run"], "server": {**rep["run"]["server"], "stt": "none", "tts": "none"}}}
    assert "voice on (text only)" in render_markdown(text_only, run)  # never "voice on (None, None)"


def test_one_candidate_per_test() -> None:
    """A test that informs two status lines is one suggestion (listing both), not the same text twice."""
    ex = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    run = run_from_dict(ex["run"])
    rep = build_report(run, 1791834625.0)
    ids = [c["item_id"] for c in rep["candidates"]]
    assert len(ids) == len(set(ids)) == len(run.items)
    from pitwall.validate.catalog import BY_ID

    for c in rep["candidates"]:
        lines = [i.status_md for i in BY_ID[c["item_id"]].informs]
        assert c["status_md"] == "; ".join(lines)
