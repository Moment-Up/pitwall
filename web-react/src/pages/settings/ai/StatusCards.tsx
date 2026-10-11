// The read-only parts of Settings › AI engineer: what is in use now (with health), Test, Usage today and "What gets
// sent" (the exact body of the last request). Port of the matching sections of web/src/views/SettingsView.svelte.

import { Button, Card, Chip } from "@heroui/react";
import { KPIGroup } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import { useState, type ReactNode } from "react";
import { Unknown } from "../../../components/ui";
import {
  fmtTokens,
  fmtUsd,
  llmApi,
  messageOf,
  type LastRequest,
  type Overview,
  type Purpose,
  type Role,
  type TestResult,
  type Usage,
} from "../../../lib/endpoints/settings";
import { secs, shortModel } from "./draft";

const timeOf = (t: number): string => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

function Dot() {
  return <span aria-hidden="true" className="size-2 rounded-full bg-current" />;
}

/** What the engineer uses now: one row per configured provider, with its live health. */
export function ProviderStatus({ ov }: { ov: Overview }) {
  return (
    <ul className="m-0 grid list-none gap-2 p-0">
      {ov.status.providers.map((s) => {
        const h = ov.health?.[s.role] ?? null;
        // No model chosen = the server's default; its health check says which model that is.
        const engineer = s.models.engineer ?? (h?.model ? `${shortModel(h.model)} (server default)` : "Server default");
        const models = `${s.models.engineer ? shortModel(engineer) : engineer}${s.models.radio && s.models.radio !== s.models.engineer ? ` · radio ${shortModel(s.models.radio)}` : ""}`;
        let chip: ReactNode = null;
        if (!ov.status.enabled) {
          chip = (
            <Chip variant="soft">
              <Chip.Label>Off</Chip.Label>
            </Chip>
          );
        } else if (s.blocked) {
          chip = (
            <Chip variant="soft" color="warning">
              <Chip.Label>Blocked</Chip.Label>
            </Chip>
          );
        } else if (h) {
          chip = (
            <Chip variant="soft" color={h.ok ? "success" : "warning"} className="gap-1.5">
              <Dot />
              <Chip.Label>{h.ok ? `Ready · ${secs(h.latency_ms)}` : "Unreachable"}</Chip.Label>
            </Chip>
          );
        }
        const problem = ov.status.enabled ? (s.blocked ?? (h && !h.ok ? h.detail : null)) : null;
        return (
          <li key={s.role} className="grid gap-1 rounded-2xl bg-surface-secondary px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-muted">{s.role === "primary" ? "Now" : "Fallback"}</span>
              <span className="font-semibold">{s.label}</span>
              <Chip size="sm" variant="soft" color={s.location === "cloud" ? "warning" : "default"}>
                <Chip.Label>{s.location === "cloud" ? "Cloud" : "Local"}</Chip.Label>
              </Chip>
              <span className="flex-1" />
              {chip}
            </div>
            <span className="truncate font-mono text-xs text-muted" title={models}>
              {models}
            </span>
            {problem && <span className="text-sm text-warning">{problem}</span>}
          </li>
        );
      })}
    </ul>
  );
}

type TestState = TestResult | "running" | { error: string };
const isResult = (t: TestState | undefined): t is TestResult => t != null && t !== "running" && !("error" in t);

