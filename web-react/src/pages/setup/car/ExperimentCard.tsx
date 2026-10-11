// A setup experiment (spec 7.3): one parameter changed between a session before and a session after. Pro ItemCard
// header (parameter, from → to, status) and a Pro Stepper Proposed → Running → Concluded. Open experiments can be
// linked to the session driven with the change, compared and concluded, or abandoned; a concluded one shows the lap
// time and corner deltas with the backend's reason, setup check and conclusion verbatim (behaviour reference: the
// experiments section of web/src/views/CarSetupView.svelte). `compact` is the read-only summary used on the main page.

import { Button, Card, Chip, Disclosure, Input, Label, ListBox, Select, TextField } from "@heroui/react";
import { ItemCard, Stepper } from "@heroui-pro/react";
import { useState } from "react";
import { TimingValue } from "../../../components/ui";
import { cache } from "../../../lib/cache";
import {
  carsetupApi,
  errorText,
  type ExperimentStatus,
  type ParameterInfo,
  type SessionOption,
  type SetupExperiment,
  type Verdict,
} from "../../../lib/endpoints/carsetup";
import { lapTime } from "../../../lib/format";
import {
  afterCandidates,
  afterFor,
  experimentStep,
  mean,
  paramValue,
  pct,
  sessionLabel,
  STATUS_LABEL,
  VERDICT_LABEL,
  when,
} from "../../../lib/setup/carsetup";
import { ExperimentBalance } from "./ExperimentBalance"; // feat/technique

const STEPS = ["Proposed", "Running", "Concluded"] as const;

const STATUS_COLOR: Record<ExperimentStatus, "default" | "accent" | "success" | "warning"> = {
  proposed: "default",
  running: "accent",
  concluded: "default",
  abandoned: "warning",
};

const VERDICT_COLOR: Record<Verdict, "success" | "danger" | "default" | "warning"> = {
  faster: "success",
  slower: "danger",
  no_clear_difference: "default",
  inconclusive: "warning",
};

function Delta({ s }: { s: number | null | undefined }) {
  return <TimingValue kind="delta" ms={s === null || s === undefined ? null : s * 1000} digits={3} size="table" context="table" />;
}

function ExperimentStepper({ exp }: { exp: SetupExperiment }) {
  return (
    <Stepper
      size="sm"
      currentStep={experimentStep(exp)}
      aria-label={`Experiment ${STATUS_LABEL[exp.status].toLowerCase()}`}
      className="[--stepper-complete-color:var(--success)] [--stepper-complete-fg:var(--success-foreground)]"
    >
      {STEPS.map((s) => (
        <Stepper.Step key={s}>
          <Stepper.Indicator />
          <Stepper.Content>
            <Stepper.Title className="text-xs">{s}</Stepper.Title>
          </Stepper.Content>
          <Stepper.Separator />
        </Stepper.Step>
      ))}
    </Stepper>
  );
}

export interface ExperimentCardProps {
  exp: SetupExperiment;
  param: ParameterInfo | undefined;
  sessions: SessionOption[];
  /** Read-only summary with an Open action (main page). */
  compact?: boolean;
  onOpen?: () => void;
}

