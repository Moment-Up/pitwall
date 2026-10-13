// Settings › Radio & voice, "What the radio says" (v0.3.0): the radio's one policy in the driver's words, built from
// GET /api/radio/policy (voice.scheduler.POLICY), never written by hand here, so it cannot drift from the code.

import type { RadioFamily, RadioIntensity, RadioPolicy } from "../../../lib/endpoints/radiopolicy";

export const POLICY_TITLE = "What the radio says";

const LEVEL_LABEL: Record<RadioIntensity, string> = { quiet: "Quiet", normal: "Normal", detailed: "Detailed" };

/** When a family is said, by coaching amount: "Always", "Normal and Detailed", "Detailed only". */
export function whenSaid(levels: readonly RadioIntensity[]): string {
  if (levels.length === 3) return "Always";
  if (levels.length === 0) return "Never";
  if (levels.length === 1) return `${LEVEL_LABEL[levels[0]!]} only`;
  return levels.map((l) => LEVEL_LABEL[l]).join(" and ");
}

const BUDGET_WORDS: Record<RadioFamily["budget"], string> = {
  waits: "waits for room in the lap's messages",
  spends: "never waits, counts toward the lap's messages",
  free: "outside the lap's messages",
};

/** One family's line: when it is said, whether it cuts in, how it uses the lap. */
export function familyLine(f: RadioFamily): string {
  const parts = [whenSaid(f.intensities)];
  if (f.interrupts) parts.push("cuts in at once");
  parts.push(BUDGET_WORDS[f.budget]);
  return parts.join(" · ");
}

/** The card's first line: the budget per lap and who may cut in. */
export function policySummary(p: RadioPolicy): string {
  const t = p.talkPerLap;
  const cut = p.families.filter((f) => f.interrupts).map((f) => f.label);
  const who = cut.length ? ` Only these cut in: ${cut.join(", ")}. Everything else waits for a calm stretch.` : "";
  return (
    `At most ${t.normal} messages a lap at Normal, ${t.detailed} at Detailed, ${t.quiet} at Quiet, from every ` +
    `source together (race calls at most ${p.racePerLap.normal}, ${p.racePerLap.detailed} at Detailed). ` +
    `Alerts never wait but count.${who}`
  );
}

/** The families in race order, as the card lists them. */
export function policyRows(p: RadioPolicy): { key: string; title: string; hint: string }[] {
  return [...p.families]
    .sort((a, b) => a.rank - b.rank)
    .map((f) => ({ key: f.key, title: f.label, hint: `${f.note} ${familyLine(f)}. ${settingLine(f.setting)}` }));
}

/** Where the family is switched off, in one short sentence ("Always on." / "Switch: Race calls."). */
export function settingLine(setting: string): string {
  if (!setting) return "";
  return setting === "always on" ? "Always on." : `Switch: ${setting}.`;
}
