// Pure helpers of the Coach panels: content equality (memoised panels), bar geometry, the no-telemetry steps.
import { describe, expect, it } from "vitest";
import { catalogue, entry } from "../../../lib/game-testkit";
import {
  barStep,
  cellCaption,
  coachGameView,
  deltaFills,
  deltaScale,
  estimatedDelta,
  heroText,
  NO_COACH_GAME,
  noTelemetryGame,
  noTelemetryView,
  pct,
  radioSeat,
  sameView,
} from "./view";

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

describe("noTelemetryView with a selected game (game selection 5.3 #2)", () => {
  const CAT = catalogue();
  const guides = [
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
    {
      id: "gt7",
      game: "Gran Turismo 7",
      supported: true,
      menu_path: "No in-game setting: pitwall asks the console for telemetry (heartbeat to UDP 33739)",
      steps: [
        { label: "Connect page > Gran Turismo 7", value: "Enable", note: "pitwall starts listening on UDP 33740" },
        { label: "Console IP", value: "your PS5's IP address", note: "PS5 Settings > Network > Connection Status" },
        { label: "Packet variant", value: "C" },
      ],
    },
    {
      id: "forza",
      game: "Forza",
      supported: true,
      menu_path: "Settings > Gameplay & HUD > UDP Race Telemetry",
      steps: [
        { label: "Connect page > Forza", value: "Enable" },
        { label: "Data Out", value: "On" },
        { label: "Data Out IP Address", value: "192.0.2.10" },
      ],
    },
    {
      id: "ac",
      game: "Assetto Corsa",
      supported: true,
      menu_path: "No in-game setting: pitwall asks the game for telemetry (handshake to UDP 9996)",
      steps: [
        { label: "Connect page > Assetto Corsa", value: "Enable", note: "nothing to change in the game's menus" },
        { label: "Console IP", value: "your PS5's IP address", note: "PS5 Settings > Network > Connection Status" },
      ],
    },
  ];
  const base = {
    mac: { lan_ip: "192.0.2.10", udp_port: 20777 },
    udp: { listening: true, port: 20777, received: 0, sources: [] },
    guides,
    telemetry: { hint: null },
  };

  it("no selection: the first supported guide (F1 25), as before", () => {
    expect(noTelemetryView(base).steps[0].description).toBe("Settings › Telemetry Settings › UDP Telemetry: On, UDP Format 2025");
    expect(noTelemetryGame(null)).toBeNull();
  });

  it("F1 25 Season Pack: the format step asks for 2026", () => {
    const v = noTelemetryView(base, noTelemetryGame(entry("f1_25_2026:ps5", CAT)));
    expect(v.steps[0].description).toBe("Settings › Telemetry Settings › UDP Telemetry: On, UDP Format 2026");
    expect(v.steps[1].title).toBe("IP 192.0.2.10 · port 20777");
  });

  it("GT7: the input, the console IP (no port: it can't be changed), get on track", () => {
    const off = noTelemetryView(
      { ...base, integrations: [{ key: "gt7", enabled: false, listening: false, console_ip: null, sources: [] }] },
      noTelemetryGame(entry("gt7:ps5", CAT)),
    );
    expect(off.steps.map((x) => x.title)).toEqual(["Switch the GT7 input on", "Enter the console's IP address", "Get on track"]);
    expect(off.steps[0].description).toBe("Entering the console's IP switches it on, or let Pitwall search the network (Setup › Game)");
    expect(off.steps[1]).toMatchObject({ mono: false, description: "On Setup › Game. PS5 Settings › Network › Connection Status" });
    expect(off.needsIp).toBe(true); // nothing can arrive: the card leads with the IP
    expect(off.current).toBe(0);
    expect(off.listening).toBeNull(); // GT7's input is off: nothing listens on 33740
    const searching = noTelemetryView(
      { ...base, integrations: [{ key: "gt7", enabled: true, listening: true, console_ip: null, sources: [] }] },
      noTelemetryGame(entry("gt7:ps5", CAT)),
    );
    expect(searching.steps[0]).toMatchObject({ title: "GT7 input on", description: "Pitwall starts listening on UDP 33740" });
    expect(searching.steps[1].title).toBe("Console IP not set: Pitwall searches the network");
    expect(searching.needsIp).toBe(false);
    const on = noTelemetryView(
      {
        ...base,
        integrations: [
          {
            key: "gt7",
            enabled: true,
            listening: true,
            console_ip: "192.168.1.100",
            sources: [{ ip: "192.168.1.100", port: 33739, packets: 3, last_seen_s: 4 }],
          },
        ],
      },
      noTelemetryGame(entry("gt7:ps5", CAT)),
    );
    expect(on.steps[0].title).toBe("GT7 input on");
    expect(on.steps[1].title).toBe("Console IP 192.168.1.100");
    expect(on.steps[1].parts).toEqual([
      { text: "Console IP ", mono: false },
      { text: "192.168.1.100", mono: true }, // only the value in the mono face
    ]);
    expect(on.steps[2].description).toBe("Last sender seen: 192.168.1.100 · 4 s ago");
    expect(on.current).toBe(2);
    expect(on.listening).toBe("Listening on UDP 33740");
  });

  it("Assetto Corsa: no port (Pitwall contacts the console), the client's last packet", () => {
    const v = noTelemetryView(
      { ...base, integrations: [{ key: "ac", enabled: true, listening: false, console_ip: null, sources: [], client: { last_rx_s_ago: null } }] },
      noTelemetryGame(entry("ac:ps5", CAT)),
    );
    expect(v.steps[0].title).toBe("Assetto Corsa input on");
    expect(v.steps[1]).toMatchObject({ title: "Enter the console's IP address", mono: false });
    expect(v.steps[1].description).toBe("On Setup › Game. PS5 Settings › Network › Connection Status");
    expect(v.steps[2]).toEqual({ title: "Get on track", description: "Last sender seen: none", mono: false });
    expect(v.needsIp).toBe(true);
    expect(v.current).toBe(1);
    expect(v.listening).toBeNull();
    const rx = noTelemetryView(
      { ...base, integrations: [{ key: "ac", enabled: true, console_ip: "192.168.1.50", sources: [], client: { last_rx_s_ago: 12 } }] },
      noTelemetryGame(entry("ac:ps5", CAT)),
    );
    expect(rx.steps[2].description).toBe("Last packet: 12 s ago");
    expect(rx.current).toBe(2);
  });

  it("Forza: Data Out in the game, its own port, its own senders", () => {
    const v = noTelemetryView(
      { ...base, integrations: [{ key: "forza", enabled: true, listening: true, sources: [] }] },
      noTelemetryGame(entry("forza_motorsport:pc", CAT)),
    );
    expect(v.steps[0].title).toBe("Turn on Data Out in the game");
    expect(v.steps[0].description).toBe("Settings › Gameplay & HUD › UDP Race Telemetry › Data Out: On");
    expect(v.steps[1].title).toBe("IP 192.0.2.10 · port 5301");
    expect(v.listening).toBe("Listening on UDP 5301");
  });
});

