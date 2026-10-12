// Setup › Rig › Walkthrough (spec 7.2, the default view; `#/setup/rig/walk/<section>/<n>`): a glance screen for the
// driver in the seat changing settings on the wheel's tuning menu or in the game, with the iPad at about 70 cm.
//
//   ┌ Rig setup for James · F1 25 · PS5 · GT DD Pro 5 Nm · CSL pedals            [Something not right?] [Change rig] ┐
//   │  ① Base mode ─── ② Wheel menu ─── ③ In game ─── ④ Pedals ─── ⑤ Check on track      Pro Stepper (horizontal) │
//   ├──────────────────────────────────────────────────────────┬──────────────────────────────────────────────────┤
//   │ step card (chamfer, 96 px value, ‹ Previous / Done, next ›)│ every item of the section (Pro ListView)        │
//
// The plan comes from lib/setup/walkthrough.ts (research how-to steps + the recommendation's steps and rows). The
// position lives in the route (replace, no history entry per step); ticks live on this device per driver and game.

import { Alert, Button, Card, Link } from "@heroui/react";
import { Stepper } from "@heroui-pro/react";
import { useEffect, useMemo, useState } from "react";
import { useRadio } from "../../../components/radio";
import type { GameId, Hardware, Recommendation } from "../../../lib/endpoints/rig";
import { href, router } from "../../../lib/router";
import { GAME_LABEL, hardwareLine, rigPath, type RigQuery } from "../../../lib/setup/rig";
import {
  WALKTHROUGH,
  buildPlan,
  guideRun,
  itemAt,
  locate,
  neighbour,
  progressScope,
  relevantMistakes,
  sectionCounts,
  sectionDone,
  tick,
  untick,
  type WalkPos,
} from "../../../lib/setup/walkthrough";
import { DetailSheet, type DetailTarget } from "./DetailSheet";
import { SectionList } from "./SectionList";
import { StepCard } from "./StepCard";
import { TickIcon } from "./parts";
import { TroubleSheet } from "./TroubleSheet";
import { useWalkProgress } from "./useWalkProgress";

export interface WalkthroughViewProps {
  rec: Recommendation;
  hw: Hardware;
  game: GameId;
  driverId: number | null;
  driverName: string | null;
  query: RigQuery;
  section: string | null;
  n: number | null;
}

