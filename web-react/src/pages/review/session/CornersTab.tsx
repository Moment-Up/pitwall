// Session › Corners (spec 6.6): "what keeps happening at Stowe?". One HeroUI Card per corner (official label and
// name), sorted by average time lost: the session averages from corner_summary in plain words (time, brake point mean
// and spread, slowest speed), a FOCUS chip when the corner is in the live cue focus at this track, and every lap where
// the coach spoke there (its text verbatim, with an evidence line). Filter: a Pro Segment Work on · Went well · All.
// Incident observations are greyed, "not used for technique advice". "See it on the lap" opens Compare at the corner.

import { Button, Card, Chip, Disclosure } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import { useMemo, useState, type Key } from "react";
import { CornerTag } from "../../../components/ui";
import { useLive } from "../../../hooks/stores";
import type { SessionAnalysis, SessionDetail } from "../../../lib/endpoints/review";
import { router } from "../../../lib/router";
import { apexGameM } from "../../../lib/review/compare";
import {
  averageLines,
  averageTimeText,
  CORNERS_FILTERS,
  cornerCards,
  filterCards,
  filterCounts,
  lapsSpokenText,
  cornersShown,
  liveFocusFor,
  notesShown,
  type CornerCard,
  type CornerCardObservation,
  type CornersFilter,
} from "../../../lib/review/corner-cards";
import type { Density } from "../../../lib/review/density";
import { comparePath } from "../../../lib/review/links";
import { timeSigned, timeWords } from "../../../lib/review/compare";
import { useWideScreen } from "../useMedia";
import { CornerTechnique, useCornerTechnique, type CornerTechniqueCtx } from "./technique/CornerTechnique"; // feat/technique


function ObservationRow({ o }: { o: CornerCardObservation }) {
  if (o.incident) {
    return (
      <li className="grid gap-0.5 rounded-2xl border border-separator px-3 py-2 opacity-70">
        <span className="text-xs font-medium text-muted">Lap {o.lapNumber} · incident · not used for technique advice</span>
        <span className="text-sm text-muted">{o.text}</span>
      </li>
    );
  }
  return (
    <li className="grid gap-0.5 rounded-2xl bg-surface-secondary px-3 py-2">
      <span className="flex items-center gap-2 text-xs font-medium text-muted">
        Lap {o.lapNumber}
        <Chip size="sm" variant="soft" color={o.positive ? "success" : "warning"}>
          <Chip.Label>{o.positive ? "Went well" : "Work on"}</Chip.Label>
        </Chip>
      </span>
      <span className="text-sm leading-relaxed">{o.text}</span>
      {o.evidence && <span className="text-xs text-muted">{o.evidence}</span>}
    </li>
  );
}

