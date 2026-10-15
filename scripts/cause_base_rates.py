"""Base-rate check of the technique graph's causes on recorded captures (docs/knowledge.md, "Checking a cause against
its base rate"). Dev tool.

    uv run python scripts/cause_base_rates.py data/captures/X.pwcap [more.pwcap ...] [--date 2026-10-15]
        [--source pitwall_cause_base_rate]

Each capture is decoded and replayed through the real pipeline (``SessionManager`` + ``LapProcessor``) into a scratch
database in a temporary directory that is deleted afterwards, and every session is analysed as Review does
(``SessionAnalyzer``: every lap against the session's reference). Nothing is sent anywhere: no network, no ports, no
LLM, no voice; the captures are only read. A synthetic capture is refused: a base rate is measured on recorded laps.

For every cause and every live fault it explains, on the non-incident corner-laps of the usable comparisons (the
coaching rules ran on them) where the cause's evidence could be measured (each ``need = "all"`` discriminator's signal
measured and, with ``need = "any"`` ones, at least one of those): on how many of the corner-laps where the fault fired
the evidence held, against the corner-laps where it did not (the base rate). A corner-lap where the evidence could not
be measured is neither for nor against the cause. The script prints the table (with how often the cause was named:
its conditions and evidence, on the annotations Review shows) and the ``[[cause.measured]]`` blocks to paste into
``causes.toml``, and says which checks pass ``graph.BaseRate.passes`` (the rule for ``discriminates = true``).

Evidence tier: recorded (the captures replayed), never live validation; the source cited must be a ``recorded`` one.
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sys
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("PITWALL_LLM_ENABLED", "false")

from pitwall.analysis.coaching import is_incident
from pitwall.core.lap_processor import LapJob, LapProcessor
from pitwall.core.live import LiveState
from pitwall.core.session_analysis import SessionAnalysis, SessionAnalyzer
from pitwall.knowledge.annotate import LapSignals, Reader
from pitwall.knowledge.graph import BaseRate, Cause, Fault, Signal, TechniqueGraph, load_graph
from pitwall.storage.db import Database, DbWriter

SOURCE = "pitwall_cause_base_rate"


def evaluate(graph: TechniqueGraph, cause: Cause, read: Reader) -> tuple[bool, bool]:
    """``(measurable, holds)`` of a cause's evidence on one corner-lap: measurable when every ``need = "all"``
    signal and, with ``need = "any"`` ones, at least one of those was measured; holds as ``DriverKnowledge.causes``
    names it (its conditions aside)."""

    def value(signal: str) -> object:
        s = graph.get(signal, Signal)
        v = read(s) if s is not None else None
        return v.item() if hasattr(v, "item") else v  # numpy scalars as the Python value they hold

    alls = [d for d in cause.discriminators if d.need == "all"]
    anys = [d for d in cause.discriminators if d.need == "any"]
    vals = {d.signal: value(d.signal) for d in cause.discriminators}
    measurable = all(vals[d.signal] is not None for d in alls) and (
        not anys or any(vals[d.signal] is not None for d in anys)
    )
    holds = all(d.holds(vals[d.signal]) for d in alls) and (not anys or any(d.holds(vals[d.signal]) for d in anys))
    return measurable, holds


@dataclass(slots=True)
class PairCounts:
    """One cause against one live fault it explains."""

    cause: str
    fault: str
    fault_laps: int = 0
    fault_held: int = 0
    other_laps: int = 0
    other_held: int = 0
    unmeasured: int = 0
    named: int = 0

    def base_rate(self, date: str, source: str = SOURCE, note: str | None = None) -> BaseRate:
        return BaseRate(
            fault=self.fault,
            fault_laps=self.fault_laps,
            fault_held=self.fault_held,
            other_laps=self.other_laps,
            other_held=self.other_held,
            date=date,
            source=source,
            note=note,
        )


@dataclass(slots=True)
class Tally:
    pairs: dict[tuple[str, str], PairCounts] = field(default_factory=dict)
    sessions: int = 0
    laps: int = 0
    corner_laps: int = 0
    games: dict[str, int] = field(default_factory=dict)

    def pair(self, cause: str, fault: str) -> PairCounts:
        return self.pairs.setdefault((cause, fault), PairCounts(cause, fault))


def live_pairs(graph: TechniqueGraph) -> list[tuple[Cause, Fault]]:
    """Every cause with every live fault it explains (a fault that is not coached yet never fires: nothing to
    check)."""
    out: list[tuple[Cause, Fault]] = []
    for c in graph.causes:
        for fid in c.explains:
            f = graph.get(fid, Fault)
            if f is not None and f.status == "live" and f.kind is not None:
                out.append((c, f))
    return out


def count_session(sa: SessionAnalysis, graph: TechniqueGraph, tally: Tally) -> None:
    """Add one analysed session's corner-laps to ``tally`` (module docstring)."""
    if sa.model is None:
        return
    pairs = live_pairs(graph)
    for c, f in pairs:
        tally.pair(c.id, f.id)
    ref = sa.analyses.get(sa.ref_lap_id) if sa.ref_lap_id is not None else None
    corners = {c.name: c for c in sa.model.corners}
    laps = 0
    for lap_id, comp in sa.comparisons.items():
        an = sa.analyses.get(lap_id)
        if an is None or not comp.compatibility.ok:
            continue
        laps += 1
        signals = LapSignals({cd.corner: cd for cd in comp.corners}, an, ref, corners)
        kinds: dict[str, set[str]] = {}
        named: dict[str, set[tuple[str, str]]] = {}
        for o in sa.observations.get(lap_id, []):
            corner, kind = str(o.get("corner")), str(o.get("kind"))
            kinds.setdefault(corner, set()).add(kind)
            for cc in (o.get("knowledge") or {}).get("causes") or ():
                named.setdefault(corner, set()).add((str(cc.get("id")), kind))
        for cd in comp.corners:
            if is_incident(cd):
                continue
            tally.corner_laps += 1
            read = signals.reader(cd.corner)
            fired = kinds.get(cd.corner, set())
            for c, f in pairs:
                pc = tally.pair(c.id, f.id)
                pc.named += (c.id, str(f.kind)) in named.get(cd.corner, set())
                measurable, holds = evaluate(graph, c, read)
                if not measurable:
                    pc.unmeasured += 1
                elif f.kind in fired:
                    pc.fault_laps += 1
                    pc.fault_held += holds
                else:
                    pc.other_laps += 1
                    pc.other_held += holds
    if laps:
        tally.sessions += 1
        tally.laps += laps
        game = str(sa.session.get("game") or "unknown")
        tally.games[game] = tally.games.get(game, 0) + 1