export function WalkthroughView({ rec, hw, game, driverId, driverName, query, section, n }: WalkthroughViewProps) {
  const doc = WALKTHROUGH;
  const plan = useMemo(() => buildPlan(rec, hw, game, doc), [rec, hw, game, doc]);
  const { ticks, setTicks } = useWalkProgress(progressScope(game, driverId));
  const pos = locate(plan, section, n, ticks);
  const sec = plan.sections[pos.s]!;
  const item = itemAt(plan, pos);
  const mistakes = useMemo(() => relevantMistakes(doc, game, hw), [doc, game, hw]);
  const [detail, setDetail] = useState<DetailTarget | null>(null);
  const [trouble, setTrouble] = useState(false);
  const [moved, setMoved] = useState(false);
  // Setup is never a Drive page, so the shell's mini radio bar shows exactly while the radio is live (spec 3.5).
  const radioBar = useRadio((s) => s.phase === "live");
  const total = plan.sections.reduce((a, s) => a + s.items.length, 0);
  const done = plan.sections.reduce((a, s) => a + sectionCounts(s, ticks).done, 0);

  const go = (p: WalkPos | null) => {
    if (!p) return;
    setMoved(true);
    const s = plan.sections[p.s];
    if (s) router.replace(rigPath("walk", query, { section: s.id, n: p.i + 1 }));
  };

  // The route always names the step on screen (so Previous / Next and a reload land on it).
  const named = section === sec.id && n === pos.i + 1;
  useEffect(() => {
    if (!named && sec.items.length) router.replace(rigPath("walk", query, { section: sec.id, n: pos.i + 1 }));
  }, [named, sec.id, sec.items.length, pos.i, query]);

  if (!item) return null;
  const prev = neighbour(plan, pos, -1);
  const next = neighbour(plan, pos, 1);
  const run = guideRun(sec, item);
  // Buttons are Setup › Controls' job (feat/controls): link to it where the walkthrough finds the controls and at the
  // end of the in-game section.
  const buttonsLink = (item.kind === "guide" && item.guide.id === "controls") || (sec.id === "ingame" && pos.i === sec.items.length - 1);
  const afterRun = (): WalkPos | null => {
    const lastOfRun = sec.items.indexOf(run.at(-1)!);
    return neighbour(plan, { s: pos.s, i: lastOfRun }, 1);
  };

  return (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      <Card className="gap-3 px-4 py-3 md:px-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="m-0 min-w-0 text-[15px]">
            <span className="font-semibold">Rig setup{driverName ? ` for ${driverName}` : ""}</span>
            <span className="text-muted">
              {" "}
              · {GAME_LABEL[game]} · {hardwareLine(hw)}
            </span>
          </p>
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted" aria-live="polite">
              {done} of {total} done
            </span>
            {plan.guided ? (
              <Button variant="ghost" className="min-h-11" onPress={() => setTrouble(true)}>
                Something not right?
              </Button>
            ) : null}
            <Button variant="secondary" className="min-h-11" onPress={() => router.navigate(rigPath("settings", query))}>
              Change rig
            </Button>
          </span>
        </div>
        <div className="-mx-1 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
          <Stepper
            size="lg"
            currentStep={pos.s}
            onStepChange={(s) => go(locate(plan, plan.sections[s]?.id ?? null, null, ticks))}
            aria-label="Walkthrough sections"
            className="min-w-[620px] [--stepper-complete-color:var(--success)] [--stepper-complete-fg:var(--success-foreground)]"
          >
            {plan.sections.map((s, k) => {
              const isDone = sectionDone(s, ticks);
              const c = sectionCounts(s, ticks);
              const before = k < pos.s;
              return (
                <Stepper.Step key={s.id} className="min-h-14">
                  <Stepper.Indicator
                    className={
                      isDone
                        ? "!border-success !bg-success !text-success-foreground"
                        : before
                          ? "!border-[var(--pw-line-strong)] !bg-transparent !text-muted !shadow-none"
                          : ""
                    }
                  >
                    {isDone ? <TickIcon className="size-4 !text-current" /> : <span>{k + 1}</span>}
                  </Stepper.Indicator>
                  <Stepper.Content>
                    <Stepper.Title className="text-sm font-semibold">{s.title}</Stepper.Title>
                    <Stepper.Description className="text-xs">
                      {c.done} of {c.total}
                    </Stepper.Description>
                  </Stepper.Content>
                  <Stepper.Separator progress={isDone ? 1 : 0} />
                </Stepper.Step>
              );
            })}
          </Stepper>
        </div>
      </Card>

      {rec.warnings.map((w) => (
        <Alert key={w} status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{w}</Alert.Description>
          </Alert.Content>
        </Alert>
      ))}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px] [&>*]:min-w-0">
        <StepCard
          key={item.id}
          item={item}
          position={`${sec.title} · ${pos.i + 1} of ${sec.items.length}`}
          ticks={ticks}
          doc={doc}
          mistakes={mistakes}
          isFirst={prev === null}
          isLast={next === null}
          onPrev={() => go(prev)}
          onDone={() => {
            setTicks(tick(ticks, [item]));
            go(next);
          }}
          onUndo={() => setTicks(untick(ticks, item))}
          onSkipGuide={
            item.kind === "guide" && run.length > 1
              ? () => {
                  setTicks(tick(ticks, run));
                  go(afterRun());
                }
              : null
          }
          onDetail={setDetail}
          focusOnMount={moved}
          radioBar={radioBar}
          onOpenCheck={() => {
            setTicks(tick(ticks, [item]));
            router.navigate(rigPath("check", query));
          }}
        />
        {buttonsLink ? (
          <Card className="flex flex-row flex-wrap items-center justify-between gap-2 px-5 py-3 lg:col-start-1" data-testid="rig-buttons-link">
            <span className="text-[15px]">Which button does what in the game?</span>
            <Link href={href(`/setup/controls?game=${game}`)} className="inline-flex min-h-11 items-center font-medium">
              Buttons: Setup › Controls
            </Link>
          </Card>
        ) : null}
        <Card className="gap-2 p-2 lg:sticky lg:top-20 lg:col-start-2 lg:row-start-1">
          <p className="m-0 px-3 pt-2 text-sm font-semibold text-muted">
            {sec.title} · {sectionCounts(sec, ticks).done} of {sec.items.length} done
          </p>
          <SectionList
            section={sec}
            current={pos.i}
            ticks={ticks}
            onJump={(i) => go({ s: pos.s, i })}
            className="max-h-[min(480px,calc(100dvh-360px))] min-h-[240px] overflow-y-auto"
          />
        </Card>
      </div>

      <DetailSheet target={detail} rec={rec} doc={doc} onClose={() => setDetail(null)} />
      {plan.guided ? <TroubleSheet isOpen={trouble} onClose={() => setTrouble(false)} doc={doc} game={game} hw={hw} /> : null}
    </div>
  );
}
