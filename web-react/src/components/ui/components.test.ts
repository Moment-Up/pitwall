// Render tests for the UI kit (server-rendered to static markup in plain node: no DOM library needed).
import { createElement, type ComponentType } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MINUS } from "../../lib/format";
import {
  CopyField,
  CornerTag,
  EvidenceChips,
  Glossary,
  RangeMarker,
  SettingValue,
  TimingCell,
  TimingLegend,
  TimingTag,
  TimingValue,
  Unknown,
} from "./index";

function html<P extends object>(c: ComponentType<P>, props: P): string {
  return renderToStaticMarkup(createElement(c as ComponentType<object>, props));
}

/** Text a sighted user sees: tags stripped, visually hidden (sr-only) spans removed. */
function visible(markup: string): string {
  return markup
    .replace(/<span class="sr-only">[^<]*<\/span>/g, "")
    .replace(/<[^>]+>/g, "")
    .trim();
}

describe("Unknown", () => {
  it("shows '-' in the faint style and reads 'unknown'", () => {
    const m = html(Unknown, {});
    expect(m).toContain('class="pw-unknown"');
    expect(m).toContain('<span aria-hidden="true">-</span>');
    expect(m).toContain('<span class="sr-only">unknown</span>');
    expect(visible(m)).toBe("-");
    expect(html(Unknown, { label: "no reference yet" })).toContain("no reference yet");
  });
});

describe("TimingValue", () => {
  it("renders a lap time with its status and size", () => {
    const m = html(TimingValue, { ms: 90_986, kind: "lap", status: "sb", size: "d-m" });
    expect(visible(m)).toBe("1:30.986");
    expect(m).toContain('data-status="sb"');
    expect(m).toContain("font-size:var(--pw-d-m)");
    expect(m).toContain('data-context="inline"');
  });

  it("renders unknown as '-' (never 0.000 or --:--.---), keeping the size", () => {
    for (const ms of [null, undefined, Number.NaN, 0]) {
      const m = html(TimingValue, { ms, kind: "lap", size: "kpi" });
      expect(visible(m)).toBe("-");
      expect(m).toContain("pw-unknown");
      expect(m).toContain("font-size:32px");
      expect(m).not.toContain("0.000");
    }
  });

  it("draws the delta minus narrowed, coloured by tone with a 0.02 s level band", () => {
    const ahead = html(TimingValue, { ms: -210, kind: "delta", size: "d-delta" });
    expect(ahead).toContain(`<span class="pw-minus">${MINUS}</span>0.21`);
    expect(ahead).toContain('data-tone="ahead"');
    expect(ahead).not.toContain("data-status");
    expect(html(TimingValue, { ms: 530, kind: "delta" })).toContain('data-tone="behind"');
    expect(html(TimingValue, { ms: 15, kind: "delta" })).toContain('data-tone="level"');
    expect(html(TimingValue, { ms: 530, kind: "delta", tone: "muted" })).toContain('data-tone="muted"');
  });

  it("shows tenths while running and marks table context and dimming", () => {
    expect(visible(html(TimingValue, { ms: 69_549, kind: "lap", running: true }))).toBe("1:09.5");
    const m = html(TimingValue, { ms: 91_512, kind: "lap", status: "slower", context: "table", dim: true });
    expect(m).toContain('data-context="table"');
    expect(m).toContain('data-dim=""');
    expect(html(TimingValue, { ms: 1, kind: "lap", "aria-label": "Last lap" })).toContain('aria-label="Last lap"');
  });
});

describe("TimingTag", () => {
  it("renders REC / PB / SB / INV with the meaning for screen readers", () => {
    const m = html(TimingTag, { status: "rec" });
    expect(visible(m)).toBe("REC");
    expect(m).toContain(", family record");
    expect(m).toContain('data-status="rec"');
    expect(m).toContain('data-slot="chip"');
    expect(visible(html(TimingTag, { status: "invalid" }))).toBe("INV");
  });

  it("renders nothing for slower, neutral, running and unknown", () => {
    for (const status of ["slower", "neutral", "running", "future", null, undefined] as const) {
      expect(html(TimingTag, { status })).toBe("");
    }
  });

  it("can be decorative (legend) and sized", () => {
    const m = html(TimingTag, { status: "pb", decorative: true, size: "lg" });
    expect(m).not.toContain("sr-only");
    expect(m).toContain('data-size="lg"');
  });
});

