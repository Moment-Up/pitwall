// The Session complete card (design spec 4.7 #4, 4.9; mockup bigCard "ended"), spanning the hero, coach and delta
// areas once the session is over: four Pro KPI tiles, one Work on and one Went well (D6 picks, else the top
// observations), and Review this session (64 px).
//
//   [Best lap PB 1:30.702 · lap 9] [Clean laps 9 of 12] [Gained today 2.5 s faster] [To the family record 0.29 s slower]
//   (!) Work on · T15 Stowe …                    (✓) Went well · T9 Copse …   (corner: official label and name)
//                                                                         [ Review this session ]
// coachref: a drill driven in this session takes an empty slot (its laps' coaching is the drill's):
//   (◎) Drill T12 · Brake point: 2 of 2 on the point (2 of 5 laps)
//
// LAZY (React.lazy in SessionCompleteSlot.tsx): Pro KPI imports AreaChart and so Recharts at module level, which
// must stay out of the eager Drive bundle (spec 4.9, 4.11). Values are TimingValue-style numerals in KPI.Content,
// never KPI.Value (it animates and formats plain numbers). Stationary: full coaching text, no glance texts.

import { CircleCheck, Target, TriangleExclamation } from "@gravity-ui/icons";
import { ItemCard, KPIGroup } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import { Button, Card } from "@heroui/react";
import type { ReactNode } from "react";
import { TimingLegend, TimingTag, Unknown } from "../../../components/ui";
import type { CoachPoint } from "../../../lib/drive/coach";
import type { EndedCard, EndedChange } from "../../../lib/drive/model";
import { router } from "../../../lib/router";
import { TimeText } from "./parts";

function Tile({ title, tag, children, sub }: { title: string; tag?: ReactNode; children: ReactNode; sub?: string | null }) {
  return (
    <KPI>
      <KPI.Header>
        <KPI.Title>{title}</KPI.Title>
        {tag}
      </KPI.Header>
      <KPI.Content>
        <span className="pwc-end__v">{children}</span>
      </KPI.Content>
      <span className="pwc-end__s">{sub ?? " "}</span>
    </KPI>
  );
}

function Point({ point, kind, corner }: { point: CoachPoint | null; kind: "work" | "good"; corner: string | null }) {
  // "Work on · T15 Stowe": the corner reads without the sentence (mockup).
  const title = `${kind === "work" ? "Work on" : "Went well"}${point && corner ? ` · ${corner}` : ""}`;
  return (
    <ItemCard variant="secondary" className="pwc-item" data-tone={kind === "work" ? "warning" : "success"}>
      <ItemCard.Icon className="pwc-item__icon">
        {kind === "work" ? <TriangleExclamation aria-hidden="true" /> : <CircleCheck aria-hidden="true" />}
      </ItemCard.Icon>
      <ItemCard.Content>
        <ItemCard.Title>{title}</ItemCard.Title>
        <ItemCard.Description>
          {point?.text ?? (kind === "work" ? "No point to work on from this session" : "No highlight from this session")}
          {point?.evidence ? ` (${point.evidence})` : ""}
        </ItemCard.Description>
      </ItemCard.Content>
    </ItemCard>
  );
}

/** coachref: the drill driven in this session (lib/drive/drill.ts endedDrill). */
function DrillItem({ title, line }: { title: string; line: string }) {
  return (
    <ItemCard variant="secondary" className="pwc-item" data-tone="accent">
      <ItemCard.Icon className="pwc-item__icon">
        <Target aria-hidden="true" />
      </ItemCard.Icon>
      <ItemCard.Content>
        <ItemCard.Title>{title}</ItemCard.Title>
        <ItemCard.Description>{line}</ItemCard.Description>
      </ItemCard.Content>
    </ItemCard>
  );
}

/** A gain or gap the one way every page says it (lib/bests.ts changeWords): the amount large, the word beside it
 * ("4.8 s faster", "0.29 s slower"); "PB" / "REC" / "level" as words; "-" unknown. */
function Change({ c, label, ahead = false }: { c: EndedChange; label: string; ahead?: boolean }) {
  if (!c.amount) return <TimeText text={c.text} label={label} />;
  return (
    <>
      <TimeText text={c.amount} label={label} className={ahead && c.word === "faster" ? "text-ahead" : ""} />
      {c.word && <span className="pwc-end__w">{c.word}</span>}
    </>
  );
}

export interface SessionCompleteCardProps {
  ended: EndedCard;
  tier: 1 | 2;
  /** Work on / Went well corners by official label and name (coach/view.ts endedCorners), null when unknown. */
  corners?: { workOn: string | null; wentWell: string | null };
}

export function SessionCompleteCard({ ended, tier, corners }: SessionCompleteCardProps) {
  const { best, clean, gained, toRecord, toYourBest } = ended;
  const drill = ended.drill ?? null;
  const yourBest = !toYourBest || toYourBest.text === "PB" ? null : toYourBest.word ? `${toYourBest.text} than your best` : "level with your best";
  const recordSub = [toRecord?.sub, yourBest].filter(Boolean).join(" · ");
  return (
    <Card className="pwc-end pwc-span3">
      <KPIGroup className="pwc-end__kpis">
        <Tile title="Best lap" tag={best?.tag ? <TimingTag status={best.status} size="md" /> : null} sub={best?.sub}>
          {best ? <TimeText text={best.text} status={best.status} label="Best lap" /> : <Unknown />}
        </Tile>
        <KPIGroup.Separator />
        <Tile title="Clean laps" sub={clean.sub}>
          {clean.clean}
          <span className="text-xl text-muted">of {clean.total}</span>
        </Tile>
        <KPIGroup.Separator />
        <Tile title="Gained today" sub={gained.sub}>
          <Change c={gained} label="Gained today" ahead />
        </Tile>
        <KPIGroup.Separator />
        <Tile title="To the family record" sub={recordSub || null}>
          {toRecord ? <Change c={toRecord} label="To the family record" /> : <Unknown />}
        </Tile>
      </KPIGroup>
      {drill && !ended.workOn ? (
        <DrillItem title={drill.title} line={drill.line} />
      ) : (
        <Point point={ended.workOn} kind="work" corner={corners?.workOn ?? null} />
      )}
      {drill && ended.workOn && !ended.wentWell ? (
        <DrillItem title={drill.title} line={drill.line} />
      ) : (
        <Point point={ended.wentWell} kind="good" corner={corners?.wentWell ?? null} />
      )}
      <div className="pwc-end__actions">
        <TimingLegend tier={tier} className="mr-auto self-center" />
        <Button
          variant="primary"
          size="lg"
          className="pwc-glove"
          isDisabled={!ended.sessionId}
          onPress={() => ended.sessionId && router.navigate(`/review/sessions/${ended.sessionId}`)}
        >
          Review this session
        </Button>
      </div>
    </Card>
  );
}
