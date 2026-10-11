// Setup › Car setup, one session: "How the car handled" (feat/technique spec §4.3, §4.4, §9). Before the session's
// experiments. From GET /api/technique/sessions/{sid}/balance:
//   - one Pro ItemCard per CAR symptom (it recurs and shows even on the session's best lap): its corners, "3 of 3 laps,
//     including your best", the backend's sentence, and its one-parameter suggestions ("Front Anti-Roll Bar 9 → 7")
//     with why and the catalogue's effect behind a Disclosure. "Try this" opens the existing Start an experiment modal
//     prefilled (parameter, new value, hypothesis), so the experiment goes through carsetup's `propose` unchanged; a
//     blocked suggestion shows its reason instead;
//   - DRIVING symptoms (not on the best lap) muted, with "See it on the lap" (Compare at the corner) and never a
//     setup suggestion;
//   - the catalogue caveat verbatim. Non-F1 sessions: suggestions are for F1 25 only. No slip data: said so.
// Balance thresholds are heuristics and the card says so. A server without feat/technique (404) hides the card.

import { Button, Card, Chip, Disclosure, Skeleton } from "@heroui/react";
import { ItemCard } from "@heroui-pro/react";
import { useState } from "react";
import { CornerTag, EvidenceChips } from "../../../components/ui";
import { cache } from "../../../lib/cache";
import type { CarFormat, CarSetupCatalog, SessionSetupResponse, SetupExperiment } from "../../../lib/endpoints/carsetup";
import { reviewApi, reviewKeys } from "../../../lib/endpoints/review";
import {
  techniqueErrorKind,
  techniqueErrorText,
  type BalanceSymptom,
  type SetupSuggestion,
  type TechniqueBalance,
} from "../../../lib/endpoints/technique";
import { apexGameM } from "../../../lib/review/compare";
import { comparePath } from "../../../lib/review/links";
import { router } from "../../../lib/router";
import { symptomViews, unavailableReasons, type SymptomView } from "../../../lib/technique/view";
import { SPEED_CLASS_WORDS, suggestionChange, symptomLapsText, symptomTitle } from "../../../lib/technique/words";
import { useTechniqueBalance } from "../../review/session/technique/data";
import { Caveat } from "./RecommendationSummary";

export const NOT_F1_TEXT = "Setup suggestions are for F1 25 only.";
export const NO_SLIP_TEXT =
  "No tyre slip data in this session (recorded before Pitwall stored it, or the game does not send it).";

export interface TryInitial {
  key: string;
  to: number;
  hypothesis?: string;
}

export interface HandlingBalanceCardProps {
  sid: string;
  /** The car format the page knows (chosen or reported); fills in suggestions the server could not size. */
  carFormat?: CarFormat | null;
  session: Pick<SessionSetupResponse["session"], "game" | "synthetic" | "driver">;
  catalog: Pick<CarSetupCatalog, "parameters">;
  /** This session's experiments (refreshes after every proposal; a suggestion already proposed is marked). */
  experiments: readonly SetupExperiment[];
  /** Open the existing Start an experiment modal, prefilled. */
  onTry: (initial: TryInitial) => void;
}

/** The Start an experiment prefill for a suggestion (null when it cannot be tried: blocked or no target value). */
export function tryInitial(x: Pick<SetupSuggestion, "parameter" | "to_value" | "hypothesis"> & { blockedNow?: string | null }): TryInitial | null {
  if (x.blockedNow || x.to_value === null || !Number.isFinite(x.to_value)) return null;
  return { key: x.parameter, to: x.to_value, hypothesis: x.hypothesis };
}

/** "Entry understeer at T3" -> "entry understeer at T3" (corner labels keep their case). */
export function lowerFirst(s: string): string {
  return s ? s[0]!.toLowerCase() + s.slice(1) : s;
}

/** Compare at the symptom's first corner: the apex from the session's analysis (loaded if needed). */
async function seeOnLap(sid: string, corner: string | undefined): Promise<void> {
  let at: number | null = null;
  if (corner) {
    try {
      const a = await cache.load(reviewKeys.analysis(sid), () => reviewApi.analysis(sid), { maxAgeMs: 60_000 });
      at = apexGameM(a.track_model, corner, null);
    } catch {
      at = null;
    }
  }
  router.navigate(comparePath(sid, { at }));
}

