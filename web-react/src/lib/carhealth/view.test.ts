// Car health and racecraft view pieces (lib/carhealth/view.ts, lane "health" spec 3.13 D1 / D6) from the edited
// fixtures (src/test/fixtures/carhealth: hand-built from the lane spec's JSON contract, see each file's _fixture).
// Every state: an older server (no block), a newer contract, another session, F1 carcass / surface / first lap,
// Forza fuel in every status, GT7 fuel unverified, Assetto Corsa nothing sent; rejoin v2 measured / game only /
// frozen / simple; attack and defend clear / spread / none / off / another car; settings payloads.
import { describe, expect, it } from "vitest";
import type { Snapshot } from "../api";
import { frame, snap } from "../drive/testkit";
import type { TrackModelNext } from "../drive/types";
import { mergeStatic, STATIC_KEYS } from "../live";
import type { RejoinView } from "../strategy/types";
import {
  CARHEALTH_FIXTURES,
  healthMeta,
  healthView,
  racecraftView,
  rejoinStrategy,
  settingsFixture,
  withHealth,
} from "./testkit";
import type { RacecraftView, SlipHealth, TankFuel } from "./types";
import {
  BAND_COLOUR,
  BAND_WORD,
  bandAria,
  brakeSection,
  carHealthOf,
  carHealthSettingsOf,
  DEFAULT_CAR_HEALTH_SETTINGS,
  engineSection,
  lapsOfFuelText,
  mainTemp,
  ordinal,
  racecraftMark,
  racecraftOf,
  recentCall,
  rejoinLine,
  slipLine,
  slipSection,
  snapCarHealth,
  snapRacecraft,
  tankFuelLine,
  tempBasis,
  tempsLine,
  tyreSection,
  tyresCold,
  wheelBand,
} from "./view";

/** Words that must never reach the screen (unknown is "-", never a placeholder that looks like data). */
function honest(text: string | null | undefined, what: string): void {
  if (text == null) return;
  for (const bad of ["NaN", "undefined", "null", "Infinity", "[object Object]", "—", "--"]) {
    expect(text, `${what}: ${bad}`).not.toContain(bad);
  }
}