class _SyncWorker:
    """The analysis worker, run in line (the replay waits for each lap, as the analysis thread would)."""

    def __init__(self, proc: LapProcessor) -> None:
        self.proc = proc

    def submit(self, job: LapJob) -> None:
        self.proc.process(job)

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *a, **k: None


def replay(capture: Path, root: Path) -> list[SessionAnalysis]:
    """Every session of one capture, replayed into a scratch database under ``root`` and analysed as Review does."""
    from pitwall.core.runtime import default_adapters
    from pitwall.core.session import SessionManager
    from pitwall.ingest.capture import CaptureReader
    from pitwall.ingest.router import PacketRouter

    meta = CaptureReader(capture).meta
    if meta.synthetic:
        raise SystemExit(f"{capture.name} is SYNTHETIC: a base rate is measured on recorded laps")
    db = Database(root / "pitwall.sqlite3")
    writer = DbWriter(db)
    live = LiveState()
    live.on_driver(None, None)
    sessions = SessionManager(
        writer,
        live,
        _SyncWorker(LapProcessor(db, writer, live)),  # type: ignore[arg-type]
        source=f"base-rate:{capture.name}",
        synthetic=False,
        capture_path=str(capture),
        overrides={"track_name": meta.extra.get("track_name")},
    )
    router = PacketRouter(default_adapters(), sessions, live)
    try:
        for p in CaptureReader(capture):
            router.handle(p)
        router.finish()
        writer.flush()
        with db.read() as c:
            ids = [r[0] for r in c.execute("SELECT id FROM sessions ORDER BY started_unix").fetchall()]
        analyzer = SessionAnalyzer(db)
        return [sa for sid in ids if (sa := analyzer.analyse(sid)) is not None]
    finally:
        writer.close()


def _share(held: int, laps: int) -> str:
    return f"{held}/{laps} ({100 * held / laps:.1f}%)" if laps else f"{held}/{laps} (-)"


def table(tally: Tally) -> str:
    rows = [
        f"{'cause':28} {'fault':16} {'fault corner-laps':>20} {'other corner-laps':>20} {'ratio':>6} {'named':>6}  pass"
    ]
    for (cid, fid), pc in tally.pairs.items():
        r = pc.base_rate("2000-01")
        ratio = "-" if r.ratio is None else ("inf" if math.isinf(r.ratio) else f"{r.ratio:.2f}")
        rows.append(
            f"{cid:28} {fid:16} {_share(pc.fault_held, pc.fault_laps):>20} {_share(pc.other_held, pc.other_laps):>20} "
            f"{ratio:>6} {pc.named:>6}  {'yes' if r.passes else 'no'}"
        )
    return "\n".join(rows)


def toml_blocks(tally: Tally, date: str, source: str) -> str:
    """The ``[[cause.measured]]`` tables, one per checked pair, grouped by cause (paste each under its cause)."""
    out: list[str] = []
    for (cid, _fid), pc in tally.pairs.items():
        out.append(
            f'# {cid}\n[[cause.measured]]\nfault = "{pc.fault}"\nfault_laps = {pc.fault_laps}\n'
            f"fault_held = {pc.fault_held}\nother_laps = {pc.other_laps}\nother_held = {pc.other_held}\n"
            f'date = "{date}"\nsource = "{source}"\n'
        )
    return "\n".join(out)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("captures", nargs="+", type=Path)
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--source", default=SOURCE, help="the recorded source the check cites")
    args = ap.parse_args(list(argv) if argv is not None else None)
    graph = load_graph()
    if not graph.valid:
        print("the technique graph does not load:", *graph.errors, sep="\n- ", file=sys.stderr)
        return 1
    tally = Tally()
    with tempfile.TemporaryDirectory(prefix="pitwall-base-rate-") as tmp:
        for i, cap in enumerate(args.captures):
            root = Path(tmp) / f"{i:03d}"
            root.mkdir()
            for sa in replay(cap, root):
                count_session(sa, graph, tally)
            print(f"{cap.name}: replayed", file=sys.stderr, flush=True)
    games = ", ".join(f"{n} {g}" for g, n in sorted(tally.games.items()))
    print(
        f"{tally.sessions} sessions with a usable comparison ({games}), {tally.laps} compared laps, "
        f"{tally.corner_laps} non-incident corner-laps\n"
    )
    print(table(tally))
    print("\n" + toml_blocks(tally, args.date, args.source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
