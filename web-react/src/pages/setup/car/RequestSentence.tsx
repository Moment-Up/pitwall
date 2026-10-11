// The car setup request as a sentence (spec 7.3, mockup "Setup › Car setup"): "Setup for the 2025 car at
// Silverstone, Race, Dry, Stable", each choice a Pro InlineSelect, with a line under it that says who the style was
// chosen for ("chosen for Alex, a beginner") or that it is the driver's own choice. Every option says what would
// stand in for it ("qualifying setup shown", "no setup") so nothing is substituted silently.

import { Button, ListBox } from "@heroui/react";
import { InlineSelect } from "@heroui-pro/react";
import type { Key, ReactNode } from "react";
import type { Driver } from "../../../lib/drivers";
import {
  CONDITIONS,
  SESSION_KINDS,
  STYLES,
  type CarFormat,
  type CarSetupCatalog,
  type Conditions,
  type SessionKind,
  type SetupStyle,
} from "../../../lib/endpoints/carsetup";
import {
  CONDITIONS_LABEL,
  defaultStyle,
  formatShortLabel,
  SESSION_LABEL,
  servedNote,
  skillPhrase,
  STYLE_HINT,
  STYLE_LABEL,
  trackHasSetup,
  type ResolvedRequest,
} from "../../../lib/setup/carsetup";

export interface RequestChange {
  format?: CarFormat;
  track?: number;
  session?: SessionKind;
  conditions?: Conditions;
  /** null = back to the driver's default */
  style?: SetupStyle | null;
  driver?: number;
}

interface Option {
  id: string;
  text: string;
  hint?: string;
  dim?: boolean;
}

function Choice({ label, value, options, onChange, wide = false }: { label: string; value: string; options: Option[]; onChange: (id: string) => void; wide?: boolean }) {
  return (
    <InlineSelect
      aria-label={label}
      selectedKey={value}
      onSelectionChange={(k: Key | null) => {
        if (k !== null && String(k) !== value) onChange(String(k));
      }}
      className="inline-flex align-baseline"
    >
      <InlineSelect.Trigger className="inline-flex min-h-11 items-center gap-1 px-0.5 text-[length:inherit] font-[650] text-foreground">
        <InlineSelect.Value className="text-[length:inherit] underline decoration-accent/55 decoration-2 underline-offset-[6px]">
          {({ selectedText }) => selectedText}
        </InlineSelect.Value>
        <InlineSelect.Indicator className="size-4 text-muted" />
      </InlineSelect.Trigger>
      <InlineSelect.Popover placement="bottom start" className={wide ? "min-w-72" : "min-w-56"}>
        <ListBox aria-label={label} className="max-h-[60vh] overflow-y-auto">
          {options.map((o) => (
            <ListBox.Item key={o.id} id={o.id} textValue={o.text} className="min-h-12">
              <div className="grid min-w-0">
                <span className={o.dim ? "text-muted" : "font-medium"}>{o.text}</span>
                {o.hint ? <span className="text-xs text-muted">{o.hint}</span> : null}
              </div>
              <ListBox.ItemIndicator />
            </ListBox.Item>
          ))}
        </ListBox>
      </InlineSelect.Popover>
    </InlineSelect>
  );
}

export interface RequestSentenceProps {
  catalog: CarSetupCatalog;
  req: ResolvedRequest;
  /** The style on screen: the explicit one, else what the API chose for the driver. */
  shownStyle: SetupStyle;
  drivers: Driver[];
  driver: Driver | null;
  onChange: (c: RequestChange) => void;
  /** Extra text after the note (e.g. "loading"). */
  aside?: ReactNode;
}

export function RequestSentence({ catalog, req, shownStyle, drivers, driver, onChange, aside }: RequestSentenceProps) {
  const av = catalog.available;
  const format = catalog.formats.find((f) => f.id === req.format) ?? null;
  const q = { car_format: req.format, track_id: req.track, session: req.session, conditions: req.conditions, style: shownStyle };
  const skill = driver?.preferences.skill_level ?? null;
  const auto = defaultStyle(skill);

  const formatOptions: Option[] = catalog.formats.map((f) => ({ id: f.id, text: formatShortLabel(f.id, catalog), hint: f.label }));
  const trackOptions: Option[] = (format?.tracks ?? []).map((t) => {
    const has = trackHasSetup(av, req.format, t.id);
    return { id: String(t.id), text: t.name, hint: has ? undefined : "no setup yet", dim: !has };
  });
  const sessionOptions: Option[] = SESSION_KINDS.map((k) => {
    const note = servedNote(av, { ...q, session: k });
    return { id: k, text: SESSION_LABEL[k], hint: note || undefined, dim: note === "no setup" };
  });
  const conditionOptions: Option[] = CONDITIONS.map((c) => {
    const note = servedNote(av, { ...q, conditions: c });
    return { id: c, text: CONDITIONS_LABEL[c], hint: note || undefined, dim: note === "no setup" };
  });
  const styleOptions: Option[] = STYLES.map((s) => {
    const note = servedNote(av, { ...q, style: s });
    const def = req.style === null && s === auto && driver ? `${driver.name}'s default` : "";
    return { id: s, text: STYLE_LABEL[s], hint: [STYLE_HINT[s], def, note].filter(Boolean).join(" · "), dim: note === "no setup" };
  });

  return (
    <div className="grid gap-1">
      <div role="group" aria-label="Setup request" className="text-2xl leading-[1.6] font-medium">
        Setup for the{" "}
        <Choice label="Car" value={req.format} options={formatOptions} onChange={(id) => onChange({ format: id as CarFormat })} wide /> at{" "}
        <Choice label="Track" value={String(req.track)} options={trackOptions} onChange={(id) => onChange({ track: Number(id) })} />,{" "}
        <Choice label="Session" value={req.session} options={sessionOptions} onChange={(id) => onChange({ session: id as SessionKind })} />,{" "}
        <Choice label="Conditions" value={req.conditions} options={conditionOptions} onChange={(id) => onChange({ conditions: id as Conditions })} />,{" "}
        <Choice label="Style" value={shownStyle} options={styleOptions} onChange={(id) => onChange({ style: id as SetupStyle })} wide />
      </div>
      <div className="flex min-h-11 flex-wrap items-center gap-x-2 text-[15px] text-muted">
        {drivers.length ? (
          <>
            <span>{req.style === null ? "Style chosen for" : "Your choice for"}</span>
            <Choice
              label="Driver"
              value={driver ? String(driver.id) : ""}
              options={drivers.map((d) => ({
                id: String(d.id),
                text: d.name,
                hint: `${d.preferences.skill_level}${d.active ? " · in the seat" : ""}`,
              }))}
              onChange={(id) => onChange({ driver: Number(id) })}
            />
            {req.style === null ? (
              // -ml-2 takes back the row's gap, so the comma sits right after the driver picker ("Alex, an …").
              <span className="-ml-2">{skill ? `, ${skillPhrase(skill)}` : ": skill level not set, balanced"}</span>
            ) : (
              <Button variant="ghost" size="sm" className="min-h-11" onPress={() => onChange({ style: null })}>
                Use {driver ? `${driver.name}'s` : "the"} default ({STYLE_LABEL[auto]})
              </Button>
            )}
          </>
        ) : (
          <span>{req.style === null ? "Balanced until a driver profile exists" : "Your choice"}</span>
        )}
        {aside}
      </div>
    </div>
  );
}
