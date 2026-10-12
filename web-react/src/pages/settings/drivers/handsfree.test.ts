// Settings › Drivers, hands-free while driving (lane handsfree): offered only when the server reports the preference,
// sent only when known, and shown on the card when on.

import { describe, expect, it } from "vitest";
import { PALETTE, type Driver } from "../../../lib/drivers";
import {
  driverSubtitle,
  formBody,
  formFromDriver,
  handsFreeDrivingHint,
  handsFreeSupported,
  newDriverForm,
} from "./model";

function driver(id: number, prefs: Partial<Driver["preferences"]> = {}): Driver {
  return {
    id,
    name: `Driver ${id}`,
    created_unix: id,
    preferences: {
      colour: PALETTE[0]!,
      initials: "D",
      skill_level: "beginner",
      coaching_intensity: "normal",
      voice_enabled: true,
      ...prefs,
    },
    coaching: {
      skill_level: "beginner",
      intensity: "normal",
      min_confidence: 0.6,
      min_impact_s: 0.1,
      max_per_lap: 1,
      max_corrective_per_lap: 1,
      max_positive_per_lap: 1,
      allowed_kinds: null,
      simple_wording: true,
      mention_consistency: false,
      corner_repeat_gap_laps: 2,
    },
    active: false,
    stats: { sessions: 0, laps: 0, clean_laps: 0, tracks: 0, last_session_unix: null, best_laps: [] },
  };
}

describe("hands-free while driving in a driver's profile", () => {
  it("is offered only when the server reports the preference", () => {
    expect(handsFreeSupported([driver(1), driver(2)])).toBe(false);
    expect(handsFreeSupported([driver(1), driver(2, { handsfree_while_driving: false })])).toBe(true);
    expect(handsFreeSupported([])).toBe(false);
  });

  it("round-trips through the form and is sent only when known", () => {
    const on = formFromDriver(driver(1, { handsfree_while_driving: true }));
    expect(on.handsfree_while_driving).toBe(true);
    const body = formBody(on);
    expect(body.ok && body.body.handsfree_while_driving).toBe(true);
    const off = formBody({ ...on, handsfree_while_driving: false });
    expect(off.ok && off.body).toMatchObject({ handsfree_while_driving: false });
    const old = formBody(formFromDriver(driver(1)));
    expect(old.ok && "handsfree_while_driving" in old.body).toBe(false); // a server without hands-free never gets it
    const fresh = formBody({ ...newDriverForm([]), name: "Sam" });
    expect(fresh.ok && "handsfree_while_driving" in fresh.body).toBe(false);
    const freshOn = formBody({ ...newDriverForm([]), name: "Sam", handsfree_while_driving: true });
    expect(freshOn.ok && freshOn.body.handsfree_while_driving).toBe(true);
  });

  it("hints and the card subtitle", () => {
    expect(handsFreeDrivingHint(true)).toBe("On: also listens on track (a braking call can cut you off: say it again).");
    expect(handsFreeDrivingHint(false)).toBe("Off: only while the car is stopped.");
    expect(driverSubtitle(driver(1, { handsfree_while_driving: true }), true)).toBe(
      "Beginner · coaching normal · hands-free on track",
    );
    expect(driverSubtitle(driver(1, { handsfree_while_driving: false }), true)).toBe("Beginner · coaching normal");
    expect(driverSubtitle(driver(1, { handsfree_while_driving: true }), false)).toBe("Beginner");
  });
});
