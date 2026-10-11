"""``pitwall validate``: review rig validation runs from the files (no server needed).

    pitwall validate list                          newest first
    pitwall validate show [RUN|latest]             item table, reasons and key metrics
    pitwall validate report [RUN|latest] [--json] [--out PATH] [--redact-transcripts]
    pitwall validate catalog [ITEM]                what each test asks the driver to do

Exit code 1 for an unknown run or a file of an unknown format. Reading never changes a run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

if TYPE_CHECKING:
    from pitwall.validate.model import Run
    from pitwall.validate.store import ValidationStore

validate_app = typer.Typer(add_completion=False, help="Rig validation runs (Setup › Validation)", no_args_is_help=True)


def _store() -> ValidationStore:
    from pitwall.config import get_settings
    from pitwall.validate.store import ValidationStore

    return ValidationStore(get_settings().data_dir)


def _resolve(run: str) -> str:
    store = _store()
    if run == "latest":
        ids = store.run_ids()
        if not ids:
            typer.echo("No validation runs yet.")
            raise typer.Exit(1)
        return str(ids[0])
    from pitwall.validate.store import is_run_id

    if not is_run_id(run) or not (store.run_dir(run) / "run.json").is_file():
        typer.echo(f"Unknown run: {run}")
        raise typer.Exit(1)
    return run


def _load(run_id: str) -> Run:
    from pitwall.validate.model import run_from_dict

    try:
        return run_from_dict(_store().load_run(run_id))
    except ValueError as e:
        typer.echo(f"Cannot read run {run_id}: {e}")
        raise typer.Exit(1) from e


def _when(t: float | None) -> str:
    return "-" if t is None else time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


@validate_app.command("list")
def list_runs() -> None:
    """Validation runs, newest first."""
    rows = _store().list_runs()
    if not rows:
        typer.echo("No validation runs yet.")
        return
    for r in rows:
        c = r["counts"]
        tiers = ",".join(r["tiers"]) or "-"
        typer.echo(
            f"{r['id']}  {_when(r['started_unix'])}  {r['status']:<9} pass {c['pass']}  fail {c['fail']}  "
            f"review {c['needs_review']}  not run {c['not_run']}  skipped {c['skipped']}  {tiers}"
            + (f"  {r['label']}" if r.get("label") else "")
        )


@validate_app.command()
def show(run: Annotated[str, typer.Argument(help="Run id or 'latest'")] = "latest") -> None:
    """One run: each test's result, what Pitwall saw and why."""
    from pitwall.validate.catalog import BY_ID
    from pitwall.validate.report import AUTO_WORDS, RESULT_WORDS

    rid = _resolve(run)
    r = _load(rid)
    typer.echo(f"Run {r.id}  {r.status}  started {_when(r.started_unix)}  ended {_when(r.ended_unix)}")
    typer.echo(
        f"pitwall {r.server.pitwall_version} ({r.server.git_commit or '-'})  {r.server.os}  "
        f"voice {'on' if r.server.voice_enabled else 'off'}  LLM {'on' if r.server.llm_enabled else 'off'}"
    )
    counts = r.evidence.tier_counts()
    parts = ", ".join(f"{k} {v}" for k, v in counts.items() if v)
    typer.echo(f"Evidence: {parts}" if parts else "Evidence: none")
    for it in r.items:
        cat = BY_ID.get(it.id)
        title = cat.title if cat else it.id
        driver = it.marks[-1].verdict if it.marks else "-"
        typer.echo(
            f"\n{title}\n  result {RESULT_WORDS.get(it.result, it.result)}  driver {driver}  "
            f"pitwall {AUTO_WORDS.get(it.auto.verdict, it.auto.verdict)}  tier {it.auto.tier or '-'}"
        )
        for reason in it.auto.reasons[:4]:
            typer.echo(f"  - {reason}")
        keys = [f"{k}={v}" for k, v in it.auto.metrics.items() if v is not None][:8]
        if keys:
            typer.echo("  " + "  ".join(keys))


@validate_app.command()
def report(
    run: Annotated[str, typer.Argument(help="Run id or 'latest'")] = "latest",
    as_json: Annotated[bool, typer.Option("--json", help="The report as JSON")] = False,
    out: Annotated[Path | None, typer.Option("--out", help="Write to this file instead of the terminal")] = None,
    redact_transcripts: Annotated[
        bool, typer.Option("--redact-transcripts", help="Replace the driver's transcripts with a placeholder")
    ] = False,
) -> None:
    """The evidence report (Markdown, or JSON with --json)."""
    from pitwall.validate.report import build_report, render_markdown

    rid = _resolve(run)
    r = _load(rid)
    rep = build_report(r, r.ended_unix or time.time(), redact=redact_transcripts)
    text = json.dumps(rep, indent=1, ensure_ascii=False) if as_json else render_markdown(rep, r)
    if out is not None:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@validate_app.command()
def catalog(item: Annotated[str | None, typer.Argument(help="One test id")] = None) -> None:
    """What each test asks the driver to do."""
    from pitwall.validate.catalog import BY_ID, CATALOG

    if item is not None and item not in BY_ID:
        typer.echo(f"Unknown test: {item}. Tests: {', '.join(BY_ID)}")
        raise typer.Exit(1)
    for it in [BY_ID[item]] if item else list(CATALOG):
        typer.echo(
            f"{it.id}  {it.title}  ({it.group}, about {it.est_minutes} min{', optional' if it.optional else ''})"
        )
        if item:
            typer.echo(f"  {it.summary}")
            for pre in it.prerequisites:
                typer.echo(f"  Before you start: {pre}")
            for i, s in enumerate(it.steps, 1):
                typer.echo(f"  {i}. {s.text}" + (f" ({s.detail})" if s.detail else ""))
            typer.echo(f"  How it is measured: {it.rule_text}")
