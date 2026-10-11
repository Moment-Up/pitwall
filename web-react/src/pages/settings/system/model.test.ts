import { describe, expect, it } from "vitest";
import type { Capability, Capture, ServerHealth } from "../../../lib/endpoints/settings";
import { THIN_SPACE } from "../../../lib/format";
import {
  SUPPORT,
  capabilityRows,
  captureView,
  contextText,
  fieldLevels,
  fileName,
  llmHealthView,
  modelName,
  replayRunning,
  replayText,
  simulateNote,
  sizeText,
  sortCaptures,
  supportOf,
  telemetryText,
  udpText,
  workerErrorDetail,
  workerErrors,
} from "./model";

// GET /api/health on the live server (2026-10-11, no telemetry).
const HEALTH: ServerHealth = {
  version: "0.1.0",
  time: 1791681921.59,
  connection: {
    status: "no_data",
    last_packet_age_s: null,
    packets: 0,
    packets_per_s: 0,
    rejected: 0,
    unrecognised: 0,
    source: null,
    synthetic: false,
    decode: {},
  },
  udp_port: 20777,
  replay: null,
  db_writer_errors: 0,
  analysis_errors: 0,
  laps_processed: 0,
};

describe("capabilities", () => {
  it("only the two validated tiers are green; strength order is the server's", () => {
    const green = Object.entries(SUPPORT).filter(([, v]) => v.tone === "success").map(([k]) => k);
    expect(green).toEqual(["live_validated", "recorded_validated"]);
    const order = Object.entries(SUPPORT)
      .sort((a, b) => a[1].rank - b[1].rank)
      .map(([k]) => k);
    expect(order).toEqual([
      "live_validated",
      "recorded_validated",
      "spec_implemented",
      "community_documented",
      "partial",
      "unverified",
      "unsupported",
    ]);
  });

  it("an unknown status is shown in its own words, never as working", () => {
    expect(supportOf("lab_validated")).toEqual({ label: "Lab validated", tone: "default", evidence: "-", rank: 99 });
  });

  it("rows keep the server's order with unique ids; field levels are counted strongest first", () => {
    const caps: Capability[] = [
      {
        game: "F1 25 (UDP format 2025)",
        platform: "PS5",
        transport: "UDP 20777",
        status: "live_validated",
        implemented: true,
        notes: "",
        fields: {
          speed_kph: { level: "spec_implemented", source: "CarTelemetry.speed" },
          lap_time_ms: { level: "recorded_validated", source: "LapData" },
          throttle: { level: "spec_implemented", source: "CarTelemetry.throttle" },
          tyre_wear_pct: { level: "unsupported", source: "-" },
        },
      },
      { game: "F1 25 (UDP format 2025)", platform: "PC / Xbox Series", transport: "UDP", status: "spec_implemented", implemented: true, notes: "", fields: null },
    ];
    const rows = capabilityRows(caps);
    expect(rows.map((r) => r.id)).toEqual(["0:F1 25 (UDP format 2025)|PS5", "1:F1 25 (UDP format 2025)|PC / Xbox Series"]);
    expect(rows[0]?.support.label).toBe("Live validated");
    expect(rows[0]?.fieldCount).toBe(4);
    expect(fieldLevels(caps[0]!)).toEqual([
      ["Recorded validated", 1],
      ["Spec implemented", 2],
      ["Unsupported", 1],
    ]);
    expect(fieldLevels(caps[1]!)).toEqual([]);
  });
});

