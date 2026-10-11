// tokens.css guard rails: the contrast targets of spec 9.2 in every display mode (the same checks as
// `node scripts/contrast.mjs`), scheme parity, removed tokens, and the colour-family rules of spec 9.2.
import { describe, expect, it } from "vitest";
import {
  cascade,
  checkFiles,
  DEFAULT_HEROUI_PATH,
  DEFAULT_TOKENS_PATH,
  hex,
  modeColours,
  parseColor,
  parseRules,
  readText,
  resolveVar,
  runContrast,
  type ModeName,
} from "../../scripts/contrast.mjs";

const tokensCss = readText(DEFAULT_TOKENS_PATH);
const herouiCss = readText(DEFAULT_HEROUI_PATH);
const rules = [...parseRules(herouiCss, "heroui"), ...parseRules(tokensCss, "tokens.css")];
const colourIn = (mode: ModeName, name: string): string => {
  const c = modeColours(rules, mode).colour(name);
  if (!c) throw new Error(`${mode}: ${name} does not resolve to a colour`);
  return hex(c);
};

describe("contrast (spec 9.2, scripts/contrast.mjs)", () => {
  const report = checkFiles();

  it("resolves every checked token in every mode", () => {
    expect(report.errors).toEqual([]);
  });

  it("passes every target in dark, light, night and red-green safe", () => {
    const failed = report.results
      .filter((r) => !r.pass)
      .map((r) => `${r.mode}: ${r.fg} on ${r.bg} = ${r.ratio.toFixed(2)} < ${r.target} (${r.what})`);
    expect(failed).toEqual([]);
    const modes = new Set(report.results.map((r) => r.mode));
    expect([...modes].sort()).toEqual(["dark", "light", "night", "rg-dark", "rg-light", "rg-night"]);
  });

  it("keeps Drive glance values at 4.5:1 or more (the 7:1 aim is a warning)", () => {
    for (const r of report.results.filter((x) => x.aim !== null)) expect(r.ratio, `${r.mode} ${r.fg}`).toBeGreaterThanOrEqual(4.5);
  });

  it("fails on a regression (a token that drops below its target)", () => {
    const broken = tokensCss.replace(
      "--pw-faint: oklch(0.6332 0.0273 257.67);",
      "--pw-faint: oklch(0.35 0.0273 257.67);",
    );
    expect(broken).not.toBe(tokensCss);
    const r = runContrast({ tokensCss: broken, herouiCss });
    expect(r.ok).toBe(false);
    expect(r.results.some((x) => !x.pass && x.fg === "--pw-faint" && x.mode === "dark")).toBe(true);
  });

  it("catches a variable set for one scheme only (it would leak into the other)", () => {
    const leaky = tokensCss.replace("    --pw-neutral-bg: var(--surface-secondary);\n", "");
    expect(leaky).not.toBe(tokensCss);
    const r = runContrast({ tokensCss: leaky, herouiCss });
    expect(r.errors.some((e) => e.includes("--pw-neutral-bg"))).toBe(true);
  });
});

describe("token values (spec 9.2 table)", () => {
  it("dark and light base colours", () => {
    expect(colourIn("dark", "--background")).toBe("#06080b");
    expect(colourIn("dark", "--surface")).toBe("#0f1318");
    expect(colourIn("dark", "--foreground")).toBe("#eef1f5");
    expect(colourIn("dark", "--accent")).toBe("#ff6a2b");
    expect(colourIn("light", "--background")).toBe("#f3f5f8");
    expect(colourIn("light", "--accent")).toBe("#c2410c");
    expect(colourIn("light", "--accent-foreground")).toBe("#ffffff");
  });

  it("timing colours: purple REC, green PB / SB, yellow slower", () => {
    expect(colourIn("dark", "--pw-rec")).toBe("#c58cff");
    expect(colourIn("dark", "--pw-pb")).toBe("#2fe37f");
    expect(colourIn("dark", "--pw-slower")).toBe("#ffd23f");
    expect(colourIn("light", "--pw-rec")).toBe("#6d28d9");
    expect(colourIn("light", "--pw-pb")).toBe("#047857");
    expect(colourIn("light", "--pw-slower-fg")).toBe("#0c1016");
  });

  it("purple means timing only: synthetic is pink, aero zones are not purple", () => {
    expect(colourIn("dark", "--pw-synthetic")).toBe("#ff7ac0");
    expect(colourIn("light", "--pw-synthetic")).toBe("#be185d");
    for (const mode of ["dark", "light"] as const) {
      expect(colourIn(mode, "--pw-zone-aero")).not.toBe(colourIn(mode, "--pw-rec"));
      expect(colourIn(mode, "--pw-synthetic")).not.toBe(colourIn(mode, "--pw-rec"));
    }
  });

  it("sector identity is neutral grey (no timing, flag or brake hue)", () => {
    for (const mode of ["dark", "light", "night"] as const) {
      for (const s of ["--pw-sector-1", "--pw-sector-2", "--pw-sector-3"]) {
        const c = parseColor(colourIn(mode, s));
        if (!c) throw new Error(s);
        const [r, g, b] = c;
        expect(Math.max(r, g, b) - Math.min(r, g, b), `${mode} ${s}`).toBeLessThan(0.12);
      }
    }
  });

  it("slower is yellow and behind is red; amber is stale only", () => {
    expect(colourIn("dark", "--pw-behind")).toBe("#ff5466");
    expect(colourIn("dark", "--pw-stale")).toBe("#ffb020");
    expect(colourIn("dark", "--pw-stale")).not.toBe(colourIn("dark", "--pw-slower"));
  });

  it("night dims the dark scheme only", () => {
    expect(colourIn("night", "--background")).toBe("#000000");
    expect(colourIn("night", "--foreground")).toBe("#c9ced6");
    expect(colourIn("night", "--pw-pb")).toBe("#28c46e");
    // light ignores data-night
    const props = cascade(rules, { classes: ["light"], attrs: { "data-theme": "light", "data-night": "on" } });
    const bg = parseColor(resolveVar(props, "--background") ?? "");
    expect(bg && hex(bg)).toBe("#f3f5f8");
  });

  it("red-green safe turns green blue and red orange in every scheme, night included", () => {
    expect(colourIn("rg-dark", "--pw-pb")).toBe("#4cc3ff");
    expect(colourIn("rg-dark", "--pw-behind")).toBe("#ff9f1c");
    expect(colourIn("rg-light", "--pw-pb")).toBe("#0369a1");
    expect(colourIn("rg-light", "--pw-behind")).toBe("#9f4706");
    for (const mode of ["rg-dark", "rg-light", "rg-night"] as const) {
      expect(colourIn(mode, "--success"), mode).toBe(colourIn(mode, "--pw-pb"));
      expect(colourIn(mode, "--danger"), mode).toBe(colourIn(mode, "--pw-behind"));
      expect(colourIn(mode, "--pw-ahead"), mode).toBe(colourIn(mode, "--pw-pb"));
      expect(colourIn(mode, "--pw-brake"), mode).toBe(colourIn(mode, "--pw-behind"));
    }
    // night + rg: blue / orange, never night's green or red
    expect(colourIn("rg-night", "--success")).not.toBe(colourIn("night", "--success"));
    expect(colourIn("rg-night", "--danger")).not.toBe(colourIn("night", "--danger"));
  });

  it("flag bands are the same in every theme", () => {
    for (const t of ["--pw-flag-yellow", "--pw-flag-sc", "--pw-flag-red", "--pw-flag-blue", "--pw-pit"]) {
      expect(colourIn("light", t), t).toBe(colourIn("dark", t));
    }
    expect(colourIn("dark", "--pw-flag-red")).toBe("#d7263d");
  });
});