/** One real question per provider and purpose, through the engineer's grounding check. */
export function TestCard({ ov, dirty, onTested }: { ov: Overview; dirty: boolean; onTested: () => void }) {
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const enabled = ov.status.enabled;

  async function run(role: Role, purpose: Purpose) {
    const k = `${role}:${purpose}`;
    setTests((t) => ({ ...t, [k]: "running" }));
    try {
      const r = await llmApi.test(role, purpose);
      setTests((t) => ({ ...t, [k]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [k]: { error: messageOf(e) } }));
    }
    onTested();
  }

  return (
    <Card>
      <Card.Header>
        <Card.Title className="text-base font-semibold">Test</Card.Title>
        <Card.Description>
          Asks one question about sample lap data through the real engineer, grounding check included. Cloud tests are
          billed like any other call.
        </Card.Description>
      </Card.Header>
      <Card.Content className="grid grid-cols-1 gap-3">
        {dirty && <p className="m-0 text-sm text-warning">Save first: tests use the saved settings.</p>}
        {!enabled && <p className="m-0 text-sm text-muted">The AI engineer is off.</p>}
        {ov.status.providers.flatMap((s) =>
          (["engineer", "radio"] as const).map((purpose) => {
            const k = `${s.role}:${purpose}`;
            const t = tests[k];
            const label = `Test ${s.role === "fallback" ? "fallback " : ""}${purpose}`;
            return (
              <div key={k} className="grid gap-2 rounded-2xl bg-surface-secondary px-4 py-3">
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    size="lg"
                    variant="secondary"
                    className="min-h-11 bg-surface"
                    isDisabled={dirty || !enabled}
                    isPending={t === "running"}
                    onPress={() => void run(s.role, purpose)}
                  >
                    {label}
                  </Button>
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted">{shortModel(s.models[purpose])}</span>
                  {isResult(t) && (
                    <>
                      <Chip variant="soft" color={t.ok ? "success" : "warning"}>
                        <Chip.Label>{t.ok ? "Works" : "Fell back to facts"}</Chip.Label>
                      </Chip>
                      <span className="pw-num text-[17px]">{secs(t.answer_latency_ms)}</span>
                    </>
                  )}
                </div>
                {isResult(t) && (
                  <>
                    <p className="m-0 text-sm">“{t.answer}”</p>
                    {!t.ok && <p className="m-0 text-sm text-warning">{t.issues.join("; ") || t.health.detail}</p>}
                    <p className="m-0 text-xs text-muted">{t.note}</p>
                  </>
                )}
                {t && t !== "running" && "error" in t && <p className="m-0 text-sm text-bad">{t.error}</p>}
              </div>
            );
          }),
        )}
      </Card.Content>
    </Card>
  );
}

function Metric({ title, children, tone }: { title: string; children: ReactNode; tone?: "warning" }) {
  return (
    <KPI className="min-w-0 px-3">
      <KPI.Header>
        <KPI.Title className="text-[13px]">{title}</KPI.Title>
      </KPI.Header>
      <KPI.Content>
        <span className={`pw-num truncate text-[32px] leading-none ${tone === "warning" ? "text-warning" : ""}`}>{children}</span>
      </KPI.Content>
    </KPI>
  );
}