describe("fixtures", () => {
  it("every car-health fixture is edited test data with its provenance", () => {
    expect(CARHEALTH_FIXTURES.length).toBeGreaterThanOrEqual(13);
    for (const name of CARHEALTH_FIXTURES) {
      const m = healthMeta(name);
      expect(m?.tier, name).toBe("edited");
      expect(m?.source, name).toBeTruthy();
      expect(m?.moment, name).toBeTruthy();
      expect(m?.notes ?? "", name).toMatch(/Test data, not game data/);
    }
  });

  it("no fixture carries a name: racecraft has positions, car indexes and corners only (privacy)", () => {
    for (const name of CARHEALTH_FIXTURES.filter((n) => n.includes("racecraft"))) {
      const json = JSON.stringify(racecraftView(name));
      expect(json, name).not.toMatch(/"(name|driver|driver_name|player_name|team)"\s*:\s*"(?!T\d)/);
    }
  });
});

describe("the blocks", () => {
  it("car_health is read only for contract version 1; lists default to empty", () => {
    expect(carHealthOf(null)).toBeNull();
    expect(carHealthOf("x")).toBeNull();
    expect(carHealthOf({ version: 2 })).toBeNull();
    const v = carHealthOf({ version: 1, session_id: "s1" });
    expect(v).toMatchObject({ tyres: null, brakes: null, engine: null, slip: null, fuel: null, calls: [], thresholds: [] });
    expect(carHealthOf(healthView("edited-live-f1-carcass-cold-after-stop"))?.tyres).not.toBeNull();
  });

  it("racecraft is read only for version 1 with a known mode", () => {
    expect(racecraftOf(null)).toBeNull();
    expect(racecraftOf({ version: 1, mode: "attack" })).toBeNull();
    expect(racecraftOf({ version: 2, mode: "race" })).toBeNull();
    expect(racecraftOf(racecraftView("edited-racecraft-off"))).toMatchObject({ mode: "off", reason: "attack and defend need an F1 race" });
  });

  it("a block of another session is never shown; an older server (no key) is null", () => {
    const s = withHealth(snap(), { car_health: healthView("edited-live-f1-carcass-cold-after-stop") });
    expect(snapCarHealth(s)).not.toBeNull();
    expect(snapCarHealth({ ...s, car_health: { ...s.car_health!, session_id: "other" } })).toBeNull();
    expect(snapCarHealth(snap())).toBeNull();
    expect(snapCarHealth(null)).toBeNull();
    const r = withHealth(snap(), { racecraft: racecraftView("edited-racecraft-attack-clear") });
    expect(snapRacecraft(r)?.mode).toBe("race");
    expect(snapRacecraft({ ...r, racecraft: { ...r.racecraft!, session_id: "other" } })).toBeNull();
  });

  it("/ws/live keeps both blocks between their pushes, within the session only (STATIC_KEYS)", () => {
    expect(STATIC_KEYS).toContain("car_health");
    expect(STATIC_KEYS).toContain("racecraft");
    const ch = healthView("edited-live-f1-carcass-cold-after-stop");
    const rc = racecraftView("edited-racecraft-attack-clear");
    const prev = { ...snap(), car_health: ch, racecraft: rc } as unknown as Snapshot;
    const kept = mergeStatic(prev, snap() as unknown as Snapshot) as unknown as Record<string, unknown>;
    expect(kept.car_health).toBe(ch);
    expect(kept.racecraft).toBe(rc);
    const cleared = mergeStatic(prev, { ...snap(), car_health: null } as unknown as Snapshot) as unknown as Record<string, unknown>;
    expect(cleared.car_health).toBeNull();
    const other = mergeStatic(prev, snap({ session_id: "s2" }) as unknown as Snapshot) as unknown as Record<string, unknown>;
    expect(other.car_health).toBeUndefined();
    expect(other.racecraft).toBeUndefined();
  });

  it("sections: available ones are read, unavailable ones are null (their reason is the capability sentence)", () => {
    const f1 = healthView("edited-live-f1-carcass-cold-after-stop");
    expect(tyreSection(f1)?.model).toBe("carcass");
    expect(brakeSection(f1)?.word).toBe("normal");
    expect(engineSection(f1)?.word).toBe("steady");
    expect(slipSection(f1)?.abs).toBe(false);
    const ac = healthView("edited-live-ac-not-sent");
    expect([tyreSection(ac), brakeSection(ac), engineSection(ac), slipSection(ac)]).toEqual([null, null, null, null]);
    expect(ac.tyres).toEqual({ available: false, reason: "Assetto Corsa doesn't send tyre data" });
    // a malformed tyre section (no wheel list) is not read
    expect(tyreSection({ ...f1, tyres: { ...f1.tyres!, wheels: null } as never })).toBeNull();
  });
});

describe("tyre bands: against the driver's own warm laps, never a fixed window", () => {
  it("each wheel's band by its name; unknown without one", () => {
    const t = tyreSection(healthView("edited-live-f1-surface-warm-abs-on"));
    expect((["FL", "FR", "RL", "RR"] as const).map((w) => wheelBand(t, w))).toEqual(["ok", "hot", "ok", "ok"]);
    expect(wheelBand(null, "FL")).toBe("unknown");
    // order on the wire does not matter
    const shuffled = { ...t!, wheels: [...t!.wheels].reverse() };
    expect(wheelBand(shuffled, "FR")).toBe("hot");
    // an unknown band word from a newer server is unknown, never guessed
    expect(wheelBand({ ...t!, wheels: [{ ...t!.wheels[0]!, band: "scorching" as never }] }, "FL")).toBe("unknown");
  });

  it("cold and hot have their own colour and a word; in range and unknown are the plain foreground", () => {
    expect(BAND_COLOUR).toEqual({
      cold: "var(--pw-tyre-cold)",
      hot: "var(--pw-tyre-hot)",
      ok: "var(--pw-tyre-optimal)",
      unknown: "var(--pw-tyre-optimal)",
    });
    expect(BAND_WORD).toEqual({ cold: "cold", hot: "hot" });
    expect(bandAria("cold")).toBe("cold for this session");
    expect(bandAria("ok")).toBe("normal for this session");
    expect(bandAria("unknown")).toBeNull();
  });

  it("the carcass is the main number only when the game simulates it; the caption says which", () => {
    const carcass = tyreSection(healthView("edited-live-f1-carcass-cold-after-stop"));
    const surface = tyreSection(healthView("edited-live-f1-surface-warm-abs-on"));
    expect(mainTemp(carcass)).toBe("inner");
    expect(mainTemp(surface)).toBe("surface");
    expect(mainTemp(null)).toBe("surface");
    expect(tempBasis(carcass)).toBe("Inside temperatures · colours compare with your warm laps");
    expect(tempBasis(surface)).toBe("Surface temperatures · colours compare with your warm laps");
    expect(tempBasis(null)).toBeNull();
  });

  it("cold tyres after a stop (the chip), not on warm or unknown tyres", () => {
    expect(tyresCold(tyreSection(healthView("edited-live-f1-carcass-cold-after-stop")))).toBe(true);
    expect(tyresCold(tyreSection(healthView("edited-live-f1-surface-warm-abs-on")))).toBe(false);
    expect(tyresCold(tyreSection(healthView("edited-live-f1-first-lap")))).toBe(false);
    expect(tyresCold(null)).toBe(false);
  });
});

describe("brakes and engine (F1, from the frame)", () => {
  const F = frame({ brake_temp_c: [982, 979, 961, 960], engine_temp_c: 124.4 });

  it("the hottest brake and the engine, whole degrees", () => {
    expect(tempsLine(F, healthView("edited-live-f1-carcass-cold-after-stop"))).toBe("Brakes 982° · Engine 124°");
  });

  it("unknown values are '-' while the game is known to send them", () => {
    const ch = healthView("edited-live-f1-first-lap");
    expect(tempsLine(frame({ brake_temp_c: null }), ch)).toBe("Brakes - · Engine -");
    expect(tempsLine(frame({ brake_temp_c: [null, 700, null, null] as never, engine_temp_c: null }), ch)).toBe("Brakes 700° · Engine -");
  });

  it("left out for games that do not send them (GT7, Forza, AC)", () => {
    for (const n of ["edited-live-gt7-fuel-unverified", "edited-live-forza-fuel-ok", "edited-live-ac-not-sent"]) {
      expect(tempsLine(F, healthView(n)), n).toBeNull();
    }
  });

  it("an older server (no block): what the frame carries; brakes only when the catalogue does not rule them out", () => {
    expect(tempsLine(frame({ brake_temp_c: [857, 853, 838, 841] }), null)).toBe("Brakes 857°");
    expect(tempsLine(frame({ brake_temp_c: [857, 853, 838, 841] }), null, false)).toBeNull();
    expect(tempsLine(frame({ engine_temp_c: 110 }), null)).toBe("Engine 110°");
    expect(tempsLine(frame(), null)).toBeNull();
    expect(tempsLine(null, null)).toBeNull();
  });
});

describe("lock-ups and wheelspin (F1 MotionEx, the whole last lap)", () => {
  it("ABS off: lock-ups counted", () => {
    expect(slipLine(slipSection(healthView("edited-live-f1-carcass-cold-after-stop")))).toBe("Last lap: 3 lock-ups · 4 wheelspins");
  });

  it("ABS on: lock-ups are not counted, never '0'", () => {
    // with ABS on nothing is counted: no "no lock-ups" claim, just the setting
    expect(slipLine(slipSection(healthView("edited-live-f1-surface-warm-abs-on")))).toBe("Last lap: ABS on · 1 wheelspin");
    const absOn = slipSection(healthView("edited-live-f1-surface-warm-abs-on"));
    expect(absOn && slipLine({ ...absOn, abs: null })).toBe("Last lap: ABS setting not known · 1 wheelspin");
  });

  it("one, none and unknown", () => {
    const base = slipSection(healthView("edited-live-f1-carcass-cold-after-stop"))!;
    const lap = (over: Partial<NonNullable<SlipHealth["last_lap"]>>): SlipHealth => ({ ...base, last_lap: { ...base.last_lap!, ...over } });
    expect(slipLine(lap({ lockups: 1, wheelspin: 1 }))).toBe("Last lap: 1 lock-up · 1 wheelspin");
    expect(slipLine(lap({ lockups: 0, wheelspin: 0 }))).toBe("Last lap: no lock-ups · no wheelspin");
    expect(slipLine(lap({ lockups: null, wheelspin: null }))).toBe("Last lap: lock-ups - · wheelspin -");
  });

  it("before the first lap: '-'; a game without slip: no line", () => {
    expect(slipLine(slipSection(healthView("edited-live-f1-first-lap")))).toBe("Last lap: -");
    expect(slipLine(slipSection(healthView("edited-live-gt7-fuel-unverified")))).toBeNull();
    expect(slipLine(null)).toBeNull();
  });
});

describe("fuel from the tank level (Forza; GT7 once verified)", () => {
  const ok = healthView("edited-live-forza-fuel-ok").fuel!;
  const fuel = (over: Partial<TankFuel>): TankFuel => ({ ...ok, ...over });

  it("laps of fuel: whole laps rounded down, one decimal under two laps", () => {
    expect(lapsOfFuelText(7.6)).toBe("7 laps");
    expect(lapsOfFuelText(2)).toBe("2 laps");
    expect(lapsOfFuelText(1.15)).toBe("1.1 laps");
    expect(lapsOfFuelText(-0.2)).toBe("0.0 laps");
  });

  it("every status in words; low and almost out are amber with their words", () => {
    expect(tankFuelLine(ok)).toEqual({ text: "Fuel ≈ 7 laps (tank level)", tone: "plain", estimates: true });
    expect(tankFuelLine(fuel({ status: "low", laps_of_fuel: 2.6 }))).toEqual({
      text: "Fuel low: ≈ 2 laps (tank level)",
      tone: "warn",
      estimates: true,
    });
    expect(tankFuelLine(healthView("edited-live-forza-fuel-critical").fuel)).toEqual({
      text: "Fuel almost out: ≈ 1.1 laps (tank level)",
      tone: "warn",
      estimates: true,
    });
    expect(tankFuelLine(fuel({ status: "not_used", laps_of_fuel: null }))?.text).toBe("Fuel use off");
    expect(tankFuelLine(fuel({ status: "unknown", laps_of_fuel: null }))?.text).toBe("Fuel: measuring…");
    expect(tankFuelLine(fuel({ status: "ok", laps_of_fuel: null }))?.text).toBe("Fuel: measuring…");
  });

  it("GT7 unverified and not sent: no numbers, and the catalogue's sentence stays", () => {
    const gt7 = tankFuelLine(healthView("edited-live-gt7-fuel-unverified").fuel);
    expect(gt7).toEqual({ text: "Fuel: not estimated", tone: "plain", estimates: false });
    expect(gt7!.text).not.toMatch(/\d/);
    expect(tankFuelLine(healthView("edited-live-ac-not-sent").fuel)).toEqual({ text: "Fuel: not sent", tone: "plain", estimates: false });
    // the backend sends "not sent" without a source
    expect(tankFuelLine({ ...healthView("edited-live-ac-not-sent").fuel!, source: null, laps_used: null, tier: null })?.text).toBe(
      "Fuel: not sent",
    );
  });

  it("F1 (strategy owns fuel) and older servers: null", () => {
    expect(tankFuelLine(healthView("edited-live-f1-carcass-cold-after-stop").fuel)).toBeNull();
    expect(tankFuelLine(null)).toBeNull();
    expect(tankFuelLine({ ...ok, source: "kilos" as never })).toBeNull();
  });
});

describe("where I'd come out (rejoin v2)", () => {
  const r = (): RejoinView => rejoinStrategy().pit!.rejoin!;

  it("ordinals", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 101].map(ordinal)).toEqual([
      "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "101st",
    ]);
  });

  it("measured: '≈', the range, and the aria says the estimate, its pit loss, the game's figure and traffic", () => {
    expect(rejoinLine(r())).toEqual({
      text: "Box now ≈ P11 (P10–12)",
      aria: "If you box now you'd come out around P11, between P10 and P12; Pitwall estimate, from a 22 second pit loss measured on 3 stops; the game says P10; in traffic",
      gameOnly: false,
    });
    expect(rejoinLine(r(), true)?.text).toBe("If you stop now: about 11th");
  });

  it("no range when low and high agree; the tier suffix of a heuristic pit loss", () => {
    expect(rejoinLine({ ...r(), position_low: 11, position_high: 11 })?.text).toBe("Box now ≈ P11");
    expect(rejoinLine({ ...r(), position_low: null, position_high: null })?.text).toBe("Box now ≈ P11");
    expect(rejoinLine({ ...r(), loss_tier: "heuristic" })?.text).toBe("Box now ≈ P11 (P10–12) (estimate)");
    // under a safety car with no stop measured under one: the SC loss rule of thumb
    const sc = rejoinLine({ ...r(), basis: "estimated_loss", loss_tier: "heuristic" });
    expect(sc?.text).toBe("Box now ≈ P11 (P10–12) (estimate)");
    expect(sc?.aria).toContain("Pitwall estimate");
  });

  it("frozen in the pit lane: the prediction made on track, as 'Rejoin'", () => {
    expect(rejoinLine({ ...r(), frozen: true })?.text).toBe("Rejoin ≈ P11 (P10–12)");
    expect(rejoinLine({ ...r(), frozen: true }, true)?.text).toBe("You'll come out about 11th");
    expect(rejoinLine({ ...r(), frozen: true })?.aria).toMatch(/^Coming out of the pits you'd come out around P11/);
  });

  it("no stop measured yet: the game's own figure, said as the game's", () => {
    const g: RejoinView = { ...r(), basis: "game_only", position: null, position_low: null, position_high: null };
    expect(rejoinLine(g)).toEqual({
      text: "Box now: game says P10",
      aria: "If you box now: no pit stop timed in this race yet, the game's own estimate is P10",
      gameOnly: true,
    });
    // stops timed, but the player's own gap is not known this moment (right after their own stop): said so
    expect(rejoinLine({ ...g, reason: "no_gap" })?.aria).toBe(
      "If you box now: your own gap isn't known this moment, the game's own estimate is P10",
    );
    expect(rejoinLine(g, true)?.text).toBe("If you stop now: game says 10th");
    expect(rejoinLine({ ...g, game_position: 0 })).toBeNull(); // F1 25 reads 0 on the in-lap: unknown
    expect(rejoinLine({ ...g, game_position: null })).toBeNull();
  });

  it("an older server's rejoin (no basis) is not shown: its rule was wrong on real races", () => {
    const old: RejoinView = { position: 11, gap_ahead_s: 0.6, gap_behind_s: 2.4, traffic: true, game_position: 10 };
    expect(rejoinLine(old)).toBeNull();
    expect(rejoinLine(null)).toBeNull();
    expect(rejoinLine(undefined)).toBeNull();
  });

  it("every line is honest", () => {
    for (const v of [r(), { ...r(), frozen: true }, { ...r(), loss_s: null, loss_n: null }, { ...r(), basis: "game_only", position: null }]) {
      for (const simple of [false, true]) {
        const l = rejoinLine(v, simple);
        honest(l?.text, "rejoin text");
        honest(l?.aria, "rejoin aria");
      }
    }
  });
});

