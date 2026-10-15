// Review › Coaching › "How corners work" (technique knowledge spec section 4): the technique graph
// (GET /api/technique/knowledge; with the plan session's id, its `?session=` variant when the server has one) as a
// section of the Coaching page, not a page of its own:
//   - the six phases of a corner in driving order (cards), each with its techniques tagged "Fits you" / "For other
//     drivers" / "Not known yet" for the viewed driver and a one-line reason; alternatives (trail braking against
//     straight-line braking), how each works and the signals that measure it by density;
//   - "What Pitwall checks": the faults coached on their laps today apart from the ones not coached yet (experimental,
//     planned, background), with the causes Pitwall can tell apart and its own measurements by density;
//   - "Where this comes from": Ed (Pitwall tester) credited first, then published coaching and Pitwall's own sources.
// The pure rules are lib/knowledge/view.ts. Density by the viewed driver's level (lib/review/density.ts): beginners
// read the narrative (what each phase is, what fits them, in 18 px), advanced drivers get the detail inline; "Show
// the detail" opens it for anyone, for this section only. Published and brief knowledge is never presented as
// validated by Pitwall: the note above the phases and the tier chips say what each piece is. A server without the
// graph (FastAPI's own 404) leaves the section out; a graph that did not load says so.

import { Button, Card, Chip, Disclosure, Link, Skeleton } from "@heroui/react";
import { ListView } from "@heroui-pro/react";
import { useMemo, useState, type ReactNode } from "react";
import { useApi } from "../../../hooks/useApi";
import type { SkillLevel } from "../../../lib/drivers";
import { isMissingKnowledge, KNOWLEDGE_MAX_AGE_MS, knowledgeApi, knowledgeKeys, type KnowledgeTier } from "../../../lib/endpoints/knowledge";
import {
  contextNote,
  cornersView,
  creditLine,
  fitLabel,
  knowledgeDensity,
  TIER_LABEL,
  type FaultItem,
  type Fit,
  type KnowledgeDensity,
  type PhaseView,
  type SourceItem,
  type TechniqueItem,
} from "../../../lib/knowledge/view";

const FIT_COLOUR: Readonly<Record<Fit, "success" | "default" | "warning">> = {
  fits: "success",
  other: "default",
  unknown: "warning",
};

function FitChip({ fit, name }: { fit: Fit; name: string | null }) {
  return (
    <Chip size="sm" variant="soft" color={FIT_COLOUR[fit]} className="shrink-0">
      <Chip.Label>{fitLabel(fit, name)}</Chip.Label>
    </Chip>
  );
}

function TierChip({ tier, meaning }: { tier: KnowledgeTier; meaning: string | undefined }) {
  return (
    <span title={meaning} className="inline-flex">
      <Chip size="sm" variant="soft" className="shrink-0">
        <Chip.Label>
          {TIER_LABEL[tier] ?? tier}
          {meaning && <span className="sr-only">: {meaning}</span>}
        </Chip.Label>
      </Chip>
    </span>
  );
}

