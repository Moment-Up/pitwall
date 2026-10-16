// One game on Setup › Connect (spec 7.1): the integration (on/off, console IP, port, GT7 variant, Assetto Corsa
// platform; PUT /api/integrations/{key}, applied at once) with what is actually happening, how far its support is
// proven, and the game's own telemetry settings as a vertical Pro Stepper with a copy button on every value the
// driver types. Behaviour reference: web/src/views/ConnectView.svelte (drafts survive the refresh; F1 is always on).
// ACC (PC) has no IP or port: its card shows the shared-memory reader's sentence and counters, and says when it runs
// because ACC is the selected game even with the switch off.

import { Button, Card, Chip, Disclosure, Input, Label, Link, ListBox, Select, Switch, TextField } from "@heroui/react";
import { useEffect, useState } from "react";
import { CopyField } from "../../../components/ui";
import { cache } from "../../../lib/cache";
import {
  CONNECT_KEYS,
  ConnectError,
  connectApi,
  type ConnectInfo,
  type GameGuide,
  type Integration,
  type IntegrationUpdate,
} from "../../../lib/endpoints/connect";
import {
  AC_PLATFORMS,
  ago,
  CARD_STATE_LABEL,
  cardState,
  consoleIpLabel,
  consoleIpPlaceholder,
  draftDirty,
  draftFrom,
  evidenceOfStatus,
  GT7_VARIANTS,
  guideText,
  senderSummary,
  updateFromDraft,
  type CardState,
  type Draft,
} from "../../../lib/setup/connect";
import { href } from "../../../lib/router";
import { CopyButton } from "../shared/CopyButton";
import { GuideStepper } from "./GuideStepper";

const STATE_CHIP: Record<CardState, string> = {
  receiving: "[--chip-fg:var(--pw-status-live)] [--chip-bg:color-mix(in_oklab,var(--pw-status-live)_14%,transparent)]",
  waiting: "[--chip-fg:var(--pw-status-idle)] [--chip-bg:color-mix(in_oklab,var(--pw-status-idle)_14%,transparent)]",
  off: "",
  problem: "[--chip-fg:var(--warning)] [--chip-bg:color-mix(in_oklab,var(--warning)_14%,transparent)]",
};

function StateChip({ state }: { state: CardState }) {
  return (
    <Chip size="sm" variant="soft" className={STATE_CHIP[state]}>
      {state === "receiving" || state === "waiting" ? (
        <span aria-hidden="true" className="inline-block size-2 shrink-0 rounded-full bg-current" />
      ) : null}
      <Chip.Label>{CARD_STATE_LABEL[state]}</Chip.Label>
    </Chip>
  );
}

/** Store the PUT answer at once, then refetch the whole page payload. */
function applyIntegrations(list: Integration[]): void {
  const prev = cache.entry<ConnectInfo>(CONNECT_KEYS.connect).data;
  if (prev) cache.set<ConnectInfo>(CONNECT_KEYS.connect, { ...prev, integrations: list });
  cache.set(CONNECT_KEYS.integrations, list);
  cache.invalidate(CONNECT_KEYS.connect);
}

/** ACC's reader in numbers (only while it exists), and why it runs with the switch off. */
function AccDetails({ g }: { g: Integration }) {
  const r = g.reader;
  const pages = r?.by_page;
  return (
    <div className="grid gap-0.5 text-sm text-muted">
      {g.selected && !g.enabled ? <p className="m-0">On because ACC is the selected game (Setup › Game).</p> : null}
      {pages ? (
        <p className="m-0">
          Pages read: {pages.physics.toLocaleString("en-GB")} physics · {pages.graphics.toLocaleString("en-GB")} graphics ·{" "}
          {pages.static.toLocaleString("en-GB")} static
          {r?.last_rx_s_ago != null ? ` · last ${ago(r.last_rx_s_ago)}` : ""}
        </p>
      ) : null}
    </div>
  );
}