describe("attack and defend (racecraft)", () => {
  const clear = (): RacecraftView => racecraftView("edited-racecraft-attack-clear");
  const defend = (): RacecraftView => racecraftView("edited-racecraft-defend-clear");

  it("a clear attack corner: BEST <corner> on the car ahead; plain words for simple wording", () => {
    expect(racecraftMark(clear(), "ahead", { carIndex: 7 })).toEqual({
      tag: "BEST T2",
      sub: null,
      aria: "best chance on the car ahead at Turn 3, you gain about 0.4 seconds a lap there",
    });
    expect(racecraftMark(clear(), "ahead", { carIndex: 7, simple: true })).toMatchObject({ tag: null, sub: "you catch it at T2" });
  });

  it("the official short label when the track sheet maps the learned corner", () => {
    const tm = { corners: [{ name: "T2", label: "T3" }] } as unknown as TrackModelNext;
    expect(racecraftMark(clear(), "ahead", { trackModel: tm })?.tag).toBe("BEST T3");
    const viaText = { corners: [], corner_text: { T7: { short: "T8", long: "Turn 8", voice: "turn eight" } } } as unknown as TrackModelNext;
    expect(racecraftMark(defend(), "behind", { trackModel: viaText })?.tag).toBe("WATCH T8");
  });

  it("a clear defend corner: WATCH <corner> on the car behind", () => {
    expect(racecraftMark(defend(), "behind", { carIndex: 14 })).toEqual({
      tag: "WATCH T7",
      sub: null,
      aria: "the car behind is quickest at Turn 7, about 0.2 seconds a lap",
    });
    expect(racecraftMark(defend(), "behind", { simple: true })?.sub).toBe("it catches you at T7");
  });

  it("spread, none or unknown: no mark (no corner is invented)", () => {
    expect(racecraftMark(defend(), "ahead")).toBeNull(); // spread
    expect(racecraftMark(clear(), "behind")).toBeNull(); // none
    const early = clear();
    early.ahead = { ...early.ahead!, verdict: "unknown", laps_compared: null, corner: null, second: null, margin_s: null };
    expect(racecraftMark(early, "ahead")).toBeNull();
  });

  it("another car now (a position changed since the comparison): no mark", () => {
    expect(racecraftMark(clear(), "ahead", { carIndex: 3 })).toBeNull();
    expect(racecraftMark(clear(), "ahead", { carIndex: null })?.tag).toBe("BEST T2");
  });

  it("off, no corners learned, or no block: nothing", () => {
    expect(racecraftMark(racecraftView("edited-racecraft-off"), "ahead")).toBeNull();
    expect(racecraftMark(racecraftView("edited-racecraft-no-corners"), "ahead")).toBeNull();
    expect(racecraftMark(null, "behind")).toBeNull();
  });
});