describe("token structure (spec 11)", () => {
  const defined = new Set(parseRules(tokensCss).flatMap((r) => [...r.decls.keys()]));

  it("defines the Drive scale, layout, touch, font and motion tokens", () => {
    for (const t of [
      "--pw-d-delta",
      "--pw-d-corner",
      "--pw-d-corner-long",
      "--pw-d-pit",
      "--pw-d-xl",
      "--pw-d-l",
      "--pw-d-m",
      "--pw-d-s",
      "--pw-d-xs",
      "--pw-d-label",
      "--pw-drive-k",
      "--pw-rail-w",
      "--pw-status-h",
      "--pw-tabbar-h",
      "--pw-appbar-h",
      "--pw-touch",
      "--pw-touch-drive",
      "--pw-touch-glove",
      "--pw-font-num",
      "--pw-font-sans",
      "--pw-font-mono",
      "--pw-motion-bar",
    ]) {
      expect(defined.has(t), t).toBe(true);
    }
  });

  it("Large multiplies the Drive scale by 1.12; radius is 0.5rem", () => {
    expect(tokensCss).toMatch(/:root\[data-drive-size="large"\]\s*\{\s*--pw-drive-k:\s*1\.12;/);
    expect(tokensCss).toMatch(/--radius:\s*0\.5rem;/);
    expect(tokensCss).toMatch(/--pw-d-delta:\s*calc\(clamp\(104px, 17\.6dvh, 172px\) \* var\(--pw-drive-k\)\)/);
  });

  it("keeps the v1 tokens only as aliases carrying the new meanings (deprecated until phase 3)", () => {
    expect(colourIn("dark", "--pw-gain")).toBe(colourIn("dark", "--pw-ahead"));
    expect(colourIn("dark", "--pw-loss")).toBe(colourIn("dark", "--pw-stale"));
    expect(colourIn("light", "--pw-sector-best")).toBe(colourIn("light", "--pw-pb"));
    expect(colourIn("rg-dark", "--pw-gain")).toBe("#4cc3ff");
    for (const u of ["--color-gain:", "--color-loss:", "--color-sector-best:", "--color-sector-pb:", "--color-sector-slower:"]) {
      expect(tokensCss, u).toContain(u);
    }
    const raw = tokensCss.replace("--pw-loss: var(--pw-stale);", "--pw-loss: oklch(0.8131 0.165 75.04);");
    expect(raw).not.toBe(tokensCss);
    expect(runContrast({ tokensCss: raw, herouiCss }).errors.some((e) => e.includes("--pw-loss"))).toBe(true);
  });

  it("maps the utilities other lanes use", () => {
    for (const u of [
      "--font-num:",
      "--text-d-delta:",
      "--color-pw-rec:",
      "--color-pw-pb-bg:",
      "--color-ahead:",
      "--color-behind:",
      "--color-flag-yellow:",
      "--color-flag-yellow-ink:",
      "--color-pit-ink:",
      "--color-faint:",
      "--color-line-strong:",
      "--color-synthetic:",
    ]) {
      expect(tokensCss, u).toContain(u);
    }
  });

  it("Drive has no shadow but keeps focus rings (a transparent shadow, not none)", () => {
    expect(tokensCss).toMatch(/\.pw-drive\s*\{\s*--surface-shadow:\s*0 0 0 0 transparent inset;/);
  });
});