export function ExperimentCard({ exp, param, sessions, compact = false, onOpen }: ExperimentCardProps) {
  const [busy, setBusy] = useState<"start" | "conclude" | "abandon" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [abandoning, setAbandoning] = useState(false);
  const [reason, setReason] = useState("");
  const cmp = exp.after_metrics?.comparison;
  const b = exp.before_metrics;
  const a = exp.after_metrics;
  const cands = afterCandidates(exp, sessions);
  const after = afterFor(exp, sessions, picked);
  const open = exp.status === "proposed" || exp.status === "running";
  const name = (id: string | null) => {
    if (!id) return "not linked yet";
    const s = sessions.find((x) => x.id === id);
    return s ? sessionLabel(s) : id;
  };

  async function act(action: "start" | "conclude" | "abandon") {
    setBusy(action);
    setError(null);
    try {
      if (action === "start") {
        if (!after) throw new Error("Pick the session you drove with the change first.");
        await carsetupApi.start(exp.id, after);
      } else if (action === "conclude") {
        await carsetupApi.conclude(exp.id);
      } else {
        await carsetupApi.abandon(exp.id, reason);
        setAbandoning(false);
        setReason("");
      }
      cache.invalidate("carsetup:experiments:");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card variant="secondary" className="gap-3 p-4" aria-label={`Experiment: ${param?.label ?? exp.parameter}`}>
      <ItemCard variant="transparent" className="p-0">
        <ItemCard.Content>
          <ItemCard.Title className="text-base font-semibold">{param?.label ?? exp.parameter}</ItemCard.Title>
          <ItemCard.Description className="text-sm text-muted">
            <span className="pw-num text-lg text-foreground">
              {paramValue(param, exp.from_value)} → {paramValue(param, exp.to_value)}
            </span>{" "}
            · {when(exp.created_unix)}
          </ItemCard.Description>
        </ItemCard.Content>
        <ItemCard.Action className="flex items-center gap-2">
          <Chip size="sm" variant="soft" color={STATUS_COLOR[exp.status]}>
            <Chip.Label>{STATUS_LABEL[exp.status]}</Chip.Label>
          </Chip>
          {compact && onOpen ? (
            <Button variant="ghost" size="sm" className="min-h-11" onPress={onOpen}>
              Open
            </Button>
          ) : null}
        </ItemCard.Action>
      </ItemCard>
      {exp.status !== "abandoned" ? <ExperimentStepper exp={exp} /> : null}
      {exp.hypothesis ? <p className="m-0 text-[15px]">{exp.hypothesis}</p> : null}
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted">Before</dt>
        <dd className="m-0">{name(exp.before_session_id)}</dd>
        <dt className="text-muted">After</dt>
        <dd className="m-0">{name(exp.after_session_id)}</dd>
      </dl>

      {!compact && open ? (
        <div className="grid gap-3">
          {cands.length ? (
            <div className="flex flex-wrap items-end gap-2">
              <Select
                className="min-w-64 flex-1"
                selectedKey={after}
                onSelectionChange={(k) => setPicked(k === null ? null : String(k))}
                isDisabled={busy !== null}
              >
                <Label>Session driven with the change</Label>
                <Select.Trigger className="min-h-11">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {cands.map((c) => (
                      <ListBox.Item key={c.id} id={c.id} textValue={sessionLabel(c)} className="min-h-12">
                        {sessionLabel(c)}
                        {c.synthetic ? " · SYNTHETIC" : ""}
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
              <Button
                variant="secondary"
                className="min-h-11"
                isDisabled={busy !== null || !after || after === exp.after_session_id}
                isPending={busy === "start"}
                onPress={() => void act("start")}
              >
                {exp.after_session_id ? "Change session" : "Link session"}
              </Button>
            </div>
          ) : (
            <p className="m-0 text-sm text-muted">Drive a session on this track with only this change, then link it here.</p>
          )}
          <div className="flex flex-wrap gap-2">
            {exp.status === "running" ? (
              <Button className="min-h-11" isDisabled={busy !== null} isPending={busy === "conclude"} onPress={() => void act("conclude")}>
                Compare and conclude
              </Button>
            ) : null}
            {abandoning ? null : (
              <Button variant="ghost" className="min-h-11" isDisabled={busy !== null} onPress={() => setAbandoning(true)}>
                Abandon…
              </Button>
            )}
          </div>
          {abandoning ? (
            <div className="flex flex-wrap items-end gap-2 rounded-xl bg-surface p-3">
              <TextField className="min-w-56 flex-1" value={reason} onChange={setReason} maxLength={500}>
                <Label>Reason (optional)</Label>
                <Input className="min-h-11" />
              </TextField>
              <Button variant="danger-soft" className="min-h-11" isPending={busy === "abandon"} isDisabled={busy !== null} onPress={() => void act("abandon")}>
                Abandon experiment
              </Button>
              <Button variant="ghost" className="min-h-11" onPress={() => setAbandoning(false)}>
                Keep it
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {cmp && !compact ? (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Chip variant="soft" color={VERDICT_COLOR[cmp.verdict]}>
              <Chip.Label>{VERDICT_LABEL[cmp.verdict]}</Chip.Label>
            </Chip>
            <span className="text-sm">{cmp.reason}</span>
          </div>
          {/* feat/technique */}
          <ExperimentBalance comparison={cmp} />
          <table className="w-full border-separate border-spacing-0 text-sm">
            <thead>
              <tr className="text-muted">
                <th className="py-2 pr-3 text-left font-medium" />
                <th className="py-2 pr-3 text-right font-medium">Before</th>
                <th className="py-2 pr-3 text-right font-medium">After</th>
                <th className="py-2 text-right font-medium">Change</th>
              </tr>
            </thead>
            <tbody className="[&_td]:border-t [&_td]:border-separator [&_td]:py-2">
              {(
                [
                  ["Median clean lap", b?.median_clean_ms, a?.median_clean_ms, cmp.median_delta_s],
                  ["Best clean lap", b?.best_clean_ms, a?.best_clean_ms, cmp.best_delta_s],
                  ["Theoretical best", b?.theoretical_best_ms, a?.theoretical_best_ms, cmp.theoretical_delta_s],
                ] as const
              ).map(([label, before, aft, d]) => (
                <tr key={label}>
                  <td className="pr-3 text-muted">{label}</td>
                  <td className="pw-num pr-3 text-right text-[17px]">{lapTime(before)}</td>
                  <td className="pw-num pr-3 text-right text-[17px]">{lapTime(aft)}</td>
                  <td className="text-right">
                    <Delta s={d} />
                  </td>
                </tr>
              ))}
              <tr>
                <td className="pr-3 text-muted">Clean laps</td>
                <td className="pw-num pr-3 text-right text-[17px]">{b?.clean_laps ?? "-"}</td>
                <td className="pw-num pr-3 text-right text-[17px]">{a?.clean_laps ?? "-"}</td>
                <td className="text-right text-xs text-faint">{cmp.noise_s !== null ? `noise ±${cmp.noise_s.toFixed(3)} s` : ""}</td>
              </tr>
              {mean(b?.wear_rate_pct_per_lap) !== null || mean(a?.wear_rate_pct_per_lap) !== null ? (
                <tr>
                  <td className="pr-3 text-muted">Tyre wear per lap</td>
                  <td className="pw-num pr-3 text-right text-[17px]">{pct(mean(b?.wear_rate_pct_per_lap))}</td>
                  <td className="pw-num pr-3 text-right text-[17px]">{pct(mean(a?.wear_rate_pct_per_lap))}</td>
                  <td />
                </tr>
              ) : null}
            </tbody>
          </table>
          <p className="m-0 text-sm">
            <span className="text-muted">Setup check: </span>
            {cmp.setup_check.applied === true
              ? "the change was applied"
              : cmp.setup_check.applied === false
                ? "the after session does not have the experiment's value"
                : (cmp.setup_check.note ?? "unknown")}
            {cmp.setup_check.applied !== null && cmp.setup_check.note ? <span className="text-muted"> · {cmp.setup_check.note}</span> : null}
          </p>
          {cmp.setup_check.other_changes.length ? (
            <p role="note" className="m-0 rounded-xl bg-surface px-3 py-2 text-sm text-warning">
              Other settings changed too, so the effect cannot be put down to this one change:{" "}
              {cmp.setup_check.other_changes.map((o) => `${o.label} ${o.before} → ${o.after}`).join(", ")}
            </p>
          ) : null}
          {cmp.corners.length ? (
            <Disclosure className="border-t border-separator">
              <Disclosure.Heading>
                <Disclosure.Trigger className="flex min-h-12 w-full items-center justify-between text-left text-sm font-semibold">
                  Corner by corner ({cmp.corners.length})
                  <Disclosure.Indicator />
                </Disclosure.Trigger>
              </Disclosure.Heading>
              <Disclosure.Content>
                <Disclosure.Body>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-muted">
                        <th className="py-1.5 text-left font-medium">Corner</th>
                        <th className="py-1.5 text-right font-medium">Laps</th>
                        <th className="py-1.5 text-right font-medium">Time</th>
                        <th className="py-1.5 text-right font-medium">Slowest speed</th>
                        <th className="py-1.5 text-right font-medium">Exit speed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cmp.corners.map((c) => (
                        <tr key={c.corner} className="border-t border-separator">
                          <td className="py-1.5">{c.label}</td>
                          <td className="pw-num py-1.5 text-right">{c.laps}</td>
                          <td className="py-1.5 text-right">
                            <Delta s={c.mean_time_delta_s} />
                          </td>
                          <td className="pw-num py-1.5 text-right">{kph(c.mean_min_speed_delta_kph)}</td>
                          <td className="pw-num py-1.5 text-right">{kph(c.mean_exit_speed_delta_kph)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Disclosure.Body>
              </Disclosure.Content>
            </Disclosure>
          ) : null}
        </div>
      ) : null}
      {exp.conclusion ? <p className="m-0 text-[15px]">{exp.conclusion}</p> : null}
    </Card>
  );
}

function kph(v: number | null): string {
  if (v === null || !Number.isFinite(v)) return "-";
  const n = Math.abs(v).toFixed(1);
  return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${n} km/h`;
}
