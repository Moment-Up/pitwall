// Car classes (F2 support, contract v1): the class payloads from the contract's examples, read as the dashboard reads
// them. Unknown stays unknown: an older server (no class), a game without classes (null) and a class this build does
// not know all read as unknown, never as a guess; a raw id is never a car's words.
import { describe, expect, it } from "vitest";
import {
  borrowedCaption,
  carText,
  classChip,
  classOf,
  compoundWords,
  familyCarText,
  familyOf,
  fitsFamily,
  noErs,
  sameFamily,
  type CarClass,
} from "./carclass";
import { CLASSIC_CLASS as CLASSIC, F1_CLASS as F1_2025, F1_GENERIC_CLASS as F1_GENERIC, F2_CLASS as F2, OTHER_CLASS as OTHER } from "./carclass-testkit";

describe("a class payload", () => {
  it("is read when its id and family are ones this build knows", () => {
    expect(classOf(F2)).toBe(F2);
    expect(classOf(F1_GENERIC)?.id).toBe("f1");
    expect(classOf(OTHER)?.family).toBe("other");
  });

  it("anything else is unknown: absent, null, a newer class or family, not an object", () => {
    expect(classOf(undefined)).toBeNull();
    expect(classOf(null)).toBeNull();
    expect(classOf({ ...F2, id: "f3" })).toBeNull();
    expect(classOf({ ...F2, family: "f3" })).toBeNull();
    expect(classOf("f2")).toBeNull();
  });
});

describe("families", () => {
  it("from a class or as sent; unknown is null", () => {
    expect(familyOf(F2)).toBe("f2");
    expect(familyOf(CLASSIC)).toBe("other");
    expect(familyOf("f1")).toBe("f1");
    expect(familyOf("f3")).toBeNull();
    expect(familyOf(null)).toBeNull();
    expect(familyOf(undefined)).toBeNull();
  });

  it("same family is null when either side is unknown (an older server never splits anything)", () => {
    expect(sameFamily(F2, "f2")).toBe(true);
    expect(sameFamily(F1_2025, F1_GENERIC)).toBe(true);
    expect(sameFamily(F2, F1_2025)).toBe(false);
    expect(sameFamily(F2, null)).toBeNull();
    expect(sameFamily(undefined, "f1")).toBeNull();
  });

  it("a lap fits a car unless both families are known and differ", () => {
    expect(fitsFamily("f2", F2)).toBe(true);
    expect(fitsFamily("f1", F2)).toBe(false);
    expect(fitsFamily(null, F2)).toBe(true); // a best from before classes
    expect(fitsFamily("f1", undefined)).toBe(true); // an older server: no class on the session
  });
});

describe("the class chip", () => {
  it("F2 and Classic F1 carry one; F1 cars and other cars without a label do not", () => {
    expect(classChip(F2)).toBe("F2");
    expect(classChip(CLASSIC)).toBe("Classic F1");
    expect(classChip(F1_2025)).toBeNull();
    expect(classChip(F1_GENERIC)).toBeNull();
    expect(classChip(OTHER)).toBeNull();
    expect(classChip(null)).toBeNull();
    expect(classChip(undefined)).toBeNull();
  });

  it("without the chip flag, every family but F1's gets one (a label is still needed)", () => {
    const { chip: _chip, ...noFlag } = F2;
    expect(classChip(noFlag as CarClass)).toBe("F2");
    const { chip: _c2, ...f1NoFlag } = F1_2025;
    expect(classChip(f1NoFlag as CarClass)).toBeNull();
  });
});

describe("the car in words", () => {
  it("the server's car_label first (contract examples), never a raw id", () => {
    // F2 Grand Prix mode, team 214 in format 2025: the spec names no team, the recording does
    expect(carText({ car_label: "F2 · Hitech '25", car_name: "Unknown team (id 214)" })).toBe("F2 · Hitech '25");
    expect(carText({ car_label: "F2 · Art GP '24", car_name: "Art GP '24" })).toBe("F2 · Art GP '24");
    expect(carText({ car_label: "F2 car", car_name: "Unknown team (id 490)" })).toBe("F2 car");
    expect(carText({ car_label: "McLaren", car_name: "McLaren" })).toBe("McLaren");
    expect(carText({ car_label: "Porsche 911 RSR (991) '17", car_name: "Porsche 911 RSR (991) '17" })).toBe("Porsche 911 RSR (991) '17");
  });

  it("an older server (no car_label): the stored name, a raw id left out", () => {
    expect(carText({ car_name: "McLaren" })).toBe("McLaren");
    expect(carText({ car_name: "team_214" })).toBeNull();
    expect(carText({ car_name: "Unknown team (id 214)" })).toBeNull();
    expect(carText({ car_label: null, car_name: "f1:team:214" })).toBeNull();
    expect(carText(null)).toBeNull();
  });
});

describe("compound words", () => {
  it("underscores to spaces, the first letter capital (contract dashboard_strings.drive_tyre_chip)", () => {
    expect(compoundWords("super_soft")).toBe("Super soft");
    expect(compoundWords("soft")).toBe("Soft");
    expect(compoundWords("inter")).toBe("Inter");
    expect(compoundWords("C5")).toBe("C5");
    expect(compoundWords(null)).toBeNull();
    expect(compoundWords("")).toBeNull();
  });
});

describe("ERS", () => {
  it("only a class known to have none hides ERS (F2); unknown (Classic F1, other, no class) keeps it", () => {
    expect(noErs(F2)).toBe(true);
    expect(noErs(F1_2025)).toBe(false);
    expect(noErs(CLASSIC)).toBe(false);
    expect(noErs(null)).toBe(false);
    expect(noErs(undefined)).toBe(false);
  });
});

describe("another family's car and corners", () => {
  it("'F1 car' / 'F2 car', words for a family without a name", () => {
    expect(familyCarText("f1")).toBe("F1 car");
    expect(familyCarText("f2")).toBe("F2 car");
    expect(familyCarText("other")).toBe("another class of car");
    expect(familyCarText(null)).toBe("another class of car");
  });

  it("the borrowed-corners caption (contract strings.track_model.borrowed_caption)", () => {
    // F2 session at a track where only F1 laps built the model
    expect(borrowedCaption({ car_family: "f1", car_family_match: false }, F2)).toBe(
      "Corners from F1 laps until your first clean F2 lap here.",
    );
    // contract example: an F1 session at Melbourne where only an F2 model exists
    expect(borrowedCaption({ car_family: "f2", car_family_match: false }, F1_2025)).toBe(
      "Corners from F2 laps until your first clean F1 lap here.",
    );
    expect(borrowedCaption({ car_family: "f1", car_family_match: false }, CLASSIC)).toBe(
      "Corners from F1 laps until your first clean Classic F1 lap here.",
    );
    expect(borrowedCaption({ car_family: null, car_family_match: false }, F2)).toBe(
      "Corners from another class of car's laps until your first clean F2 lap here.",
    );
  });

  it("no caption for the class's own model, a legacy model, non-F1 games and older servers", () => {
    expect(borrowedCaption({ car_family: "f2", car_family_match: true }, F2)).toBeNull();
    expect(borrowedCaption({ car_family: null, car_family_match: null }, null)).toBeNull();
    expect(borrowedCaption({}, F2)).toBeNull();
    expect(borrowedCaption(null, F2)).toBeNull();
  });
});
