// "What Pitwall saw" for one test (spec 12.3): the automatic verdict in plain words, a warning when the evidence is
// not live (a replay, generated data or a recording sent from this Mac: shown, never counted), up to four headline
// numbers (Pro KPIGroup), the checks with their status chips (heuristic thresholds marked as such), the reasons in the
// backend's words, and "How this is measured" (the catalogue's rule text). Nothing here is advice.

import { Alert } from "@heroui/react";
import { KPIGroup } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import { Fragment } from "react";
import type { CatalogItem, ItemState } from "../../../lib/endpoints/validation";
import { AUTO_CHIP, checkView, headlineMetrics, notLiveNotice, reasonText, shownReasons } from "../../../lib/validation/view";
import { Fold, SectionTitle, StatusChip } from "./parts";

export function EvidencePanel({ item, state }: { item: CatalogItem; state: ItemState }) {
  const auto = state.auto;
  const chip = AUTO_CHIP[auto.verdict] ?? AUTO_CHIP.no_evidence;
  const notLive = notLiveNotice(auto);
  // nothing seen yet: no big zeros (unknown is never shown as 0)
  const metrics = auto.verdict === "no_evidence" ? [] : headlineMetrics(item.id, auto.metrics);
  const checks = auto.checks.map((c) => checkView(c, auto.verdict));
  const reasons = shownReasons(auto); // the not-live warning above already says where the data came from
  const empty = !metrics.length && !checks.length && !reasons.length;
  return (
    <section className="grid gap-3" aria-labelledby={`saw-${item.id}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SectionTitle id={`saw-${item.id}`}>What Pitwall saw</SectionTitle>
        <StatusChip chip={chip} />
      </div>
      {notLive ? (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{notLive}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      {metrics.length ? (
        <KPIGroup className="max-md:grid max-md:grid-cols-2" role="group" aria-label="Headline numbers">
          {metrics.map((m, k) => (
            <Fragment key={m.key}>
              {k > 0 ? <KPIGroup.Separator className="max-md:hidden" /> : null}
              <KPI className="min-w-0">
                <KPI.Header>
                  <KPI.Title className="text-sm text-muted">{m.label}</KPI.Title>
                </KPI.Header>
                <KPI.Content className="min-h-9">
                  <span className={`pw-num text-[28px] leading-none ${m.value === "-" ? "text-faint" : ""}`}>{m.value}</span>
                </KPI.Content>
              </KPI>
            </Fragment>
          ))}
        </KPIGroup>
      ) : null}
      {checks.length ? (
        <ul className="m-0 grid list-none gap-2 p-0" aria-label="Checks">
          {checks.map((c) => (
            <li key={c.id} className="flex min-h-12 items-center gap-3 rounded-2xl bg-surface-secondary px-4 py-2">
              <span className="grid min-w-0 flex-1 gap-0.5">
                <span className="text-[15px] font-medium">{c.label}</span>
                <span className="text-sm text-muted">
                  <span className="font-semibold text-foreground">{c.value}</span>
                  {c.target ? <> · target {c.target}</> : null}
                  {c.heuristic ? " · heuristic" : ""}
                </span>
              </span>
              <StatusChip chip={c.chip} size="sm" />
            </li>
          ))}
        </ul>
      ) : null}
      {reasons.length ? (
        <ul className="m-0 grid list-disc gap-1 pl-5 text-[15px] text-muted">
          {reasons.map((r) => (
            <li key={r}>{reasonText(r)}</li>
          ))}
        </ul>
      ) : null}
      {empty ? <p className="m-0 text-[15px] text-muted">Nothing seen for this test yet.</p> : null}
      <Fold title="How this is measured" className="border-t border-separator">
        <p className="m-0 text-muted">{item.rule_text}</p>
        <p className="m-0 text-sm text-muted">Only data that arrives live from the console counts. Thresholds marked heuristic are first guesses.</p>
      </Fold>
    </section>
  );
}