describe("what the game changes on Coach (game selection 5.3 #3, #4)", () => {
  const CAT = catalogue();
  it("GT7: one muted sector cell with the server's words, the delta marked estimated", () => {
    expect(coachGameView(entry("gt7:ps5", CAT))).toEqual({ sectors: "Sectors · Not sent by GT7", deltaEstimated: true });
    expect(coachGameView(entry("ac:ps5", CAT))).toEqual({ sectors: "Sectors · Not sent by Assetto Corsa", deltaEstimated: true });
  });

  it("F1 25 and unknown games: Coach as before", () => {
    expect(coachGameView(entry("f1_25:ps5", CAT))).toEqual(NO_COACH_GAME);
    expect(coachGameView(entry("other:any", CAT))).toEqual(NO_COACH_GAME); // unknown: the three '-' cells stay
    expect(coachGameView(null)).toEqual(NO_COACH_GAME);
  });

  it("the delta header gains '· estimated' and nothing else changes", () => {
    const d = { label: "Delta to reference", text: "−0.21" };
    expect(estimatedDelta(d, true)).toEqual({ label: "Delta to reference · estimated", text: "−0.21" });
    expect(estimatedDelta(d, false)).toBe(d);
    expect(estimatedDelta({ label: "vs your target lap" }, true).label).toBe("vs your target lap · estimated");
  });
});