describe("captures", () => {
  const cap = (name: string, synthetic = false, size = 37_178_175): Capture => ({
    path: `/Users/x/pitwall/data/captures/${name}`,
    name,
    size_bytes: size,
    synthetic,
    description: synthetic ? "SYNTHETIC F1 25 packet stream" : "live capture",
    created_unix: 1_000_000,
  });

  it("sizes", () => {
    expect(sizeText(240)).toBe("240 B");
    expect(sizeText(8074)).toBe("8 KB");
    expect(sizeText(37_178_175)).toBe("35.5 MB");
    expect(sizeText(null)).toBe("-");
    expect(sizeText(-1)).toBe("-");
  });

  it("a row says what, how big and how long ago", () => {
    expect(captureView(cap("20261011-011513_udp20777.pwcap"), 1_000_000 + 2 * 3600 + 5).detail).toBe("live capture · 35.5 MB · 2 h ago");
    expect(captureView(cap("a.pwcap"), 1_000_030).detail).toBe("live capture · 35.5 MB · just now");
    expect(captureView({ ...cap("b.pwcap"), created_unix: 0, description: "" }).detail).toBe("capture · 35.5 MB · -");
  });

  it("synthetic demos first, the rest in the server's (newest first) order", () => {
    const list = [cap("3.pwcap"), cap("2.pwcap"), cap("demo.pwcap", true), cap("1.pwcap")];
    expect(sortCaptures(list).map((c) => c.name)).toEqual(["demo.pwcap", "3.pwcap", "2.pwcap", "1.pwcap"]);
  });

  it("file names from server paths", () => {
    expect(fileName("/Users/x/data/captures/synthetic-coaching-demo-2025.pwcap")).toBe("synthetic-coaching-demo-2025.pwcap");
    expect(fileName("C:\\data\\a.pwcap")).toBe("a.pwcap");
  });

  it("the demo note always says SYNTHETIC", () => {
    expect(simulateNote("/d/synthetic-coaching-demo-2026.pwcap")).toMatch(/^Wrote synthetic-coaching-demo-2026\.pwcap\. It is SYNTHETIC/);
  });
});

describe("health", () => {
  it("worker errors add analysis and database", () => {
    expect(workerErrors(null)).toBeNull();
    expect(workerErrors({ ...HEALTH, analysis_errors: 2, db_writer_errors: 1 })).toBe(3);
    expect(workerErrorDetail({ ...HEALTH, analysis_errors: 2 })).toBe("2 analysis · 0 database");
  });

  it("telemetry and the UDP listener in words", () => {
    expect(telemetryText(HEALTH)).toBe("No data · 0 packets · 0 rejected");
    expect(telemetryText({ ...HEALTH, connection: { ...HEALTH.connection, status: "live", packets: 190_312 } })).toBe(
      `Live · 190${THIN_SPACE}312 packets · 0 rejected`,
    );
    expect(udpText(HEALTH)).toBe("Port 20777");
    expect(udpText({ ...HEALTH, udp_port: null })).toBe("Off");
  });

  it("replay status", () => {
    expect(replayText(null)).toBeNull();
    const r = { path: "/d/captures/a.pwcap", sent: 1200, done: false, speed: 4, synthetic: false };
    expect(replayText(r)).toBe(`a.pwcap · 4× · 1${THIN_SPACE}200 packets`);
    expect(replayText({ ...r, speed: null, done: true })).toBe(`a.pwcap · max speed · 1${THIN_SPACE}200 packets · done`);
    expect(replayRunning(r)).toBe(true);
    expect(replayRunning({ ...r, done: true })).toBe(false);
    expect(replayRunning(null)).toBe(false);
  });

  it("local LLM chip", () => {
    const ok = {
      ok: true,
      base_url: "http://127.0.0.1:8081/v1",
      model: "/Users/x/models/Qwen3.8-27B-UD-Q4_K_XL.gguf",
      detail: "ok",
      latency_ms: 9,
      context_tokens: 32768,
      breaker_open: false,
    };
    expect(llmHealthView(ok)).toEqual({ tone: "success", label: "Ready · 9 ms", detail: "ok" });
    expect(llmHealthView({ ...ok, latency_ms: null }).label).toBe("Ready");
    expect(llmHealthView({ ...ok, ok: false, detail: "connection refused" })).toEqual({
      tone: "danger",
      label: "Offline",
      detail: "connection refused",
    });
    expect(llmHealthView(null, "HTTP 502")).toEqual({ tone: "danger", label: "Unreachable", detail: "HTTP 502" });
    expect(llmHealthView(undefined)).toEqual({ tone: "default", label: "-", detail: "" });
    expect(modelName(ok.model)).toBe("Qwen3.8-27B-UD-Q4_K_XL.gguf");
    expect(modelName(null)).toBe("-");
    expect(contextText(32768)).toBe(`32${THIN_SPACE}768 tokens`);
    expect(contextText(null)).toBe("-");
  });
});