export function GameCard({ g, guide }: { g: Integration; guide: GameGuide | null }) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(g));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = draftDirty(g, draft);

  // A value saved elsewhere (another device) replaces an untouched draft; a draft being typed is never overwritten.
  useEffect(() => {
    if (!dirty) setDraft(draftFrom(g));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only when the server's values change
  }, [g.console_ip, g.port]);

  async function save(body: IntegrationUpdate, resetDraft = false) {
    setSaving(true);
    setError(null);
    try {
      const list = await connectApi.updateIntegration(g.key, body);
      applyIntegrations(list);
      if (resetDraft) {
        const next = list.find((x) => x.key === g.key);
        if (next) setDraft(draftFrom(next));
      }
    } catch (e) {
      setError(e instanceof ConnectError ? e.detail : e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function saveDraft() {
    const { body, error: problem } = updateFromDraft(g, draft);
    if (problem) {
      setError(problem);
      return;
    }
    if (body) void save(body, true);
  }

  const state = cardState(g);
  const ev = evidenceOfStatus(g.status);
  const showFields = g.needs_console_ip || g.port_editable || g.key === "gt7" || g.key === "ac";
  const guideOpen = g.key === "acc" ? (g.active ?? g.enabled) : g.enabled;

  return (
    <Card className="gap-4 p-5" aria-label={g.name}>
      <Card.Header className="flex-row flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Card.Title className="text-base font-semibold">{g.name}</Card.Title>
          <Card.Description className="text-sm text-muted">{g.platforms.join(" / ")}</Card.Description>
        </div>
        <div className="flex items-center gap-3">
          <StateChip state={state} />
          {g.key === "f1" ? (
            <Chip size="sm" variant="soft">
              <Chip.Label>Always on</Chip.Label>
            </Chip>
          ) : (
            <Switch
              isSelected={g.enabled}
              isDisabled={saving}
              onChange={(on: boolean) => void save({ enabled: on })}
              aria-label={`${g.name} on`}
            >
              <Switch.Content className="min-h-11">
                <Switch.Control>
                  <Switch.Thumb />
                </Switch.Control>
                <span className="w-7 text-sm">{g.enabled ? "On" : "Off"}</span>
              </Switch.Content>
            </Switch>
          )}
        </div>
      </Card.Header>

      <Card.Content className="grid gap-4">
        <div className="grid gap-1.5">
          <p className={`m-0 text-[15px] ${state === "receiving" ? "text-status-live" : state === "off" ? "text-muted" : ""}`}>
            {senderSummary(g)}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Chip size="sm" variant="soft" color={ev.tone} title={ev.detail}>
              <Chip.Label>{ev.label}</Chip.Label>
            </Chip>
          </div>
          {g.key === "gt7" && g.enabled ? (
            <p className="m-0 text-sm text-muted">
              Heartbeat to {g.console_ip ?? "broadcast (enter the PS5 IP for reliability)"}
              {g.heartbeat?.sent ? ` · ${g.heartbeat.sent.toLocaleString("en-GB")} sent` : ""}
              {g.heartbeat?.last_error ? ` · ${g.heartbeat.last_error}` : ""}
            </p>
          ) : null}
          {g.key === "ac" && g.enabled && g.client ? (
            <div className="grid gap-0.5 text-sm text-muted">
              <p className="m-0">
                Client {g.client.state} · {g.client.sent} sent · {g.client.received.toLocaleString("en-GB")} received
                {g.client.cycles ? ` · re-registered ${g.client.cycles}×` : ""}
                {g.client.last_rx_s_ago != null ? ` · last packet ${ago(g.client.last_rx_s_ago)}` : ""}
              </p>
              {g.client.last_handshake ? (
                <p className="m-0">
                  The game reports {g.client.last_handshake.car ?? "an unknown car"} at {g.client.last_handshake.track ?? "an unknown track"}
                  {g.client.last_handshake.config ? ` (${g.client.last_handshake.config})` : ""}
                </p>
              ) : null}
              {g.client.last_error && g.client.state !== "streaming" ? <p className="m-0">{g.client.last_error}</p> : null}
            </div>
          ) : null}
          {g.key === "acc" ? <AccDetails g={g} /> : null}
          {g.error ? <p className="m-0 text-sm text-danger">{g.error}</p> : null}
        </div>

        {showFields ? (
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              saveDraft();
            }}
          >
            {g.needs_console_ip ? (
              <TextField
                className="w-48"
                value={draft.console_ip}
                onChange={(v: string) => setDraft((d) => ({ ...d, console_ip: v }))}
                isDisabled={saving}
              >
                <Label>{consoleIpLabel(g)}</Label>
                <Input inputMode="decimal" placeholder={consoleIpPlaceholder(g)} className="min-h-11 font-mono text-base" autoComplete="off" />
              </TextField>
            ) : null}
            {g.port_editable ? (
              <TextField
                className="w-32"
                value={draft.port}
                onChange={(v: string) => setDraft((d) => ({ ...d, port: v }))}
                isDisabled={saving}
              >
                <Label>UDP port</Label>
                <Input inputMode="numeric" className="min-h-11 font-mono text-base" autoComplete="off" />
              </TextField>
            ) : null}
            {g.key === "gt7" ? (
              <Select
                className="w-36"
                selectedKey={g.variant}
                onSelectionChange={(k) => {
                  if (k !== null && String(k) !== g.variant) void save({ variant: String(k) });
                }}
                isDisabled={saving}
              >
                <Label>Packet variant</Label>
                <Select.Trigger className="min-h-11">
                  <Select.Value>{({ selectedText }) => <span className="font-mono">{selectedText}</span>}</Select.Value>
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {GT7_VARIANTS.map((v) => (
                      <ListBox.Item key={v.id} id={v.id} textValue={v.label} className="min-h-11">
                        <div className="grid">
                          <span className="font-mono font-semibold">{v.label}</span>
                          <span className="text-xs text-muted">{v.hint}</span>
                        </div>
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
            ) : null}
            {g.key === "ac" ? (
              <Select
                className="w-32"
                selectedKey={g.platform ?? "ps5"}
                onSelectionChange={(k) => {
                  if (k !== null && String(k) !== g.platform) void save({ platform: String(k) });
                }}
                isDisabled={saving}
              >
                <Label>Platform</Label>
                <Select.Trigger className="min-h-11">
                  <Select.Value />
                  <Select.Indicator />
                </Select.Trigger>
                <Select.Popover>
                  <ListBox>
                    {AC_PLATFORMS.map((p) => (
                      <ListBox.Item key={p.id} id={p.id} textValue={p.label} className="min-h-11">
                        {p.label}
                        <ListBox.ItemIndicator />
                      </ListBox.Item>
                    ))}
                  </ListBox>
                </Select.Popover>
              </Select>
            ) : null}
            {g.needs_console_ip || g.port_editable ? (
              <Button type="submit" variant={dirty ? "primary" : "secondary"} className="min-h-11" isDisabled={!dirty || saving} isPending={saving}>
                Save
              </Button>
            ) : null}
          </form>
        ) : null}
        {error ? (
          <p role="alert" className="m-0 text-sm text-danger">
            {error}
          </p>
        ) : null}

        {guide ? (
          <Disclosure defaultExpanded={guideOpen} className="border-t border-separator">
            <Disclosure.Heading>
              <Disclosure.Trigger className="flex min-h-14 w-full items-center justify-between gap-3 text-left">
                <span className="grid">
                  <span className="text-sm font-semibold">Set up the game</span>
                  <span className="text-xs text-muted">{guide.menu_path}</span>
                </span>
                <Disclosure.Indicator />
              </Disclosure.Trigger>
            </Disclosure.Heading>
            <Disclosure.Content>
              <Disclosure.Body className="grid gap-4 pb-1">
                {guide.supported ? null : (
                  <Chip size="sm" variant="soft" color="warning">
                    <Chip.Label>Not supported yet</Chip.Label>
                  </Chip>
                )}
                <GuideStepper guide={guide} integration={g} />
                {guide.extras.length ? (
                  <div className="grid gap-2">
                    <span className="text-sm font-semibold text-muted">Also recommended</span>
                    {guide.extras.map((s) => (
                      <div key={s.label} className="grid gap-1">
                        <span className="text-sm">{s.label}</span>
                        {s.copy ? (
                          <CopyField value={s.value} label={s.label} labelHidden />
                        ) : (
                          <span className="font-semibold">{s.value}</span>
                        )}
                        {s.note ? <span className="text-xs text-muted">{s.note}</span> : null}
                        {/^UDP Action \d+/.test(s.value) ? (
                          <Link href={href("/setup/controls?game=f1_25")} className="inline-flex min-h-11 items-center text-sm font-medium" data-testid="connect-controls-link">
                            Map your buttons: Setup › Controls
                          </Link>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {guide.notes.length ? (
                  <ul className="m-0 grid list-disc gap-1 pl-5 text-sm text-muted">
                    {guide.notes.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                ) : null}
                <div>
                  <CopyButton text={guideText(guide)} label="Copy all settings" what={`${g.name} settings`} variant="secondary" />
                </div>
              </Disclosure.Body>
            </Disclosure.Content>
          </Disclosure>
        ) : null}
      </Card.Content>
    </Card>
  );
}