describe("TimingCell", () => {
  it("shows label, tag, value and the sub line with a narrow minus", () => {
    const m = html(TimingCell, { label: "S1", value: "29.318", status: "sb", sub: `${MINUS}0.023 on today's best` });
    expect(m).toContain('data-status="sb"');
    expect(m).toContain('data-size="drive"');
    expect(m).toContain('data-slot="card"');
    expect(m).toContain(">S1<");
    expect(m).toContain("29.318");
    expect(m).toContain(`<span class="pw-minus">${MINUS}</span>0.023 on today`);
    expect(visible(m)).toContain("SB");
  });

  it("running: progress bar instead of the sub line, no tag", () => {
    const m = html(TimingCell, { label: "S3", value: "12.4", status: "running", progress: 0.42, sub: "ignored" });
    expect(m).toContain('role="progressbar"');
    expect(m).toContain('aria-valuenow="42"');
    expect(m).toContain('aria-label="S3 progress"');
    expect(m).toContain("running");
    expect(m).not.toContain("ignored");
    expect(m).not.toContain("pw-ttag");
  });

  it("future and unknown values show '-'; tag can be turned off; last-lap values dim with a caption", () => {
    expect(visible(html(TimingCell, { label: "S3", value: null, status: "future" }))).toContain("-");
    expect(html(TimingCell, { label: "S2", value: "-", status: "neutral" })).toContain("pw-unknown");
    expect(html(TimingCell, { label: "S2", value: "36.904", status: "rec", tag: false })).not.toContain("pw-ttag");
    const last = html(TimingCell, { label: "S1", caption: "last lap · L6", value: "29.341", status: "sb", dim: true });
    expect(last).toContain('data-dim=""');
    expect(last).toContain("last lap · L6");
  });

  it("clamps progress and drops it when unknown", () => {
    expect(html(TimingCell, { label: "S3", value: "1.0", status: "running", progress: 3 })).toContain(
      'aria-valuenow="100"',
    );
    expect(html(TimingCell, { label: "S3", value: "1.0", status: "running", progress: null })).not.toContain(
      "progressbar",
    );
  });
});

describe("TimingLegend", () => {
  it("before D2 explains SB only: purple and PB never appear", () => {
    const m = visible(html(TimingLegend, { tier: 1 }));
    expect(m).toContain("SB");
    expect(m).toContain("your best today");
    expect(m).not.toContain("REC");
    expect(m).not.toContain("PB");
  });

  it("with D2: REC family record · PB your best ever · SB your best today", () => {
    const m = visible(html(TimingLegend, { tier: 2 }));
    expect(m.replace(/\s+/g, " ")).toBe("RECfamily recordPByour best everSByour best today".replace(/\s+/g, " "));
    const ext = visible(html(TimingLegend, { tier: 2, extended: true }));
    expect(ext).toContain("Yellow: slower than your best today");
    expect(ext).toContain("INV");
  });

  it("on Review (scope session) SB is the best of the session shown, not of today", () => {
    const m = visible(html(TimingLegend, { tier: 2, scope: "session" }));
    expect(m).toContain("your best this session");
    expect(m).not.toContain("today");
  });
});

describe("EvidenceChips", () => {
  it("renders nothing for live game data", () => {
    expect(html(EvidenceChips, { synthetic: false, source: "udp:192.168.1.100" })).toBe("");
    expect(html(EvidenceChips, {})).toBe("");
  });

  it("SYNTHETIC is hatched pink; REPLAY comes from the flag or the source", () => {
    const syn = html(EvidenceChips, { synthetic: true });
    expect(visible(syn)).toBe("SYNTHETIC");
    expect(syn).toContain("pw-hatch-synthetic");
    expect(syn).toContain("generated data, not from a game");
    expect(visible(html(EvidenceChips, { source: "replay:captures/x.pwcap" }))).toBe("REPLAY");
    expect(visible(html(EvidenceChips, { synthetic: true, replay: true }))).toBe("SYNTHETICREPLAY");
  });
});

