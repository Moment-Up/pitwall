import { describe, expect, it } from "vitest";
import type { Integration } from "../endpoints/connect";
import {
  acSummary,
  ago,
  captureName,
  cardState,
  consoleIpLabel,
  decodedPackets,
  draftDirty,
  DRIVE_OUT_STEP,
  draftFrom,
  evidenceOfStatus,
  gameText,
  guideById,
  guideFor,
  guideStep,
  guideSteps,
  guideText,
  lastDecodeError,
  orderedIntegrations,
  senderRows,
  senderSummary,
  statusDetail,
  statusLine,
  updateFromDraft,
} from "./connect";
import { fixtures } from "./fixtures";

const integ = (key: string) => {
  const g = fixtures.connectNoData().integrations.find((x) => x.key === key);
  if (!g) throw new Error(key);
  return g;
};

describe("recorded fixtures", () => {
  it("never carry the access token or private host names", () => {
    const raw = JSON.stringify([fixtures.connectNoData(), fixtures.connectF1Live()]);
    expect(raw).not.toMatch(/token=(?!REDACTED)/);
    expect(fixtures.connectNoData().urls.lan_with_token.endsWith("?token=REDACTED")).toBe(true);
    expect(fixtures.meta("connect-f1-live-edited").edited?.length).toBeGreaterThan(0);
  });

  it("list the five integrations in the server's order", () => {
    expect(fixtures.connectNoData().integrations.map((g) => g.key)).toEqual(["f1", "gt7", "forza", "ac", "record"]);
  });
});

describe("status", () => {
  it("ago", () => {
    expect(ago(null)).toBe("never");
    expect(ago(0.4)).toBe("now");
    expect(ago(6.2)).toBe("6 s ago");
    expect(ago(125)).toBe("2 min ago");
    expect(ago(7300)).toBe("2 h ago");
  });

  it("statusLine: waiting, live and stale", () => {
    expect(statusLine(fixtures.connectNoData())).toBe("Listening on UDP 20777, waiting for the game");
    const live = fixtures.connectF1Live();
    expect(statusLine(live)).toBe("Receiving F1 25 (format 2025) from 192.168.1.100 · 61 packets/s");
    expect(statusDetail(live)).toBe("Silverstone · Practice · PS5 · game v1.26");
    live.telemetry.status = "stale";
    live.telemetry.last_packet_age_s = 8;
    expect(statusLine(live)).toBe("Last packet 8 s ago from 192.168.1.100: is the game paused or in a menu?");
    const off = fixtures.connectNoData();
    off.udp.listening = false;
    expect(statusLine(off)).toBe("Not listening on UDP 20777");
    expect(statusDetail(off)).toBe("");
  });

  it("gameText", () => {
    expect(gameText("f1_25")).toBe("F1 25");
    expect(gameText(null)).toBe("telemetry");
  });
});