describe("the radio's calls", () => {
  const ch = healthView("edited-live-f1-carcass-cold-after-stop");
  const T = ch.calls[0]!.t_unix;

  it("the newest call of a topic within its age (2 s of clock skew allowed)", () => {
    expect(recentCall(ch, "tyres_cold", T + 3, 6)?.id).toBe("hc-tyres_cold-2-1");
    expect(recentCall(ch, "tyres_cold", T - 2, 6)?.id).toBe("hc-tyres_cold-2-1");
    expect(recentCall(ch, "tyres_cold", T - 3, 6)).toBeNull();
    expect(recentCall(ch, "tyres_cold", T + 7, 6)).toBeNull();
    expect(recentCall(ch, "fuel_low", T, 6)).toBeNull();
    expect(recentCall(null, "tyres_cold", T, 6)).toBeNull();
  });

  it("every call carries plain words for beginners, and none says to brake later", () => {
    for (const name of CARHEALTH_FIXTURES.filter((n) => n.includes("-live-"))) {
      for (const c of healthView(name).calls) {
        expect(c.text_simple, c.id).toBeTruthy();
        expect(c.text.length, c.id).toBeLessThanOrEqual(120);
        for (const t of [c.text, c.text_simple ?? ""]) {
          expect(t, c.id).not.toMatch(/brake\w* (?:a (?:bit|little) )?later|later on the brakes|brake deeper|\bdive\b/i);
        }
      }
    }
  });
});

describe("settings", () => {
  it("the defaults: every call on, lock-up and wheelspin notes on the detailed radio only", () => {
    expect(carHealthSettingsOf(settingsFixture("edited-settings-default"))).toEqual(DEFAULT_CAR_HEALTH_SETTINGS);
    expect(carHealthSettingsOf(settingsFixture("edited-settings-quiet"))).toEqual({
      tyre_calls: true,
      wear_calls: false,
      fuel_calls: false,
      slip_calls: "normal",
    });
  });

  it("an incomplete or invalid payload is not read (never guessed)", () => {
    expect(carHealthSettingsOf(null)).toBeNull();
    expect(carHealthSettingsOf({ tyre_calls: true })).toBeNull();
    expect(carHealthSettingsOf({ ...DEFAULT_CAR_HEALTH_SETTINGS, slip_calls: "loud" })).toBeNull();
    expect(carHealthSettingsOf({ ...DEFAULT_CAR_HEALTH_SETTINGS, fuel_calls: "yes" })).toBeNull();
  });
});