describe("CornerTag", () => {
  it("label in bold, the official name, FOCUS as a word", () => {
    const m = html(CornerTag, { label: "T15", name: "Stowe", focus: true });
    expect(m).toContain('<b class="pw-corner__label">T15</b>');
    expect(m).toContain("Stowe");
    expect(m).toContain("data-focus");
    expect(visible(m)).toBe("T15StoweFOCUS");
  });

  it("no official name: label only; no label: '-'", () => {
    expect(visible(html(CornerTag, { label: "T10-13", name: null }))).toBe("T10-13");
    const m = html(CornerTag, { label: null });
    expect(visible(m)).toBe("-");
    expect(m).toContain("corner unknown");
  });
});

describe("Glossary", () => {
  it("is a 44 px icon button with a spoken question; the popover stays closed until tapped", () => {
    const m = html(Glossary, { term: "clean_lap" });
    expect(m).toContain("<button");
    expect(m).toContain('aria-label="What is clean lap?"');
    expect(m).toContain("pw-gloss");
    expect(m).toContain('aria-expanded="false"');
    expect(m).not.toContain("A lap that counts");
    expect(html(Glossary, { term: "household_record" })).toContain('aria-label="What is family record?"');
    expect(html(Glossary, { term: "delta", label: "Explain delta" })).toContain('aria-label="Explain delta"');
  });
});

describe("SettingValue", () => {
  it("shows the value with a real narrowed minus and its unit", () => {
    const m = html(SettingValue, { value: "-3.50", unit: "°", size: "row" });
    expect(m).toContain(`<span class="pw-minus">${MINUS}</span>3.50`);
    expect(m).toContain('<small class="pw-setting__unit">°</small>');
    expect(m).toContain('data-size="row"');
    expect(html(SettingValue, { value: 78, unit: "%", size: "step" })).toContain('data-size="step"');
    expect(html(SettingValue, { value: 18, size: 40 })).toContain("font-size:40px");
  });

  it("unknown -> '-' without a unit", () => {
    const m = html(SettingValue, { value: null, unit: "%" });
    expect(visible(m)).toBe("-");
    expect(m).not.toContain("pw-setting__unit");
  });
});

describe("RangeMarker", () => {
  it("draws spread and marker and describes them", () => {
    const m = html(RangeMarker, { min: 0, max: 50, value: 22, spread: [18, 26], label: "Front wing aero" });
    expect(m).toContain('role="img"');
    expect(m).toContain('aria-label="Front wing aero: 22 on a range of 0 to 50; sources 18 to 26"');
    expect(m).toContain("--pw-range-v:44%");
    expect(m).toContain("--pw-range-a:36%");
    expect(m).toContain("--pw-range-w:16%");
    expect(m).toContain('class="pw-range__min" aria-hidden="true">0<');
  });

  it("marks values outside the range and hides the ends on request", () => {
    const m = html(RangeMarker, { min: 0, max: 50, value: 60, showEnds: false });
    expect(m).toContain('data-outside="above"');
    expect(m).not.toContain("pw-range__min");
  });

  it("an unknown range is '-'", () => {
    const m = html(RangeMarker, { min: 1, max: 1, value: 1, label: "Rear wing" });
    expect(visible(m)).toBe("-");
    expect(m).toContain("Rear wing: range unknown");
  });
});

describe("CopyField", () => {
  it("shows the label, the monospace value and a named 44 px Copy button", () => {
    const m = html(CopyField, { value: "https://studio.example.ts.net:8443/", label: "Tailscale HTTPS URL" });
    expect(m).toContain('class="pw-copy__label">Tailscale HTTPS URL<');
    expect(m).toContain('class="pw-copy__value" data-mono="">https://studio.example.ts.net:8443/<');
    expect(m).toContain('aria-label="Copy Tailscale HTTPS URL"');
    expect(m).toContain("pw-copy__button");
    expect(m).toContain('role="status"');
    expect(visible(m)).toContain("Copy");
  });

  it("unknown value: '-' and a disabled button; numbers are shown as text; label can be hidden", () => {
    const m = html(CopyField, { value: null, label: "IP address" });
    expect(m).toContain("pw-unknown");
    expect(m).toMatch(/<button[^>]*disabled/);
    expect(html(CopyField, { value: 20777, label: "Port" })).toContain(">20777<");
    expect(html(CopyField, { value: "x", label: "Token URL", labelHidden: true, mono: false })).toContain(
      '<span class="sr-only">Token URL</span>',
    );
  });
});