function Fold({ title, defaultExpanded = false, children }: { title: string; defaultExpanded?: boolean; children: ReactNode }) {
  return (
    <Disclosure defaultExpanded={defaultExpanded} className="border-t border-separator">
      <Disclosure.Heading className="m-0">
        <Disclosure.Trigger className="flex min-h-11 w-full items-center justify-between gap-2 text-left text-sm font-semibold">
          {title}
          <Disclosure.Indicator className="size-4" />
        </Disclosure.Trigger>
      </Disclosure.Heading>
      <Disclosure.Content>
        <Disclosure.Body style={{ padding: 0 }} className="grid gap-3 pb-2">
          {children}
        </Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}

interface Shared {
  kd: KnowledgeDensity;
  /** Another driver's plan: their name in "Fits Alex"; null for your own. */
  name: string | null;
  tiers: Partial<Record<KnowledgeTier, string>>;
}

function TechniqueRow({ t, s }: { t: TechniqueItem; s: Shared }) {
  const { kd } = s;
  return (
    <li className="grid gap-1">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold leading-snug" style={{ fontSize: kd.textPx }}>
          {t.name}
        </span>
        <FitChip fit={t.fit.fit} name={s.name} />
        {kd.tiers && <TierChip tier={t.tier} meaning={s.tiers[t.tier]} />}
      </div>
      <p className="m-0 leading-snug" style={{ fontSize: kd.textPx }}>
        {t.summary}
      </p>
      <p className="m-0 text-sm text-muted">{t.fit.reason}</p>
      {kd.alternatives && t.alternatives.length > 0 && (
        <p className="m-0 text-sm text-muted">
          Instead: {t.alternatives.map((a) => `${a.name} (${fitLabel(a.fit, s.name).toLowerCase()})`).join(" · ")}
        </p>
      )}
      {kd.detail === "open" && <p className="m-0 text-sm leading-relaxed">{t.detail}</p>}
      {kd.detail === "fold" && (
        <Fold title="How it works">
          <p className="m-0 text-sm leading-relaxed">{t.detail}</p>
        </Fold>
      )}
      {kd.signals && t.signals.length > 0 && (
        <p className="m-0 text-xs text-muted">
          Measured by: {t.signals.map((x) => (x.measured ? x.name : `${x.name} (not measured yet)`)).join(" · ")}
        </p>
      )}
    </li>
  );
}

function TechniqueList({ items, s }: { items: readonly TechniqueItem[]; s: Shared }) {
  return (
    <ul className="m-0 grid list-none gap-4 p-0">
      {items.map((t) => (
        <TechniqueRow key={t.id} t={t} s={s} />
      ))}
    </ul>
  );
}

function PhaseCard({ p, total, s }: { p: PhaseView; total: number; s: Shared }) {
  return (
    <Card className="gap-3 p-5">
      <Card.Header className="gap-1">
        <span className="text-xs font-semibold text-muted">
          {p.order} of {total}
        </span>
        <Card.Title className="text-base font-semibold">{p.name}</Card.Title>
        <Card.Description className="text-sm">{p.summary}</Card.Description>
      </Card.Header>
      {p.shown.length > 0 ? (
        <TechniqueList items={p.shown} s={s} />
      ) : (
        <p className="m-0 text-sm text-muted">Nothing here fits {s.name ?? "you"} specially: see the techniques for other drivers.</p>
      )}
      {p.others.length > 0 &&
        (s.kd.othersOpen ? (
          <div className="grid gap-3 border-t border-separator pt-3">
            <span className="text-sm font-semibold text-muted">For other drivers</span>
            <TechniqueList items={p.others} s={s} />
          </div>
        ) : (
          <Fold title={`For other drivers (${p.others.length})`}>
            <TechniqueList items={p.others} s={s} />
          </Fold>
        ))}
    </Card>
  );
}

function FaultList({ items, label, s }: { items: readonly FaultItem[]; label: string; s: Shared }) {
  const { kd } = s;
  return (
    <ListView aria-label={label} items={[...items]} variant="secondary">
      {(f) => (
        <ListView.Item id={f.id} textValue={`${f.name} ${f.summary}`}>
          <ListView.ItemContent className="items-start">
            <span className="grid min-w-0 gap-1">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                <span>
                  {f.phase}
                  {f.positive ? " · praise" : ""}
                </span>
                {f.status !== "live" && (
                  <Chip size="sm" variant="soft">
                    <Chip.Label>{f.statusLabel}</Chip.Label>
                  </Chip>
                )}
                {!(f.fit.universal && f.fit.fit === "fits") && <FitChip fit={f.fit.fit} name={s.name} />}
                {kd.tiers && <TierChip tier={f.tier} meaning={s.tiers[f.tier]} />}
              </span>
              <ListView.Title className="whitespace-normal text-[15px] leading-snug">{f.name}</ListView.Title>
              <ListView.Description className="whitespace-normal">{f.summary}</ListView.Description>
              {!(f.fit.universal && f.fit.fit === "fits") && (
                <ListView.Description className="whitespace-normal">{f.fit.reason}</ListView.Description>
              )}
              {kd.causes && f.causes.length > 0 && (
                <ListView.Description className="whitespace-normal">
                  Causes Pitwall can tell apart: {f.causes.map((c) => c.name).join(" · ")}
                </ListView.Description>
              )}
              {kd.measured &&
                f.measured.map((m) => (
                  <ListView.Description key={m} className="whitespace-normal text-xs">
                    {m}
                  </ListView.Description>
                ))}
            </span>
          </ListView.ItemContent>
        </ListView.Item>
      )}
    </ListView>
  );
}

function FaultsCard({ coached, notCoached, s }: { coached: readonly FaultItem[]; notCoached: readonly FaultItem[]; s: Shared }) {
  const mode = s.kd.notCoached;
  return (
    <Card className="gap-3 p-5">
      <Card.Header className="gap-1">
        <Card.Title className="text-base font-semibold">What Pitwall checks</Card.Title>
        <Card.Description className="text-sm">
          Coached on {s.name ? `${s.name}'s` : "your"} laps today, each against {s.name ? "their" : "your"} own reference lap.
        </Card.Description>
      </Card.Header>
      <FaultList items={coached} label="Coached now" s={s} />
      {mode !== "hidden" && notCoached.length > 0 && (
        <Fold title={`Not coached yet (${notCoached.length})`} defaultExpanded={mode === "open"}>
          <p className="m-0 text-sm text-muted">
            Faults from Ed's checklist and patches and from published coaching that Pitwall measures or plans to, but does
            not coach: some fire far too often on real laps to be trusted yet.
          </p>
          <FaultList items={notCoached} label="Not coached yet" s={s} />
        </Fold>
      )}
    </Card>
  );
}

function SourceList({ items, label, s }: { items: readonly SourceItem[]; label: string; s: Shared }) {
  return (
    <ListView aria-label={label} items={[...items]} variant="secondary">
      {(x) => (
        <ListView.Item id={x.id} textValue={`${x.title} ${x.author}`}>
          <ListView.ItemContent className="items-start">
            <span className="grid min-w-0 gap-1">
              <ListView.Title className="whitespace-normal break-words text-[15px] leading-snug">{x.title}</ListView.Title>
              <ListView.Description className="whitespace-normal">
                {[x.author, x.date, x.tierLabel].filter(Boolean).join(" · ")}
              </ListView.Description>
              {s.kd.level !== "beginner" && <ListView.Description className="whitespace-normal">{x.note}</ListView.Description>}
            </span>
          </ListView.ItemContent>
          {x.url && (
            <ListView.ItemAction>
              <Link
                href={x.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`Open ${x.title}`}
                className="inline-flex min-h-11 items-center px-2 text-sm"
              >
                Open
              </Link>
            </ListView.ItemAction>
          )}
        </ListView.Item>
      )}
    </ListView>
  );
}

function SourcesCard({ view, s }: { view: ReturnType<typeof cornersView>; s: Shared }) {
  const g = view.sources;
  const credit = creditLine(g);
  const all = g.ed.length + g.published.length + g.pitwall.length;
  const lists = (
    <>
      {g.ed.length > 0 && <SourceList items={g.ed} label="Ed's material" s={s} />}
      {g.published.length > 0 && (
        <>
          <span className="text-sm font-semibold text-muted">Published coaching</span>
          <SourceList items={g.published} label="Published coaching" s={s} />
        </>
      )}
      {g.pitwall.length > 0 && (
        <>
          <span className="text-sm font-semibold text-muted">Pitwall's own rules and measurements</span>
          <SourceList items={g.pitwall} label="Pitwall's own rules and measurements" s={s} />
        </>
      )}
    </>
  );
  return (
    <Card className="gap-3 p-5">
      <Card.Header className="gap-1">
        <Card.Title className="text-base font-semibold">Where this comes from</Card.Title>
      </Card.Header>
      {credit && <p className="m-0 text-[15px] leading-snug">{credit}</p>}
      <p className="m-0 text-sm text-muted">
        The rest is published coaching ({g.published.length} sources) and Pitwall's own rules and measurements on
        recorded laps. Published coaching and Ed's brief are not validated by Pitwall.
      </p>
      {s.kd.sourcesOpen ? <div className="grid gap-3">{lists}</div> : <Fold title={`All ${all} sources`}>{lists}</Fold>}
    </Card>
  );
}

export interface HowCornersWorkProps {
  /** The plan session (its Context when the server has the session variant), or null. */
  sessionId: string | null;
  /** The viewed driver's own level from their profile (null when unknown): the trait the page knows for sure. */
  skill: SkillLevel | null;
  /** The density level the page shows (the profile's, or intermediate for an unknown driver). */
  level: SkillLevel;
  /** Another driver's plan: their name; null for your own. */
  name: string | null;
}

export function HowCornersWork({ sessionId, skill, level, name }: HowCornersWorkProps) {
  const q = useApi(knowledgeKeys.graph(sessionId), () => knowledgeApi.graph(sessionId), { maxAgeMs: KNOWLEDGE_MAX_AGE_MS });
  const [detail, setDetail] = useState(false);
  const kd = knowledgeDensity(detail ? "advanced" : level);
  const view = useMemo(() => (q.data && q.data.valid !== false ? cornersView(q.data, skill) : null), [q.data, skill]);
  const s: Shared = { kd, name, tiers: view?.tiers ?? {} };

  if (q.error && !q.data && isMissingKnowledge(q.error)) return null; // a server before the technique graph

  const heading = (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
      <h2 className="m-0 text-lg font-semibold">How corners work</h2>
      {view && level !== "advanced" && (
        <Button variant="ghost" size="sm" className="min-h-11" onPress={() => setDetail((v) => !v)}>
          {detail ? "Back to the usual view" : "Show the detail"}
        </Button>
      )}
    </div>
  );

  let body: ReactNode;
  if (!view) {
    body =
      q.error || (q.data && q.data.valid === false) ? (
        <p role="alert" className="m-0 text-sm text-muted">
          How corners work could not be loaded: {q.error ? q.error.message.replace(/^\d{3}: /, "") : "the technique graph did not load"}.
        </p>
      ) : (
        <div aria-busy="true" aria-label="Loading how corners work" className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-56 rounded-3xl" />
          <Skeleton className="hidden h-56 rounded-3xl md:block" />
          <Skeleton className="hidden h-56 rounded-3xl xl:block" />
        </div>
      );
  } else {
    const total = view.phases.length;
    body = (
      <>
        <div className="grid gap-2">
          <p className="m-0 leading-snug" style={{ fontSize: kd.textPx }}>
            A corner in {total} phases: what good technique looks like in each, and which of it fits{" "}
            {name ?? "you"}. Most of it is published coaching and Ed's brief, not something Pitwall has checked on{" "}
            {name ? "their" : "your"} laps; what it does check is under What Pitwall checks.
          </p>
          {view.chips.length > 0 && (
            <div role="group" className="flex flex-wrap items-center gap-1.5" aria-label="What Pitwall knows about the driver and car">
              {view.chips.map((c) => (
                <Chip key={c} size="sm" variant="soft">
                  <Chip.Label>{c}</Chip.Label>
                </Chip>
              ))}
            </div>
          )}
          <p className="m-0 text-sm text-muted">{contextNote(view.context, name)}</p>
        </div>
        <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          {view.phases.map((p) => (
            <PhaseCard key={p.id} p={p} total={total} s={s} />
          ))}
        </div>
        <div className="grid items-start gap-4 lg:grid-cols-2">
          <FaultsCard coached={view.faults.coached} notCoached={view.faults.notCoached} s={s} />
          <SourcesCard view={view} s={s} />
        </div>
      </>
    );
  }

  return (
    <section aria-label="How corners work" className="grid gap-3 pt-2">
      {heading}
      {body}
    </section>
  );
}