function SymptomCard({
  view,
  params,
  titles,
  simple,
  onTry,
}: {
  view: SymptomView;
  params: Map<string, CarSetupCatalog["parameters"][number]>;
  /** Symptom id -> its title ("Entry understeer at T3"), for changes listed under an earlier symptom. */
  titles: Map<string, string>;
  simple: boolean;
  onTry: (i: TryInitial) => void;
}) {
  const s = view.symptom;
  return (
    <Card variant="secondary" className="gap-3 p-4" data-symptom={s.id}>
      <ItemCard variant="transparent" className="items-start p-0">
        <ItemCard.Content>
          <ItemCard.Title className="text-base font-semibold whitespace-normal">
            {symptomTitle(s)} <span className="text-sm font-normal text-muted">· {SPEED_CLASS_WORDS[s.speed_class]}</span>
          </ItemCard.Title>
          <ItemCard.Description className="text-sm whitespace-normal text-muted">{symptomLapsText(s)}</ItemCard.Description>
        </ItemCard.Content>
        <ItemCard.Action className="flex flex-wrap items-center gap-1.5">
          {s.corner_labels.map((l) => (
            <CornerTag key={l} label={l} size="sm" />
          ))}
        </ItemCard.Action>
      </ItemCard>
      <p className="m-0 text-[15px] leading-relaxed">{simple && s.text_simple ? s.text_simple : s.text}</p>
      {view.suggestions.length ? (
        <div className="grid gap-2">
          <span className="text-sm font-semibold text-muted">Setup to try (one change, then compare a session)</span>
          <ul className="m-0 grid list-none gap-1.5 p-0">
            {view.suggestions.map((x) => {
              const initial = tryInitial(x);
              const change = suggestionChange(x, params.get(x.parameter));
              if (x.duplicateOf) {
                const first = titles.get(x.duplicateOf);
                return (
                  <li key={x.parameter} className="px-3 py-1 text-sm text-muted" data-suggestion={x.parameter} data-duplicate="">
                    <span className="pw-num text-base text-foreground">{change}</span> · also listed above
                    {first ? ` for ${lowerFirst(first)}` : ""}
                  </li>
                );
              }
              return (
                <li key={x.parameter} className="rounded-2xl bg-surface px-3 py-1.5" data-suggestion={x.parameter}>
                  <Disclosure>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="pw-num text-xl">{change}</span>
                      {x.forFormat && (
                        <span className="text-xs text-muted">for the {x.forFormat === "f1_2026" ? "2026" : "2025"} car you chose</span>
                      )}
                      <Disclosure.Heading className="m-0">
                        <Disclosure.Trigger className="flex min-h-11 items-center gap-1 text-sm text-muted">
                          Why
                          <Disclosure.Indicator className="size-4" />
                        </Disclosure.Trigger>
                      </Disclosure.Heading>
                      <span className="ml-auto flex items-center">
                        {initial ? (
                          <Button variant="secondary" className="min-h-11" onPress={() => onTry(initial)}>
                            Try this
                          </Button>
                        ) : (
                          <Chip size="sm" variant="soft" color="default" className="h-auto min-h-7 py-1" data-blocked="">
                            <Chip.Label className="whitespace-normal">{x.blockedNow ?? "Cannot be tried from this session"}</Chip.Label>
                          </Chip>
                        )}
                      </span>
                    </div>
                    <Disclosure.Content>
                      <Disclosure.Body style={{ padding: 0 }} className="grid gap-1 pb-2 text-sm">
                        <p className="m-0">{x.why}</p>
                        <p className="m-0 text-muted">
                          <span className="font-medium">What {x.direction === "lower" ? "lower" : "higher"} does: </span>
                          {x.effect}
                        </p>
                      </Disclosure.Body>
                    </Disclosure.Content>
                  </Disclosure>
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <p className="m-0 text-sm text-muted">No single change to suggest for this one.</p>
      )}
    </Card>
  );
}

function DrivingList({ items, sid, simple }: { items: readonly BalanceSymptom[]; sid: string; simple: boolean }) {
  const [busy, setBusy] = useState<string | null>(null);
  if (!items.length) return null;
  return (
    <div className="grid gap-2">
      <span className="text-sm font-semibold text-muted">Not on your best lap: more about how the corner was driven</span>
      <ul className="m-0 grid list-none gap-2 p-0">
        {items.map((s) => (
          <li key={s.id} className="grid gap-1 rounded-2xl border border-separator px-3 py-2 opacity-80" data-symptom={s.id}>
            <span className="flex flex-wrap items-center gap-2 text-sm text-muted">
              {symptomTitle(s)} · {symptomLapsText(s)}
              {s.corner_labels.map((l) => (
                <CornerTag key={l} label={l} size="sm" />
              ))}
            </span>
            <span className="text-sm text-muted">{simple && s.text_simple ? s.text_simple : s.text}</span>
            <div>
              <Button
                variant="ghost"
                size="sm"
                className="min-h-11"
                isPending={busy === s.id}
                onPress={() => {
                  setBusy(s.id);
                  void seeOnLap(sid, s.corners[0]).finally(() => setBusy(null));
                }}
              >
                See it on the lap
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Body({
  data,
  sid,
  carFormat,
  session,
  catalog,
  experiments,
  onTry,
}: HandlingBalanceCardProps & { data: TechniqueBalance }) {
  const simple = session.driver?.skill_level === "beginner";
  const params = new Map(catalog.parameters.map((p) => [p.key, p]));
  const noSlip = !data.available.slip.ok || !data.available.balance.ok;
  const notF1 = !data.setup && !session.game?.startsWith("f1");
  if (noSlip && !data.symptoms.length) {
    const reason = unavailableReasons(data.available, ["balance", "slip"])[0];
    return (
      <div className="grid gap-2">
        <p className="m-0 text-[15px]">{notF1 ? (reason ?? NO_SLIP_TEXT) : NO_SLIP_TEXT}</p>
        {notF1 && <p className="m-0 text-sm text-muted">{NOT_F1_TEXT}</p>}
      </div>
    );
  }
  const titles = new Map(data.symptoms.map((x) => [x.id, `${symptomTitle(x)} at ${x.corner_labels.join(", ")}`]));
  const { car, driving } = symptomViews(data.symptoms, data.setup, {
    experiments,
    sid,
    synthetic: session.synthetic,
    carFormat,
    params,
  });
  return (
    <div className="grid gap-3">
      {session.synthetic && (
        <p className="m-0 text-sm text-muted">
          Generated data: these symptoms were put there by the simulator, so they say nothing about your car. Suggestions are
          shown but not offered as experiments.
        </p>
      )}
      {car.length ? (
        car.map((v) => <SymptomCard key={v.symptom.id} view={v} params={params} titles={titles} simple={simple} onTry={onTry} />)
      ) : (
        <p className="m-0 text-[15px]">
          No handling problem showed on most laps and on your best lap, so there is no setup change to suggest from this
          session.
        </p>
      )}
      <DrivingList items={driving} sid={sid} simple={simple} />
      {notF1 && <p className="m-0 text-sm text-muted">{NOT_F1_TEXT}</p>}
      {!notF1 && !data.setup && data.available.setup.reason && <p className="m-0 text-sm text-muted">{data.available.setup.reason}</p>}
      {data.setup?.note && <p className="m-0 text-sm text-muted">{data.setup.note}</p>}
      {data.setup?.caveat && <Caveat text={data.setup.caveat} />}
    </div>
  );
}

export function HandlingBalanceCard(props: HandlingBalanceCardProps) {
  const res = useTechniqueBalance(props.sid, props.carFormat);
  if (!res.data && res.error && techniqueErrorKind(res.error) === "missing") return null;
  return (
    <Card className="gap-4 p-5" aria-label="How the car handled">
      <Card.Header className="flex-row flex-wrap items-start justify-between gap-3 p-0">
        <div className="grid gap-0.5">
          <Card.Title className="text-base font-semibold">How the car handled</Card.Title>
          <Card.Description className="text-sm text-muted">
            Measured from tyre slip at the limit; the thresholds are Pitwall's heuristics.
          </Card.Description>
        </div>
        <EvidenceChips synthetic={props.session.synthetic} size="md" />
      </Card.Header>
      {res.data ? (
        <Body {...props} data={res.data} />
      ) : res.error ? (
        techniqueErrorKind(res.error) === "no_model" ? (
          <p className="m-0 text-sm text-muted">{techniqueErrorText(res.error)}</p>
        ) : (
          <p role="alert" className="m-0 text-sm text-danger">
            {techniqueErrorText(res.error)}
          </p>
        )
      ) : (
        <div aria-busy="true" aria-label="Loading how the car handled" className="grid gap-3">
          <Skeleton className="h-24 rounded-2xl" />
        </div>
      )}
    </Card>
  );
}
