// Settings › System (spec 8; port of web/src/views/StatusView.svelte): server and worker health, the local LLM,
// captures with Replay, the synthetic demo (always labelled SYNTHETIC), the capability matrix with its evidence
// tiers, and the build version. Health polls every 10 s (every 2 s while a replay runs, to show its progress).
//
// Replay and the demo change what the live pipeline is fed, so they are explicit buttons with their result shown.

import { Alert, Button, Card, Chip, Dropdown, Label, Skeleton } from "@heroui/react";
import { DataGrid, KPIGroup, ListView, type DataGridColumn } from "@heroui-pro/react";
import { KPI } from "@heroui-pro/react/kpi";
import { useMemo, useState, type Key, type ReactNode } from "react";
import { CopyField, EvidenceChips, Unknown } from "../../components/ui";
import { useApi } from "../../hooks/useApi";
import { cache } from "../../lib/cache";
import { SETTINGS_KEYS, messageOf, systemApi } from "../../lib/endpoints/settings";
import { grouped } from "../../lib/format";
import { router } from "../../lib/router";
import type { PageProps } from "../../routes";
import { CapabilitySheet } from "./system/CapabilitySheet";
import { UpdateCard, UpdateChip, VersionText } from "./system/UpdateCard"; // lane install: update status
import {
  capabilityRows,
  captureView,
  contextText,
  fieldLevels,
  fileName,
  llmHealthView,
  modelName,
  replayNote,
  replayRunning,
  replayText,
  simulateNote,
  sortCaptures,
  telemetryText,
  udpText,
  workerErrorDetail,
  workerErrors,
  type CapabilityRow,
  type ChipTone,
} from "./system/model";
import { useWide } from "./useWide";

const CAPTURES_SHOWN = 6;

const REPLAY_SPEEDS: { id: string; speed: number | null; label: string }[] = [
  { id: "1", speed: 1, label: "Real time" },
  { id: "4", speed: 4, label: "4× speed" },
  { id: "max", speed: null, label: "As fast as possible" },
];

const DEMO_FORMATS: { id: string; format: number; label: string }[] = [
  { id: "2025", format: 2025, label: "F1 25 (UDP format 2025)" },
  { id: "2026", format: 2026, label: "F1 25 Season Pack (UDP format 2026)" },
];

function StatusChip({ tone, children }: { tone: ChipTone; children: ReactNode }) {
  return (
    <Chip variant="soft" color={tone} size="lg" className="gap-1.5">
      <span aria-hidden="true" className="size-2 rounded-full bg-current" />
      <Chip.Label>{children}</Chip.Label>
    </Chip>
  );
}

function Metric({ title, sub, children }: { title: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <KPI className="min-w-0">
      <KPI.Header>
        <KPI.Title>{title}</KPI.Title>
      </KPI.Header>
      <KPI.Content className="min-h-10">{children}</KPI.Content>
      {sub && <p className="m-0 mt-1 truncate text-xs text-muted">{sub}</p>}
    </KPI>
  );
}

