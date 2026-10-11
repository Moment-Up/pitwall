// Review › Session › Corners: "Line, inputs and balance" on each corner card (feat/technique spec §9), after the
// session averages. A HeroUI Disclosure, collapsed for beginners and on phones, with:
//   - the line at turn-in / apex / track-out over the session ("Apex: 1.2 m wider on 3 of 4 laps");
//   - how the car handled per phase, with "even on your best lap" (points at the car) or "not on your best lap"
//     (points at how it was driven);
//   - the top habits, verbatim from the backend (not the muted ones: brake figures with the braking assist on);
//   - lock-ups and wheelspin over the laps ("ABS on: no lock-up data");
//   - a mini line map, reference against the newest compared lap (intermediate and advanced), only when that lap's line
//     differs by 1 m or more somewhere (smaller differences are invisible at this scale).
// Each section says which laps it covers: the line compares the other laps with the reference; the balance counts
// every lap at racing pace, the reference too when it is from this session.
// Data: GET /api/technique/sessions/{id} (one request for the whole tab). Descriptions, never advice.

import { Chip, Disclosure, Skeleton } from "@heroui/react";
import { useMemo } from "react";
import { LineMap } from "../../../../components/viz/LineMap";
import type { UseApiResult } from "../../../../hooks/useApi";
import { PHASES, techniqueErrorKind, techniqueErrorText, type TechniqueSession } from "../../../../lib/endpoints/technique";
import type { Density } from "../../../../lib/review/density";
import { techniqueDensity, type TechniqueDensity } from "../../../../lib/technique/density";
import { refWordFor } from "../../../../lib/review/compare";
import { slipTotals, techniqueCorner, unavailableReasons } from "../../../../lib/technique/view";
import { finite, LINE_NOTABLE_M, linePointSummaryText, phaseSummaryText, refWorded } from "../../../../lib/technique/words";
import { useWideScreen } from "../../useMedia";
import { useTechnique } from "./data";
import { TechniqueGlossary } from "./TechniqueGlossary";

const HABITS_SHOWN = 3;

export interface CornerTechniqueCtx {
  state: Pick<UseApiResult<TechniqueSession>, "data" | "error">;
  td: TechniqueDensity;
}

/** One request for the Corners tab; every card reads its corner from it. */
export function useCornerTechnique(sessionId: string, density: Density): CornerTechniqueCtx {
  const state = useTechnique(sessionId);
  const phone = !useWideScreen();
  const td = useMemo(() => techniqueDensity(density, phone), [density, phone]);
  return { state, td };
}

function laps(n: number): string {
  return `${n} lap${n === 1 ? "" : "s"}`;
}

