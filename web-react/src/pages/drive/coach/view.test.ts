// Pure helpers of the Coach panels: content equality (memoised panels), bar geometry, the no-telemetry steps.
import { describe, expect, it } from "vitest";
import { barStep, cellCaption, deltaFills, deltaScale, heroText, noTelemetryView, pct, radioSeat, sameView } from "./view";

describe("sameView", () => {
  it("compares plain view models by content", () => {
    expect(sameView({ a: 1, b: ["x", { c: null }] }, { a: 1, b: ["x", { c: null }] })).toBe(true);
    expect(sameView({ a: 1 }, { a: 2 })).toBe(false);
    expect(sameView({ a: 1 }, { a: 1, b: undefined })).toBe(false);
    expect(sameView([1, 2], [1, 2, 3])).toBe(false);
    expect(sameView([1], { 0: 1 })).toBe(false);
    expect(sameView(Number.NaN, Number.NaN)).toBe(true);
    expect(sameView(null, {})).toBe(false);
  });
});

describe("geometry", () => {
  it("pct clamps and keeps three decimals", () => {
    expect(pct(0.453219)).toBe("45.322%");
    expect(pct(-1)).toBe("0%");
    expect(pct(2)).toBe("100%");
    expect(pct(Number.NaN)).toBe("0%");
  });

  it("deltaFills: one half-fill from the centre, ahead to the left", () => {
    expect(deltaFills(-0.21)).toEqual({ ahead: 0.21, behind: 0 });
    expect(deltaFills(0.53)).toEqual({ ahead: 0, behind: 0.53 });
    expect(deltaFills(-3)).toEqual({ ahead: 1, behind: 0 });
    expect(deltaFills(0)).toEqual({ ahead: 0, behind: 0 });
  });

  it("deltaScale: end labels only when unknown", () => {
    expect(deltaScale({ tone: "unknown" })).toEqual(["◀ ahead", "behind ▶"]);
    expect(deltaScale({ tone: "ahead" })).toEqual(["◀ ahead · 1.0", "0", "1.0 · behind ▶"]);
  });

  it("barStep rounds to 0.5 % steps and keeps unknown as null", () => {
    expect(barStep(0.1234)).toBe(0.125);
    expect(barStep(1.4)).toBe(1);
    expect(barStep(null)).toBeNull();
    expect(barStep(Number.NaN)).toBeNull();
  });
});

describe("texts", () => {
  it("cellCaption lower-cases the panel caption for the cell label", () => {
    expect(cellCaption("Last lap · L6")).toBe("last lap · L6");
    expect(cellCaption(null)).toBeNull();
  });

  it("heroText drops the per-frame fields of a corner hero only", () => {
    const corner = {
      kind: "corner" as const,
      head: "Next corner" as const,
      label: "T15",
      name: "Stowe",
      layout: "one" as const,
      direction: "right" as const,
      distanceText: "320 m",
      approach: 0.2,
      focus: true,
      focusReason: null,
      frozen: false,
      corner: {} as never,
      aria: "Next corner, T15, Stowe, 320 m",
    };
    const t = heroText(corner);
    expect("corner" in t).toBe(false);
    expect("approach" in t).toBe(false);
    expect(t).toMatchObject({ label: "T15", distanceText: "320 m" });
    const pit = { kind: "pit" as const, label: "PIT" as const, speedText: "78", limitText: "80", over: false, aria: "" };
    expect(heroText(pit)).toBe(pit);
  });

  it("radioSeat: Off, Live · mic OK, or the mic's state", () => {
    expect(radioSeat("idle", "off", "Radio off")).toEqual({ text: "Off", tone: "default" });
    expect(radioSeat("live", "live", "Mic live")).toEqual({ text: "Live · mic OK", tone: "success" });
    expect(radioSeat("live", "denied", "Mic blocked")).toEqual({ text: "Live · Mic blocked", tone: "warning" });
  });
});

describe("noTelemetryView", () => {
  const connect = {
    mac: { lan_ip: "192.0.2.10", udp_port: 20777 },
    udp: { listening: true, port: 20777, received: 0, sources: [] },
    guides: [
      {
        id: "f1_25",
        game: "EA SPORTS F1 25",
        supported: true,
        menu_path: "Settings > Telemetry Settings",
        steps: [
          { label: "UDP Telemetry", value: "On" },
          { label: "UDP Format", value: "2025" },
        ],
      },
    ],
    telemetry: { hint: null },
  };

  it("builds the three steps from /api/connect (the game's own menu words, this Mac's IP and port)", () => {
    const v = noTelemetryView(connect);
    expect(v.steps[0].description).toBe("Settings › Telemetry Settings › UDP Telemetry: On, UDP Format 2025");
    expect(v.steps[1].title).toBe("IP 192.0.2.10 · port 20777");
    expect(v.steps[2].description).toBe("Last sender seen: none");
    expect(v.current).toBe(0);
    expect(v.listening).toBe("Listening on UDP 20777");
    expect(v.hint).toBeNull();
  });

  it("moves to the last step once a sender has been seen, and passes the server's hint verbatim", () => {
    const v = noTelemetryView({
      ...connect,
      udp: { ...connect.udp, sources: [{ ip: "192.168.1.100", port: 50000, packets: 9, last_seen_s: 3.2 }] },
      telemetry: { hint: "Packets arrived that aren't F1 25 telemetry" },
    });
    expect(v.current).toBe(2);
    expect(v.steps[2].description).toBe("Last sender seen: 192.168.1.100 · 3 s ago");
    expect(v.hint).toBe("Packets arrived that aren't F1 25 telemetry");
  });

  it("never invents an address: unknown values are '-'", () => {
    const v = noTelemetryView(undefined);
    expect(v.steps[0].description).toBe("In the game's telemetry settings");
    expect(v.steps[1].title).toBe("IP - · port -");
    expect(v.listening).toBeNull();
    expect(noTelemetryView({ mac: { lan_ip: "<this Mac's IP>" } }).steps[1].title).toBe("IP - · port -");
  });
});