/** Today's calls, tokens and cloud cost (estimates from published prices). */
export function UsageCard({ usage, error }: { usage: Usage | undefined; error: Error | null }) {
  const u = usage;
  return (
    <Card>
      <Card.Header>
        <Card.Title className="text-base font-semibold">Usage today</Card.Title>
      </Card.Header>
      <Card.Content className="grid grid-cols-1 gap-3">
        {!u ? (
          error ? (
            <p className="m-0 text-sm text-bad">Couldn&apos;t load usage: {messageOf(error)}</p>
          ) : (
            <p className="m-0 text-sm text-muted">Loading…</p>
          )
        ) : (
          <>
            <KPIGroup className="bg-surface-secondary shadow-none max-sm:grid max-sm:grid-cols-2">
              <Metric title="Calls">{u.today.calls}</Metric>
              <KPIGroup.Separator className="max-sm:hidden" />
              <Metric title="Tokens in">{fmtTokens(u.today.prompt_tokens)}</Metric>
              <KPIGroup.Separator className="max-sm:hidden" />
              <Metric title="Tokens out">{fmtTokens(u.today.completion_tokens)}</Metric>
              <KPIGroup.Separator className="max-sm:hidden" />
              <Metric title={u.budget.daily_usd != null ? `Cloud cost of ${fmtUsd(u.budget.daily_usd)}` : "Cloud cost"} tone={u.budget.reached ? "warning" : undefined}>
                {fmtUsd(u.today.cloud_cost_usd)}
              </Metric>
            </KPIGroup>
            {u.today.by_model.length > 0 ? (
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th className="py-1.5 font-medium">Model</th>
                    <th className="py-1.5 text-right font-medium">Calls</th>
                    <th className="py-1.5 text-right font-medium">Tokens</th>
                    <th className="py-1.5 text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {u.today.by_model.map((r) => (
                    <tr key={`${r.provider}|${r.model}`} className="border-t border-separator">
                      <td className="max-w-0 py-2 pr-2">
                        <div className="truncate font-mono text-xs" title={r.model ?? ""}>
                          {shortModel(r.model)}
                        </div>
                        <div className="text-xs text-muted">
                          {r.provider}
                          {r.location === "cloud" ? " · cloud" : ""}
                        </div>
                      </td>
                      <td className="pw-num py-2 text-right text-[15px]">
                        {[r.calls || (r.blocked ? "" : "0"), r.errors ? `${r.errors} failed` : "", r.blocked ? `${r.blocked} blocked` : ""]
                          .filter(Boolean)
                          .join(" · ")}
                      </td>
                      <td className="pw-num py-2 text-right text-[15px]">{fmtTokens(r.prompt_tokens + r.completion_tokens)}</td>
                      <td className="pw-num py-2 text-right text-[15px]">
                        {r.location === "local" ? "Free" : r.unpriced_calls ? <Unknown label="unknown cost" /> : fmtUsd(r.cost_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="m-0 text-sm text-muted">No model calls yet today.</p>
            )}
            {u.budget.unmetered_calls > 0 ? (
              <p className="m-0 text-sm text-warning">
                A cloud call today reported no token counts, so today&apos;s spend is unknown: cloud calls are paused until
                tomorrow (or remove the budget).
              </p>
            ) : u.budget.reached ? (
              <p className="m-0 text-sm text-warning">Daily budget reached: cloud calls are paused until tomorrow.</p>
            ) : null}
            {u.last_block && (
              <p className="m-0 text-xs text-muted">
                Last blocked call ({timeOf(u.last_block.at)}): {u.last_block.reason}
              </p>
            )}
            <p className="m-0 text-xs text-muted">Costs are estimates from published prices; your provider&apos;s bill is authoritative.</p>
          </>
        )}
      </Card.Content>
    </Card>
  );
}

/** The exact body of the last request sent to a model (headers, which carry the key, are left out). */
export function LastRequestCard() {
  const [last, setLast] = useState<LastRequest | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setBusy(true);
    setError(null);
    try {
      setLast((await llmApi.lastRequest()).last);
    } catch (e) {
      setError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <Card.Header>
        <Card.Title className="text-base font-semibold">What gets sent</Card.Title>
        <Card.Description>
          The exact body of the last request Pitwall sent to a model. HTTP headers, which carry the key, are left out.
        </Card.Description>
      </Card.Header>
      <Card.Content className="grid grid-cols-1 gap-3">
        <div>
          <Button className="min-h-11" size="lg" variant="secondary" isPending={busy} onPress={() => void load()}>
            {last === undefined ? "Show the last request" : "Refresh"}
          </Button>
        </div>
        {error && <p className="m-0 text-sm text-bad">{error}</p>}
        {last === null && <p className="m-0 text-sm text-muted">Nothing sent yet since Pitwall started.</p>}
        {last && (
          <>
            <p className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
              <span>{timeOf(last.at)}</span>·<strong>{last.provider_label}</strong>
              <Chip size="sm" variant="soft" color={last.location === "cloud" ? "warning" : "default"}>
                <Chip.Label>{last.location === "cloud" ? "Cloud" : "Local"}</Chip.Label>
              </Chip>
              · <span className="font-mono text-xs">{shortModel(last.model)}</span> · {last.purpose}
              {last.ok ? "" : " · failed"}
              {last.redaction_enabled
                ? ` · ${last.driver_names_redacted} driver name${last.driver_names_redacted === 1 ? "" : "s"} replaced`
                : ""}
            </p>
            <Card variant="secondary" className="p-0">
              <pre className="m-0 max-h-[420px] overflow-auto p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
                {JSON.stringify(last.request, null, 2)}
              </pre>
            </Card>
          </>
        )}
      </Card.Content>
    </Card>
  );
}
