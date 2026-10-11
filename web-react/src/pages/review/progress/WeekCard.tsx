// The week on Review › Progress (lane motivation, spec 9 WeekCard): one Monday-to-Sunday week of the viewed driver's
// real driving. ‹ › move a week (44 px; › is off on the current week), the headline and totals, the sessions (7, then
// "+N more"), the best improvements (3), how each goal moved, the badges earned. Printable page opens the server's
// own HTML page (no JavaScript, no external requests; the cookie or Tailscale identity lets it in) and Copy as text
// copies the same week as markdown. No external services.

import { ChevronLeft, ChevronRight, Copy, Medal, Printer } from "@gravity-ui/icons";
import { Button, Card, Chip, ProgressBar, Skeleton } from "@heroui/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { copyText, EvidenceChips, TimingValue } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import { motivationApi, motivationKeys, motivationPaths } from "../../../lib/endpoints/motivation";
import { isMissingRoute } from "../../../lib/endpoints/review";
import { fractionChange, WEEK_BADGES_SHOWN, weekView } from "../../../lib/motivation/digest";
import { shiftWeek } from "../../../lib/motivation/format";
import { router } from "../../../lib/router";
import { sessionPath } from "../../../lib/review/links";

function CopyMarkdown({ text }: { text: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return (
    <>
      <Button
        variant="ghost"
        className="min-h-11"
        isDisabled={!text}
        onPress={async () => {
          setState((await copyText(text)) ? "copied" : "failed");
          if (timer.current) clearTimeout(timer.current);
          timer.current = setTimeout(() => setState("idle"), 2000);
        }}
      >
        <Copy aria-hidden="true" />
        {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy as text"}
      </Button>
      <span className="sr-only" role="status" aria-live="polite">
        {state === "copied" ? "The week copied as text" : state === "failed" ? "Copy is not available here" : ""}
      </span>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <h3 className="m-0 text-sm font-semibold text-muted">{title}</h3>
      {children}
    </div>
  );
}

export function WeekCard({ driverId, simple }: { driverId: number; simple: boolean }) {
  // null = this week (the server's default); else the Monday of the week shown.
  const [week, setWeek] = useState<string | null>(null);
  useEffect(() => setWeek(null), [driverId]);
  const d = useApi(motivationKeys.digest(driverId, week), () => motivationApi.digest(driverId, week), { maxAgeMs: 60_000 });
  const v = useMemo(() => (d.data ? weekView(d.data, simple) : null), [d.data, simple]);
  const missing = d.error && isMissingRoute(d.error);

  const go = (n: number) => {
    if (!v) return;
    setWeek(shiftWeek(v.weekStart, n));
  };

  return (
    <Card className="gap-3 p-5" data-motivation="week">
      <Card.Header className="flex-row flex-wrap items-center justify-between gap-2">
        <div className="grid gap-0.5">
          <Card.Title className="text-base font-semibold">{v?.isCurrent ? "This week" : "Week"}</Card.Title>
          <span className="text-sm text-muted">{v ? v.label : missing ? "-" : "…"}</span>
        </div>
        {!missing && (
          <div className="flex items-center gap-1">
            <Button isIconOnly variant="ghost" className="size-11" aria-label="Week before" isDisabled={!v} onPress={() => go(-1)}>
              <ChevronLeft aria-hidden="true" />
            </Button>
            <Button
              isIconOnly
              variant="ghost"
              className="size-11"
              aria-label="Week after"
              isDisabled={!v || v.isCurrent}
              onPress={() => go(1)}
            >
              <ChevronRight aria-hidden="true" />
            </Button>
          </div>
        )}
      </Card.Header>

      {missing ? (
        <p className="m-0 text-sm text-muted">The weekly summary needs a newer Pitwall server.</p>
      ) : !v && d.error ? (
        <p role="alert" className="m-0 text-sm text-bad">
          The week could not be loaded: {d.error.message}
        </p>
      ) : !v ? (
        <div aria-busy="true" aria-label="Loading the week" className="grid gap-2">
          <Skeleton className="h-6 w-3/4 rounded-lg" />
          <Skeleton className="h-4 w-1/2 rounded-lg" />
          <Skeleton className="h-24 rounded-2xl" />
        </div>
      ) : (
        <>
          <div className="grid gap-1">
            <p className="m-0 text-[17px] font-semibold leading-snug">{v.headline}</p>
            {v.totals && <p className="m-0 text-sm text-muted">{v.totals}</p>}
            {v.previous && <p className="m-0 text-[13px] text-muted">{v.previous}</p>}
          </div>

          {v.sessions.length > 0 && (
            <Section title="Sessions">
              <ul className="m-0 grid list-none gap-0 p-0">
                {v.sessions.map((s) => (
                  <li key={s.id}>
                    <button
                      type="button"
                      className="grid min-h-11 w-full cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 rounded-xl px-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)]"
                      onClick={() => router.navigate(sessionPath(s.id))}
                      aria-label={`${s.day}, ${s.title}. Open the session`}
                    >
                      <span className="grid min-w-0">
                        <span className="flex min-w-0 items-center gap-2 truncate text-[15px] font-medium">
                          <span className="truncate">{s.title}</span>
                          {s.synthetic && <EvidenceChips synthetic size="sm" />}
                        </span>
                        <span className="truncate text-[13px] text-muted">
                          {[s.day, s.car, s.laps].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                      <span className="flex items-center gap-1.5">
                        {s.pb && (
                          <Chip size="sm" variant="soft" color="success">
                            <Chip.Label>New best</Chip.Label>
                          </Chip>
                        )}
                        <TimingValue ms={s.bestMs} kind="lap" status="neutral" size="table" />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              {v.moreSessions > 0 && <p className="m-0 px-1 text-[13px] text-muted">+{v.moreSessions} more</p>}
            </Section>
          )}

          {v.improvements.length > 0 && (
            <Section title="Best improvements">
              <ul className="m-0 grid list-none gap-1.5 p-0">
                {v.improvements.map((i) => (
                  <li key={i.key} className="grid gap-0">
                    <span className="text-[15px] font-medium">{i.scopeText}</span>
                    <span className="text-[13px] text-muted">{i.text}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {v.goals.length > 0 && (
            <Section title="Goals this week">
              <ul className="m-0 grid list-none gap-2.5 p-0">
                {v.goals.map((g) => (
                  <li key={g.id} className="grid gap-1">
                    <span className="flex items-baseline justify-between gap-3">
                      <span className="min-w-0 text-[15px] font-medium">{g.reached ? `Reached: ${g.title}` : g.title}</span>
                      <span className="shrink-0 text-[13px] text-muted">{g.reached ? "" : (fractionChange(g.from, g.to) ?? "")}</span>
                    </span>
                    {g.to != null && (
                      <ProgressBar aria-label={`${g.title}: progress`} value={g.to}>
                        <ProgressBar.Track className="h-1.5 rounded-full bg-surface-tertiary">
                          <ProgressBar.Fill className={`rounded-full transition-none ${g.reached ? "bg-success" : "bg-foreground"}`} />
                        </ProgressBar.Track>
                      </ProgressBar>
                    )}
                    <span className="text-[13px] text-muted">{g.text}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {v.badges.length > 0 && (
            <Section title="Badges this week">
              <div className="flex flex-wrap gap-2">
                {v.badges.slice(0, WEEK_BADGES_SHOWN).map((b) => (
                  <Chip key={b} size="md" variant="soft">
                    <Medal aria-hidden="true" />
                    <Chip.Label>{b}</Chip.Label>
                  </Chip>
                ))}
                {v.badges.length > WEEK_BADGES_SHOWN && (
                  <Chip size="md" variant="soft">
                    <Chip.Label>+{v.badges.length - WEEK_BADGES_SHOWN} more</Chip.Label>
                  </Chip>
                )}
              </div>
            </Section>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-separator pt-3">
            <Button
              variant="secondary"
              className="min-h-11"
              onPress={() => window.open(motivationPaths.digestHtmlTab(driverId, v.weekStart), "_blank", "noopener")}
            >
              <Printer aria-hidden="true" />
              Printable page
            </Button>
            <CopyMarkdown text={v.markdown} />
          </div>
          <p className="m-0 text-[13px] text-muted">Real driving only: synthetic and replayed sessions are left out.</p>
        </>
      )}
    </Card>
  );
}