function Body({ corner, data, td }: { corner: string; data: TechniqueSession; td: TechniqueDensity }) {
  const c = techniqueCorner(data.corners, corner);
  if (!c) return <p className="m-0 text-sm text-muted">No technique measured at this corner yet.</p>;
  const lineReason = unavailableReasons(data.available, ["line"])[0] ?? null;
  const balanceReason = unavailableReasons(data.available, ["balance", "slip"])[0] ?? null;
  const beginner = td.level === "beginner";
  const ref = beginner ? refWordFor("beginner").sentence : "your reference";
  const lines = c.line
    ? (["turn_in", "apex", "track_out"] as const)
        .map((k) => linePointSummaryText(k, c.line?.points[k], c.line?.inside_known ?? false, LINE_NOTABLE_M, { simple: beginner, ref }))
        .filter((t): t is string => !!t)
    : [];
  const lineLaps = Math.max(0, ...(["turn_in", "apex", "track_out"] as const).map((k) => c.line?.points[k]?.laps ?? 0));
  const phases = c.balance
    ? PHASES.map((p) => ({ p, s: c.balance![p], text: phaseSummaryText(p, c.balance![p]) })).filter((x) => x.text)
    : [];
  const balanceLaps = Math.max(0, ...phases.map((x) => x.s.laps));
  const refHere = data.ref_session_id != null && data.ref_session_id === data.session_id;
  const slip = slipTotals(c);
  // muted habits (brake figures with the game's braking assist on) stay in Compare's greyed rows only
  const habits = c.habits.filter((h) => !h.muted).slice(0, HABITS_SHOWN);
  const view = c.line?.view ?? null;
  // the mini map only when the drawn lap's line differs by 1 m or more somewhere: smaller is invisible at this scale
  const viewLap = view ? c.laps.find((l) => l.lap_id === view.lap_id) : undefined;
  const mapWorthIt = !!viewLap?.line && Object.values(viewLap.line).some((v) => finite(v) && Math.abs(v) >= LINE_NOTABLE_M);
  return (
    <div className="grid gap-3">
      <div className="grid gap-1">
        <span className="flex flex-wrap items-center gap-1 text-xs font-semibold text-muted">
          Line against {data.ref_lap_number != null ? `${ref} (lap ${data.ref_lap_number})` : ref}
          {lineLaps > 0 && <span className="font-normal">· {laps(lineLaps)} compared</span>}
          {td.glossary && <TechniqueGlossary term="line_offset" />}
        </span>
        {lines.length ? (
          <ul className="m-0 grid list-none gap-0.5 p-0 text-sm">
            {lines.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-sm text-muted">{lineReason ?? "No line measured here."}</p>
        )}
      </div>
      {td.miniMap && view && view.ref_xz.length > 1 && mapWorthIt && (
        <figure className="m-0 grid gap-1">
          <div className="rounded-2xl bg-surface-secondary p-1">
            <LineMap
              refLine={view.ref_xz}
              lapLine={view.lap_xz}
              step={5}
              height={150}
              label={`Line through this corner: your reference and lap ${view.lap_number}`}
            />
          </div>
          <figcaption className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <span className="inline-flex items-center gap-1.5">
              <i aria-hidden="true" className="inline-block h-1 w-4 rounded bg-ref" /> Reference
            </span>
            <span className="inline-flex items-center gap-1.5">
              <i aria-hidden="true" className="inline-block h-0.5 w-4 rounded bg-cmp" /> Lap {view.lap_number}
            </span>
            <span>Pitwall does not know the track edges.</span>
          </figcaption>
        </figure>
      )}
      <div className="grid gap-1">
        <span className="flex flex-wrap items-center gap-1 text-xs font-semibold text-muted">
          How the car handled
          {balanceLaps > 0 && !balanceReason && (
            <span className="font-normal">
              · {laps(balanceLaps)} at racing pace{refHere ? `, ${ref} included` : ""}
            </span>
          )}
          {td.glossary && <TechniqueGlossary term="understeer" />}
        </span>
        {balanceReason ? (
          <p className="m-0 text-sm text-muted">{balanceReason}</p>
        ) : phases.length ? (
          <div className="flex flex-wrap gap-1.5">
            {phases.map(({ p, s, text }) => (
              <Chip
                key={p}
                size="sm"
                variant="soft"
                color={s.recurring && s.recurring !== "neutral" && s.verdict === "car" ? "warning" : "default"}
                className="h-auto min-h-7 py-1"
                data-verdict={s.verdict ?? "none"}
              >
                <Chip.Label className="whitespace-normal">{text}</Chip.Label>
              </Chip>
            ))}
          </div>
        ) : (
          <p className="m-0 text-sm text-muted">No balance measured here.</p>
        )}
      </div>
      {habits.length > 0 && (
        <div className="grid gap-1">
          <span className="text-xs font-semibold text-muted">Habits</span>
          <ul className="m-0 grid list-none gap-1 p-0">
            {habits.map((h) => (
              <li key={`${h.metric}:${h.text}`} className="rounded-2xl bg-surface-secondary px-3 py-2 text-sm leading-snug">
                {refWorded(td.simpleWording && h.text_simple ? h.text_simple : h.text, ref)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(slip.lockups || slip.wheelspin) && (
        <p className="m-0 text-sm text-muted">{[slip.lockups, slip.wheelspin].filter(Boolean).join(" · ")}</p>
      )}
    </div>
  );
}

export function CornerTechnique({ corner, ctx }: { corner: string; ctx: CornerTechniqueCtx }) {
  const { data, error } = ctx.state;
  if (!data && error && techniqueErrorKind(error) === "missing") return null;
  if (data && !techniqueCorner(data.corners, corner)) return null;
  return (
    <Disclosure defaultExpanded={!ctx.td.cornerCollapsed} className="border-t border-separator">
      <Disclosure.Heading className="m-0">
        <Disclosure.Trigger className="flex min-h-11 w-full items-center justify-between gap-2 text-left text-sm font-semibold">
          Line, inputs and balance
          <Disclosure.Indicator className="size-4" />
        </Disclosure.Trigger>
      </Disclosure.Heading>
      <Disclosure.Content>
        <Disclosure.Body style={{ padding: 0 }} className="pb-1">
          {data ? (
            <Body corner={corner} data={data} td={ctx.td} />
          ) : error ? (
            <p className="m-0 text-sm text-muted">{techniqueErrorText(error)}</p>
          ) : (
            <div aria-busy="true" aria-label="Loading line, inputs and balance" className="grid gap-2">
              <Skeleton className="h-4 w-3/4 rounded-lg" />
              <Skeleton className="h-4 w-1/2 rounded-lg" />
            </div>
          )}
        </Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}
