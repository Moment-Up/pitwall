// Settings › Radio & voice › Spotter (design spec 9.2): the F1 spotter's card, beside "Braking calls". One master
// switch (default Off); while it is on: the status line, the send-rate warning, spoken calls and iPad bars, the
// session types, the start delay, wording, the spotter's own voice (Kokoro only), "Still there" and "Hold your line",
// Test spotter and the diagnostics (every recent call in full: the radio log folds them).
//
// Pure: the spotter status (GET /api/spotter), the Mac's voices and the actions come in as props, so the render tests
// drive it with plain objects. SpotterSettings.tsx wires it to the API.

import { Button, Disclosure } from "@heroui/react";
import { useState } from "react";
import type { SpotterInfo, SpotterSettings, SpotterWording } from "../../../lib/spotter/types";
import { START_DELAY_MAX_S, START_DELAY_MIN_S } from "../../../lib/spotter/types";
import { CellGroup, CellRow, SegmentRow, SelectRow, SliderRow, SwitchRow } from "../cells";
import {
  diagnosticsRows,
  diagnosticsSummary,
  masterView,
  recentRows,
  sendRateWarning,
  startDelayText,
  statusView,
  testView,
  TOGGLE_HINTS,
  voiceFromOption,
  voiceView,
  WORDINGS,
  type SpotterTestState,
} from "./spotter";

export interface SpotterActions {
  /** Save a partial change. `debounce` for the slider (one PUT when it settles). */
  update: (patch: Partial<SpotterSettings>, opts?: { debounce?: boolean }) => void;
  test: () => void;
}

export interface SpotterCardProps {
  /** GET /api/spotter with unsaved changes laid over; undefined = not read yet (or unreadable: see `error`). */
  info: SpotterInfo | undefined;
  /** Reading the status failed (shown while there is nothing to show). */
  error: string | null;
  /** The last save failed (the server's words, e.g. a 422). */
  saveError: string | null;
  /** The Mac's voice engine ("kokoro" | "say" | "none") and the Kokoro voices it offers. */
  engine: string | null;
  voices: readonly string[];
  test: SpotterTestState;
  actions: SpotterActions;
}

