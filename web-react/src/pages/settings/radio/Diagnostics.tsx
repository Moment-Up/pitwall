// Settings › Radio & voice › Diagnostics (spec 8: "TTS status and diagnostics", HeroUI Disclosure): the Svelte
// RadioView's status badges and stats line, as one collapsible row of the "On the radio" group. The body is mounted
// only while open and samples the store once a second (frame counters change ~50 times a second while live).

import { Button, Disclosure } from "@heroui/react";
import { useState } from "react";
import { micChipView, useNow } from "../../../components/radio";
import { radio } from "../../../lib/radio";
import { diagnosticsRows, type MacState } from "./model";

function DiagnosticsBody({ mac }: { mac: MacState | null }) {
  useNow(1000); // re-render once a second; values are read from the store directly
  const s = radio.get();
  const rows = diagnosticsRows(s, mac, micChipView(s).label);
  const live = s.phase !== "idle";
  const audioBlocked = live && s.audio !== "running" && s.audio !== "none";
  const english = s.allVoices.filter((v) => v.lang.toLowerCase().replace("_", "-").startsWith("en"));
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
      {(live && s.micCapable) || audioBlocked ? (
        <div className="flex flex-wrap gap-2">
          {live && s.micCapable && (
            <Button className="min-h-11" size="lg" variant="secondary" onPress={() => void radio.restartMic()}>
              Restart mic
            </Button>
          )}
          {audioBlocked && (
            <Button className="min-h-11" size="lg" variant="secondary" onPress={() => radio.resumeAudio()}>
              Resume audio
            </Button>
          )}
        </div>
      ) : null}
      {english.length > 0 && (
        <Disclosure>
          <Disclosure.Heading>
            <Disclosure.Trigger className="flex min-h-11 items-center gap-2 text-sm font-medium text-muted">
              English voices this browser exposes ({english.length})
              <Disclosure.Indicator />
            </Disclosure.Trigger>
          </Disclosure.Heading>
          <Disclosure.Content>
            <Disclosure.Body>
              <ul className="m-0 grid list-none gap-1 p-0 text-sm text-muted">
                {english.map((v) => (
                  <li key={v.uri} className="min-w-0 break-words">
                    <span className="text-foreground">{v.name}</span> · {v.lang}
                    {v.default ? " · default" : ""} <span className="font-mono text-xs">{v.uri}</span>
                  </li>
                ))}
              </ul>
            </Disclosure.Body>
          </Disclosure.Content>
        </Disclosure>
      )}
    </div>
  );
}

export function DiagnosticsRow({ summary, mac }: { summary: string; mac: MacState | null }) {
  const [open, setOpen] = useState(false);
  return (
    <Disclosure isExpanded={open} onExpandedChange={setOpen}>
      <Disclosure.Heading>
        <Disclosure.Trigger className="flex min-h-14 w-full items-center gap-4 px-4 py-2.5 text-left">
          <span className="grid min-w-0 flex-1 gap-0.5">
            <span className="text-base font-medium text-foreground">Diagnostics</span>
            <span className="truncate text-sm text-muted">{summary}</span>
          </span>
          <Disclosure.Indicator className="text-muted" />
        </Disclosure.Trigger>
      </Disclosure.Heading>
      <Disclosure.Content>
        <Disclosure.Body>{open ? <DiagnosticsBody mac={mac} /> : null}</Disclosure.Body>
      </Disclosure.Content>
    </Disclosure>
  );
}