describe("game cards", () => {
  it("senderSummary for each state", () => {
    expect(senderSummary(integ("forza"))).toBe("Off");
    expect(senderSummary(integ("f1"))).toBe("Listening on UDP 20777, waiting for the game");
    const f1 = fixtures.connectF1Live().integrations.find((g) => g.key === "f1")!;
    expect(senderSummary(f1)).toBe("Receiving from 192.168.1.100 · 61/s");
    f1.sources[0]!.last_seen_s = 30;
    expect(senderSummary(f1)).toBe("48,210 packets so far · idle");
  });

  it("acSummary follows the client's state", () => {
    expect(acSummary(integ("ac"))).toBe("Off");
    const ac = fixtures.connectF1Live().integrations.find((g) => g.key === "ac")!;
    expect(acSummary(ac)).toMatch(/^192\.168\.1\.50 refused \(3 sent\): not in a session yet/);
    ac.client!.state = "streaming";
    ac.client!.rate = 59.6;
    expect(acSummary(ac)).toBe("Streaming from 192.168.1.50 · 60/s");
    ac.client!.state = "handshaking";
    expect(acSummary(ac)).toBe("Asking 192.168.1.50:9996 for telemetry: get on track (3 sent, no answer yet)");
    ac.client = null;
    expect(acSummary(ac)).toBe("Enter the console's IP address, then get on track");
  });

  it("cardState: receiving only while packets arrive", () => {
    expect(cardState(integ("forza"))).toBe("off");
    expect(cardState(integ("gt7"))).toBe("waiting");
    const live = fixtures.connectF1Live().integrations;
    expect(cardState(live.find((g) => g.key === "f1")!)).toBe("receiving");
    expect(cardState(live.find((g) => g.key === "ac")!)).toBe("problem");
    const withError: Integration = { ...integ("gt7"), error: "port in use" };
    expect(cardState(withError)).toBe("problem");
  });

  it("evidence in words, never upgraded", () => {
    expect(evidenceOfStatus("live_validated (PS5)")).toMatchObject({ label: "Tested live", tone: "success" });
    expect(evidenceOfStatus(integ("ac").status)).toMatchObject({ label: "Tested on a recording", tone: "success" });
    // the same words and tones as Setup › Game: documentation-built is neutral, never shown as tested
    expect(evidenceOfStatus("community_documented")).toMatchObject({ label: "Built from community docs", tone: "default" });
    expect(evidenceOfStatus("spec_implemented")).toMatchObject({ label: "Built from the official spec", tone: "default" });
    expect(evidenceOfStatus("capture_only").label).toBe("Records packets only");
    expect(evidenceOfStatus("something_new").tone).toBe("warning");
    expect(evidenceOfStatus(null).label).toBe("Unknown");
  });

  it("guides: F1's id is f1_25; the stepper is only complete while receiving", () => {
    const info = fixtures.connectF1Live();
    const f1 = info.integrations.find((g) => g.key === "f1")!;
    const guide = guideFor(info.guides, "f1")!;
    expect(guide.id).toBe("f1_25");
    expect(guideFor(info.guides, "nope")).toBeNull();
    expect(guideStep(f1, guide)).toBe(guide.steps.length + 1);
    expect(guideStep(integ("f1"), guide)).toBe(-1);
    expect(guideStep(null, guide)).toBe(-1);
  });

  it("every guide ends with getting on track, never twice", () => {
    const info = fixtures.connectNoData();
    const f1 = guideFor(info.guides, "f1")!;
    expect(guideSteps(f1).at(-1)).toEqual(DRIVE_OUT_STEP);
    expect(guideSteps(f1)).toHaveLength(f1.steps.length + 1);
    const ac = guideFor(info.guides, "ac")!;
    expect(guideSteps(ac)).toEqual(ac.steps); // AC's own last step is "In the game: Get on track"
  });

  it("guideText copies every step with this Mac's IP", () => {
    const info = fixtures.connectNoData();
    const t = guideText(guideFor(info.guides, "f1")!);
    expect(t).toContain(`UDP IP Address: ${info.mac.lan_ip}`);
    expect(t).toContain("UDP Port: 20777");
    expect(t.split("\n")[1]).toBe("Settings > Telemetry Settings:");
  });

  it("console address labels", () => {
    expect(consoleIpLabel(integ("gt7"))).toBe("PS5 IP");
    expect(consoleIpLabel(integ("ac"))).toBe("Console or PC IP");
  });

  it("F1 first, then enabled games, then the rest", () => {
    const keys = orderedIntegrations(fixtures.connectF1Live().integrations).map((g) => g.key);
    expect(keys).toEqual(["f1", "gt7", "ac", "forza", "record"]);
  });

  it("the selected game's input first (game selection 5.8), then F1, then the enabled ones", () => {
    const list = fixtures.connectF1Live().integrations;
    expect(orderedIntegrations(list, "forza").map((g) => g.key)).toEqual(["forza", "f1", "gt7", "ac", "record"]);
    expect(orderedIntegrations(list, "gt7").map((g) => g.key)).toEqual(["gt7", "f1", "ac", "forza", "record"]);
    expect(orderedIntegrations(list, "f1").map((g) => g.key)).toEqual(["f1", "gt7", "ac", "forza", "record"]);
    expect(orderedIntegrations(list, null).map((g) => g.key)).toEqual(["f1", "gt7", "ac", "forza", "record"]);
  });

  it("guides are matched by the catalogue entry's guide id", () => {
    const guides = fixtures.connectF1Live().guides;
    expect(guideById(guides, "f1_25")?.id).toBe("f1_25");
    expect(guideById(guides, "gt7")?.id).toBe("gt7");
    expect(guideById(guides, null)).toBeNull();
    expect(guideById(guides, "nope")).toBeNull();
  });
});

describe("drafts", () => {
  it("only changed fields are sent", () => {
    const gt7 = integ("gt7");
    const d = draftFrom(gt7);
    expect(draftDirty(gt7, d)).toBe(false);
    expect(updateFromDraft(gt7, d)).toEqual({ body: null, error: null });
    expect(updateFromDraft(gt7, { ...d, console_ip: " 192.168.1.231 " })).toEqual({ body: { console_ip: "192.168.1.231" }, error: null });
    expect(updateFromDraft(gt7, { ...d, console_ip: "" })).toEqual({ body: { console_ip: null }, error: null });
    // GT7's port is fixed by the game: never sent
    expect(updateFromDraft(gt7, { ...d, port: "1" }).body).toBeNull();
  });

  it("ports are whole numbers from 1024 to 65535", () => {
    const forza = integ("forza");
    const d = draftFrom(forza);
    expect(draftDirty(forza, { ...d, port: "5302" })).toBe(true);
    expect(updateFromDraft(forza, { ...d, port: "5302" })).toEqual({ body: { port: 5302 }, error: null });
    for (const bad of ["80", "70000", "53a", "-1", ""]) {
      expect(updateFromDraft(forza, { ...d, port: bad }).error).toBe("Port must be a whole number from 1024 to 65535");
    }
  });
});

describe("live senders", () => {
  it("lists each sender once with its input, freshest first", () => {
    const rows = senderRows(fixtures.connectF1Live());
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ ip: "192.168.1.100", input: "EA SPORTS F1 25", live: true, packetsPerS: 61 });
    expect(senderRows(fixtures.connectNoData())).toEqual([]);
  });

  it("decoded packets, capture name and decode error", () => {
    const t = fixtures.connectF1Live().telemetry;
    expect(decodedPackets(t)).toBe(48208);
    expect(decodedPackets({ ...t, packets: 1, rejected: 5 })).toBe(0);
    expect(captureName("/a/b/20261011-1940.pwcap")).toBe("20261011-1940.pwcap");
    expect(captureName(null)).toBeNull();
    expect(lastDecodeError(t)).toBeNull();
    expect(lastDecodeError({ ...t, decode: { last_error: "packetFormat 2024 not supported" } })).toBe("packetFormat 2024 not supported");
  });
});