function SpotterDiagnostics({ info }: { info: SpotterInfo }) {
  const [open, setOpen] = useState(false);
  return (
    <Disclosure isExpanded={open} onExpandedChange={setOpen}>
      <Disclosure.Heading>
        <Disclosure.Trigger className="flex min-h-14 w-full items-center gap-4 px-4 py-2.5 text-left">
          <span className="grid min-w-0 flex-1 gap-0.5">
            <span className="text-base font-medium text-foreground">Spotter diagnostics</span>
            <span className="truncate text-sm text-muted">{diagnosticsSummary(info)}</span>
          </span>
          <Disclosure.Indicator className="text-muted" />
        </Disclosure.Trigger>
      </Disclosure.Heading>
      <Disclosure.Content>
        <Disclosure.Body>{open ? <DiagnosticsBody info={info} /> : null}</Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}

function DiagnosticsBody({ info }: { info: SpotterInfo }) {
  const rows = diagnosticsRows(info);
  const recent = recentRows(info.recent);
  return (
    <div className="grid gap-3 px-4 pb-4">
      <dl className="m-0 grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
        {rows.map((r) => (
          <div key={r.label} className="contents">
            <dt className="text-muted">{r.label}</dt>
            <dd className={`m-0 min-w-0 break-words ${r.warn ? "text-warning" : ""}`}>{r.value}</dd>
          </div>
        ))}
      </dl>
      <section aria-label="Recent spotter calls" className="grid gap-1">
        <h3 className="m-0 text-sm font-semibold text-muted">Recent calls</h3>
        {recent.length ? (
          <ul className="m-0 grid list-none gap-1 p-0 text-sm">
            {recent.map((r) => (
              <li key={r.key} className="grid grid-cols-[4.5rem_minmax(0,1fr)_auto] gap-x-3">
                <span className="pw-num text-muted tabular-nums">{r.time}</span>
                <span className="min-w-0 break-words">{r.text}</span>
                <span className={r.spoken ? "text-muted" : "text-faint"}>{r.detail}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="m-0 text-sm text-muted">No calls yet.</p>
        )}
      </section>
    </div>
  );
}

export function SpotterCard({ info, error, saveError, engine, voices, test, actions }: SpotterCardProps) {
  if (!info) {
    return (
      <CellGroup label="Spotter">
        <CellRow
          title="Spotter"
          hint={error ? `Couldn't read the spotter's status: ${error}` : "Unknown until the Mac answers."}
          hintTone={error ? "warning" : "muted"}
        >
          <span className="text-faint">-</span>
        </CellRow>
      </CellGroup>
    );
  }
  const s = info.settings;
  const master = masterView(info);
  const status = statusView(info);
  const rate = sendRateWarning(info);
  const voice = voiceView(engine, voices, s.voice);
  const t = testView(info, test);
  const set = (patch: Partial<SpotterSettings>) => actions.update(patch);
  return (
    <CellGroup label="Spotter">
      <SwitchRow title="Spotter" hint={master.hint} isSelected={master.on} isDisabled={master.disabled} onChange={(v) => set({ enabled: v })} />
      {saveError && (
        <CellRow title="Not saved" hint={saveError} hintTone="warning" />
      )}
      {s.enabled && (
        <>
          <CellRow title={status.title} hint={status.detail || undefined} hintTone={status.warn ? "warning" : "muted"} />
          {rate && <CellRow title="UDP send rate" hint={rate} hintTone="warning" />}
          <SwitchRow title="Spoken calls" hint={TOGGLE_HINTS.audio} isSelected={s.audio} onChange={(v) => set({ audio: v })} />
          <SwitchRow title="iPad bars" hint={TOGGLE_HINTS.visual} isSelected={s.visual} onChange={(v) => set({ visual: v })} />
          <SwitchRow title="Also in qualifying" hint={TOGGLE_HINTS.qualifying} isSelected={s.qualifying} onChange={(v) => set({ qualifying: v })} />
          <SwitchRow title="Also in practice" hint={TOGGLE_HINTS.practice} isSelected={s.practice} onChange={(v) => set({ practice: v })} />
          <SliderRow
            title="Start after lights out"
            value={s.start_delay_s}
            min={START_DELAY_MIN_S}
            max={START_DELAY_MAX_S}
            step={1}
            format={startDelayText}
            onChange={(v) => actions.update({ start_delay_s: v }, { debounce: true })}
          />
          <SegmentRow<SpotterWording>
            title="Wording"
            hint={WORDINGS.find((w) => w.value === s.wording)?.hint}
            value={s.wording}
            choices={WORDINGS}
            onChange={(w) => set({ wording: w })}
          />
          {voice.show && (
            <SelectRow
              title="Spotter voice"
              hint={voice.hint}
              value={voice.value}
              options={voice.options}
              onChange={(id) => set({ voice: voiceFromOption(id) })}
            />
          )}
          <SwitchRow title="Still there" hint={TOGGLE_HINTS.still_there} isSelected={s.still_there} onChange={(v) => set({ still_there: v })} />
          <SwitchRow
            title="Hold your line"
            hint={TOGGLE_HINTS.hold_your_line}
            isSelected={s.hold_your_line}
            onChange={(v) => set({ hold_your_line: v })}
          />
          <CellRow title="Test spotter" hint={t.hint} hintTone={t.warn ? "warning" : "muted"}>
            <Button className="min-h-11" size="lg" variant="secondary" isDisabled={!t.enabled} onPress={() => actions.test()}>
              Test spotter
            </Button>
          </CellRow>
          <SpotterDiagnostics info={info} />
        </>
      )}
    </CellGroup>
  );
}