function CornerCardView({
  card,
  signed,
  onCompare,
  technique,
}: {
  card: CornerCard;
  signed: boolean;
  onCompare: (c: CornerCard) => void;
  /** feat/technique: line, inputs and balance for this corner. */
  technique?: CornerTechniqueCtx;
}) {
  const [all, setAll] = useState(false);
  const limit = notesShown(useWideScreen());
  const lines = averageLines(card.summary);
  const timeLine = averageTimeText(card.summary, signed);
  const shown = all ? card.observations : card.observations.slice(0, limit);
  const spoken = lapsSpokenText(card);
  const tone =
    card.meanTimeS == null || Math.abs(card.meanTimeS) < 0.01 ? "text-foreground" : card.meanTimeS > 0 ? "text-behind" : "text-ahead";
  return (
    <Card className="gap-3 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <CornerTag label={card.label} name={card.name} focus={card.focus} size="md" />
        {card.meanTimeS != null && (
          <span className={`pw-num ml-auto text-xl ${tone}`} aria-hidden="true">
            {signed ? timeSigned(card.meanTimeS) : timeWords(card.meanTimeS)}
          </span>
        )}
      </div>
      {timeLine && <p className="m-0 -mt-1 text-sm text-muted">{timeLine}</p>}
      {lines.length > 0 ? (
        <dl className="m-0 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
          {lines.map((l) => (
            <div key={l.label} className="contents">
              <dt className="text-muted">{l.label}</dt>
              <dd className="m-0">{l.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="m-0 text-sm text-muted">No session averages for this corner.</p>
      )}
      {/* feat/technique */}
      {technique && <CornerTechnique corner={card.key} ctx={technique} />}
      {card.observations.length > 0 ? (
        <div className="grid gap-2">
          <span className="text-sm font-medium">{spoken ? `The coach spoke here on ${spoken.toLowerCase()}` : "The coach spoke here"}</span>
          <ul className="m-0 grid list-none gap-2 p-0">
            {shown.map((o) => (
              <ObservationRow key={o.key} o={o} />
            ))}
          </ul>
        </div>
      ) : (
        <p className="m-0 text-sm text-muted">The coach had nothing to say here in this session.</p>
      )}
      {/* one row: the notes' Show all beside See it on the lap (a phone's page stays short, acceptance B7) */}
      <div className="mt-auto flex flex-wrap items-center gap-2">
        <Button variant="secondary" className="min-h-11" onPress={() => onCompare(card)}>
          See it on the lap
        </Button>
        {card.observations.length > limit && (
          <Button variant="ghost" size="sm" className="min-h-11" onPress={() => setAll((v) => !v)}>
            {all ? "Show fewer notes" : `Show all ${card.observations.length} notes`}
          </Button>
        )}
      </div>
    </Card>
  );
}

export interface CornersTabProps {
  session: SessionDetail;
  analysis: SessionAnalysis | undefined;
  density: Density;
}

const EMPTY: Record<CornersFilter, string> = {
  work: "Nothing to work on at any corner: the coach found nothing above its thresholds in this session.",
  good: "No corner earned a 'went well' from the coach in this session yet.",
  all: "No corners measured in this session yet.",
};

export function CornersTab({ session, analysis, density }: CornersTabProps) {
  // A string of the focus corners, not the snapshot: snapshots arrive 20 times a second, the focus rarely changes.
  const focusKey = useLive((s) => liveFocusFor(s.snap as Parameters<typeof liveFocusFor>[0], session).join("\n"));
  const focus = useMemo(() => (focusKey ? focusKey.split("\n") : []), [focusKey]);
  const model = analysis?.track_model ?? null;
  const cards = useMemo(
    () => cornerCards(analysis, model, { focus, simple: density.simpleWording }),
    [analysis, model, focus, density.simpleWording],
  );
  const counts = filterCounts(cards);
  const [filter, setFilter] = useState<CornersFilter>(counts.work > 0 || !cards.length ? "work" : "all");
  const wide = useWideScreen();
  const [allCorners, setAllCorners] = useState(false);
  const filtered = filterCards(cards, filter);
  const shown = filtered.slice(0, cornersShown(wide, filtered.length, allCorners));
  const lengthM = session.track_length_m ?? null;
  const technique = useCornerTechnique(session.id, density); // feat/technique

  const onCompare = (c: CornerCard) =>
    router.navigate(
      comparePath(session.id, { ref: analysis?.ref_lap_id ?? null, lap: c.latestLapId, at: apexGameM(model, c.key, lengthM) }),
    );

  if (!analysis) {
    return <p className="m-0 text-sm text-muted">Loading the corners…</p>;
  }
  if (analysis.ref_lap_id == null) {
    return (
      <p className="m-0 text-sm text-muted">
        No corner averages yet: they start once there is a clean lap at this track to compare with (the reference lap).
      </p>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Segment aria-label="Show corners" size="lg" selectedKey={filter} onSelectionChange={(k: Key) => setFilter(k as CornersFilter)}>
          {CORNERS_FILTERS.map((f) => (
            <Segment.Item key={f.id} id={f.id} className="h-11 px-4 text-[15px]">
              {f.label}
              <span className="ml-1.5 text-muted">{counts[f.id]}</span>
            </Segment.Item>
          ))}
        </Segment>
        <span className="text-sm text-muted">
          {filter === "good" ? "Most time gained first" : "Most time lost first"} · averages over the laps compared with the
          reference
        </span>
      </div>
      {shown.length ? (
        <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((c) => (
            <CornerCardView key={c.key} card={c} signed={density.signedBadges} onCompare={onCompare} technique={technique} />
          ))}
        </div>
      ) : null}
      {shown.length < filtered.length ? (
        <div>
          <Button variant="secondary" className="min-h-11" onPress={() => setAllCorners(true)}>
            Show all {filtered.length} corners
          </Button>
        </div>
      ) : null}
      {shown.length ? null : (
        <p className="m-0 text-sm text-muted">{EMPTY[filter]}</p>
      )}
      {cards.some((c) => c.observations.some((o) => o.incident)) && (
        <Disclosure>
          <Disclosure.Heading className="m-0">
            <Disclosure.Trigger className="flex min-h-11 items-center gap-2 text-sm text-muted">
              Why some laps are greyed
              <Disclosure.Indicator className="size-4" />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body style={{ padding: 0 }} className="text-sm text-muted">
              A lap that lost several seconds at one corner looks like an incident (a spin, contact, going off or a
              slow-down). The coach never turns those into technique advice, so they are shown for the record only.
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      )}
    </div>
  );
}