/** label / value rows */
function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="m-0 grid grid-cols-[minmax(110px,auto)_minmax(0,1fr)] gap-x-4 gap-y-2.5 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="m-0 min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SystemPage(_props: PageProps) {
  const wide = useWide();
  const health = useApi(SETTINGS_KEYS.health, systemApi.health, { intervalMs: 10_000 });
  const running = replayRunning(health.data?.replay);
  // A second, faster poll while a replay runs (its packet count moves).
  useApi(running ? `${SETTINGS_KEYS.health}` : null, systemApi.health, { intervalMs: 2_000, maxAgeMs: 0 });
  const llm = useApi(SETTINGS_KEYS.llmHealth, systemApi.llmHealth);
  const caps = useApi(SETTINGS_KEYS.capabilities, systemApi.capabilities, { maxAgeMs: 5 * 60_000 });
  const captures = useApi(SETTINGS_KEYS.captures, systemApi.captures);

  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ text: string; synthetic?: boolean; path?: string } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [capRow, setCapRow] = useState<CapabilityRow | null>(null);

  const h = health.data;
  const errs = workerErrors(h);
  const llmView = llmHealthView(llm.data, llm.error ? messageOf(llm.error) : null);
  const sorted = useMemo(() => sortCaptures(captures.data ?? []), [captures.data]);
  const shown = showAll ? sorted : sorted.slice(0, CAPTURES_SHOWN);
  const syntheticCount = sorted.filter((c) => c.synthetic).length;
  const rows = useMemo(() => capabilityRows(caps.data ?? []), [caps.data]);

  async function replay(path: string, speed: number | null) {
    setBusy(`replay:${path}`);
    setActionError(null);
    try {
      await systemApi.replay(path, speed);
      setNote({ text: replayNote(path, speed), path });
      cache.invalidate(SETTINGS_KEYS.health);
      // Real-time replays are for watching: open Drive like the Svelte dashboard did.
      if (speed) router.navigate("/drive/coach");
    } catch (e) {
      setActionError(`Couldn't replay ${fileName(path)}: ${messageOf(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function stopReplay() {
    setBusy("stop");
    setActionError(null);
    try {
      await systemApi.stopReplay();
      setNote({ text: "Replay stopped." });
      cache.invalidate(SETTINGS_KEYS.health);
    } catch (e) {
      setActionError(`Couldn't stop the replay: ${messageOf(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function simulate(format: number) {
    setBusy("simulate");
    setActionError(null);
    setNote({ text: "Generating a synthetic session…", synthetic: true });
    try {
      const r = await systemApi.simulate("coaching-demo", format);
      setNote({ text: simulateNote(r.path), synthetic: true, path: r.path });
      cache.invalidate(SETTINGS_KEYS.captures);
    } catch (e) {
      setNote(null);
      setActionError(`Couldn't generate the synthetic demo: ${messageOf(e)}`);
    } finally {
      setBusy(null);
    }
  }

  const columns: DataGridColumn<CapabilityRow>[] = [
    {
      id: "game",
      header: "Integration",
      isRowHeader: true,
      minWidth: 220,
      cell: (r) => (
        <div className="grid min-w-0 py-1">
          <span className="font-medium whitespace-normal">{r.game}</span>
          <span className="text-xs whitespace-normal text-muted">{r.platform}</span>
        </div>
      ),
    },
    {
      id: "status",
      header: "Status",
      width: 230,
      cell: (r) => (
        <Chip variant="soft" color={r.support.tone} className="whitespace-nowrap">
          <Chip.Label>{r.support.label}</Chip.Label>
        </Chip>
      ),
    },
    {
      id: "evidence",
      header: "Evidence",
      minWidth: 160,
      cell: (r) => {
        const levels = fieldLevels(r);
        return (
          <div className="grid min-w-0 py-1 text-sm whitespace-normal">
            <span>{r.support.evidence}</span>
            {levels.length > 0 && (
              <span className="text-xs text-muted">
                Fields: {levels.map(([l, n]) => `${n} ${l.toLowerCase()}`).join(" · ")}
              </span>
            )}
          </div>
        );
      },
    },
  ];

  const replayLine = replayText(h?.replay);

  return (
    <div className="grid grid-cols-1 gap-4">
      {(health.error || actionError) && (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>{actionError ? "That didn't work" : "Couldn't reach the server"}</Alert.Title>
            <Alert.Description>{actionError ?? messageOf(health.error)}</Alert.Description>
          </Alert.Content>
        </Alert>
      )}

      <KPIGroup className="max-md:grid max-md:grid-cols-2" role="group" aria-label="System health">
        <Metric title="Server" sub={h ? <>Pitwall <VersionText /* lane install */ fallback={h.version} /></> : undefined}>
          {h ? (
            <StatusChip tone="success">Running</StatusChip>
          ) : health.error ? (
            <StatusChip tone="danger">Unreachable</StatusChip>
          ) : (
            <Skeleton className="h-7 w-24 rounded-full" />
          )}
        </Metric>
        <KPIGroup.Separator className="max-md:hidden" />
        <Metric title="Local LLM" sub={llm.data ? modelName(llm.data.model) : llmView.detail || undefined}>
          {llm.data || llm.error ? (
            <StatusChip tone={llmView.tone}>{llmView.label}</StatusChip>
          ) : (
            <Skeleton className="h-7 w-24 rounded-full" />
          )}
        </Metric>
        <KPIGroup.Separator className="max-md:hidden" />
        <Metric title="Captures" sub={captures.data ? `${syntheticCount} synthetic` : undefined}>
          <span className="pw-num text-[32px] leading-none">{captures.data ? grouped(captures.data.length) : <Unknown />}</span>
        </Metric>
        <KPIGroup.Separator className="max-md:hidden" />
        <Metric title="Worker errors" sub={h ? workerErrorDetail(h) : undefined}>
          <span className={`pw-num text-[32px] leading-none ${errs ? "text-warning" : ""}`}>
            {errs == null ? <Unknown /> : grouped(errs)}
          </span>
        </Metric>
      </KPIGroup>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card className="min-w-0">
          <Card.Header className="flex-row flex-wrap items-start justify-between gap-3">
            <div className="grid gap-1">
              <Card.Title className="text-base font-semibold">Captures</Card.Title>
              <Card.Description>Live sessions are recorded automatically. Replay one without a game.</Card.Description>
            </div>
            <Dropdown>
              <Button className="min-h-11" size="lg" variant="secondary" isPending={busy === "simulate"}>
                Synthetic demo
              </Button>
              <Dropdown.Popover placement="bottom end" className="w-[min(320px,calc(100vw-20px))]">
                <Dropdown.Menu
                  aria-label="Generate a synthetic demo"
                  onAction={(k: Key) => {
                    const f = DEMO_FORMATS.find((x) => x.id === String(k));
                    if (f) void simulate(f.format);
                  }}
                >
                  {DEMO_FORMATS.map((f) => (
                    <Dropdown.Item key={f.id} id={f.id} textValue={f.label} className="min-h-12">
                      <Label>{f.label}</Label>
                    </Dropdown.Item>
                  ))}
                </Dropdown.Menu>
              </Dropdown.Popover>
            </Dropdown>
          </Card.Header>
          <Card.Content className="grid grid-cols-1 gap-3">
            <p className="m-0 text-xs text-muted">
              The synthetic demo is generated data with known mistakes, labelled SYNTHETIC everywhere. It never counts as
              game compatibility.
            </p>
            {note && (
              <div role="status" className="flex flex-wrap items-center gap-2 rounded-2xl bg-surface-secondary px-4 py-3 text-sm">
                {note.synthetic && <EvidenceChips synthetic />}
                <span className="min-w-0 flex-1">{note.text}</span>
                {note.synthetic && note.path && (
                  <Button className="min-h-11" size="lg" variant="primary" isPending={busy === `replay:${note.path}`} onPress={() => void replay(note.path!, 1)}>
                    Replay it
                  </Button>
                )}
              </div>
            )}
            {replayLine && (
              <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-surface-secondary px-4 py-3 text-sm">
                <EvidenceChips replay synthetic={h?.replay?.synthetic} />
                <span className="min-w-0 flex-1 font-mono text-xs">{replayLine}</span>
                {running && (
                  <Button className="min-h-11" size="lg" variant="danger-soft" isPending={busy === "stop"} onPress={() => void stopReplay()}>
                    Stop replay
                  </Button>
                )}
              </div>
            )}
            {!captures.data ? (
              captures.error ? (
                <p className="m-0 text-sm text-bad">Couldn&apos;t load the captures: {messageOf(captures.error)}</p>
              ) : (
                <Skeleton className="h-48 rounded-2xl" />
              )
            ) : (
              <ListView
                aria-label="Captures"
                items={shown}
                renderEmptyState={() => (
                  <p className="m-0 p-4 text-sm text-muted">No captures yet. Live sessions are recorded automatically.</p>
                )}
              >
                {(c) => {
                  const v = captureView(c);
                  return (
                    <ListView.Item id={c.path} textValue={c.name} className="min-h-14">
                      <ListView.ItemContent>
                        <div className="flex min-w-0 flex-1 flex-col">
                          <ListView.Title className="flex min-w-0 items-center gap-2">
                            <span className="truncate font-mono text-[13px]">{v.name}</span>
                            <EvidenceChips synthetic={v.synthetic} />
                          </ListView.Title>
                          <ListView.Description>{v.detail}</ListView.Description>
                        </div>
                      </ListView.ItemContent>
                      <ListView.ItemAction>
                        <Dropdown>
                          <Button className="min-h-11" size="lg" variant="outline" isPending={busy === `replay:${c.path}`} aria-label={`Replay ${c.name}`}>
                            Replay
                          </Button>
                          <Dropdown.Popover placement="bottom end">
                            <Dropdown.Menu
                              aria-label="Replay speed"
                              onAction={(k: Key) => {
                                const s = REPLAY_SPEEDS.find((x) => x.id === String(k));
                                if (s) void replay(c.path, s.speed);
                              }}
                            >
                              {REPLAY_SPEEDS.map((s) => (
                                <Dropdown.Item key={s.id} id={s.id} textValue={s.label} className="min-h-12">
                                  <Label>{s.label}</Label>
                                </Dropdown.Item>
                              ))}
                            </Dropdown.Menu>
                          </Dropdown.Popover>
                        </Dropdown>
                      </ListView.ItemAction>
                    </ListView.Item>
                  );
                }}
              </ListView>
            )}
            {sorted.length > CAPTURES_SHOWN && (
              <div>
                <Button className="min-h-11" size="lg" variant="ghost" onPress={() => setShowAll((v) => !v)}>
                  {showAll ? "Show fewer" : `Show all ${sorted.length}`}
                </Button>
              </div>
            )}
          </Card.Content>
        </Card>

        <div className="grid min-w-0 grid-cols-1 gap-4">
          <Card>
            <Card.Header>
              <Card.Title className="text-base font-semibold">Server</Card.Title>
            </Card.Header>
            <Card.Content>
              {h ? (
                <Facts
                  rows={[
                    ["Version", <span className="inline-flex flex-wrap items-center gap-2"><span className="font-mono"><VersionText /* lane install */ fallback={h.version} /></span><UpdateChip /* lane install */ /></span>],
                    ["Telemetry", telemetryText(h)],
                    ["UDP listener", udpText(h)],
                    ["Replay", replayLine ?? <Unknown label="no replay" />],
                    ["Laps analysed", grouped(h.laps_processed)],
                    ["Worker errors", workerErrorDetail(h)],
                    [
                      "Licences",
                      <span className="text-muted">
                        Listed in <span className="font-mono">docs/licences.md</span> in the Pitwall folder
                      </span>,
                    ],
                  ]}
                />
              ) : (
                <Skeleton className="h-36 rounded-2xl" />
              )}
            </Card.Content>
          </Card>
          <UpdateCard /* lane install: below the Server card */ />
          <Card>
            <Card.Header>
              <Card.Title className="text-base font-semibold">Local LLM</Card.Title>
              <Card.Description>Explains facts only. Coaching and cues never need it.</Card.Description>
            </Card.Header>
            <Card.Content>
              {llm.data ? (
                <Facts
                  rows={[
                    ["Status", `${llmView.label}${llm.data.ok ? "" : ` · ${llm.data.detail}`}`],
                    ["Endpoint", <CopyField value={llm.data.base_url} label="Local LLM endpoint" labelHidden />],
                    ["Model", <span className="font-mono text-xs break-all">{modelName(llm.data.model)}</span>],
                    ["Context", contextText(llm.data.context_tokens)],
                  ]}
                />
              ) : llm.error ? (
                <p className="m-0 text-sm text-bad">{messageOf(llm.error)}</p>
              ) : (
                <Skeleton className="h-28 rounded-2xl" />
              )}
              <div className="mt-3">
                <Button className="min-h-11" size="lg" variant="secondary" onPress={() => router.navigate("/settings/ai")}>
                  AI engineer settings
                </Button>
              </div>
            </Card.Content>
          </Card>
        </div>
      </div>

      <Card>
        <Card.Header>
          <Card.Title className="text-base font-semibold">Capability matrix</Card.Title>
          <Card.Description>
            What each game integration can do and how well it is verified. Nothing is validated until it has been
            tested with the real game on that platform. Tap a row for its notes and fields.
          </Card.Description>
        </Card.Header>
        <Card.Content>
          {!caps.data ? (
            caps.error ? (
              <p className="m-0 text-sm text-bad">Couldn&apos;t load the capability matrix: {messageOf(caps.error)}</p>
            ) : (
              <Skeleton className="h-64 rounded-2xl" />
            )
          ) : (
            <DataGrid
              aria-label="Capability matrix"
              data={rows}
              columns={columns}
              getRowId={(r) => r.id}
              variant="secondary"
              verticalAlign="middle"
              onRowAction={(k) => setCapRow(rows.find((r) => r.id === k) ?? null)}
            />
          )}
        </Card.Content>
      </Card>

      <CapabilitySheet row={capRow} wide={wide} onClose={() => setCapRow(null)} />
    </div>
  );
}
