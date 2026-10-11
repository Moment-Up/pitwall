#!/usr/bin/env node
// Pitwall token contrast check (docs/ui/design-spec.md v2, sections 9.2 and 14.2).
//
// Recomputes WCAG 2.x contrast ratios from the real stylesheet instead of trusting the numbers in the spec:
//   1. parses HeroUI's default theme (node_modules/@heroui/styles/.../variables.css) and src/styles/tokens.css,
//   2. cascades their custom properties onto a fake <html> for every display mode (dark, light, night, red-green
//      safe in each; the same attributes lib/prefs.ts sets: class + data-theme, data-night, data-cvd),
//   3. resolves var() chains and evaluates the colours (hex, rgb, oklch, oklab, color-mix in oklab/oklch/srgb,
//      alpha composited over the surface they sit on),
//   4. checks every pair below against its target and exits 1 when one fails.
//
//   node scripts/contrast.mjs            # failures, warnings and a summary
//   node scripts/contrast.mjs --all      # every pair in every mode
//   node scripts/contrast.mjs --hex      # resolved hex of the main tokens per mode (to compare with spec 9.2)
//
// Targets (spec 9.2): 4.5:1 for text; 3:1 for control boundaries; Drive glance values aim at 7:1 and are never
// below 4.5:1 (a ratio between 4.5 and 7 on a glance pair is a warning, not a failure).
// The vitest suite runs the same checks (src/styles/tokens.test.ts), so `npm run check` fails on a regression.

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const DEFAULT_TOKENS_PATH = resolve(HERE, "../src/styles/tokens.css");
export const DEFAULT_HEROUI_PATH = resolve(HERE, "../node_modules/@heroui/styles/dist/themes/default/variables.css");

// ------------------------------------------------------------------------------------------------ modes

/** Display modes as attribute sets on <html> (lib/prefs.ts applies exactly these). */
export const MODES = {
  dark: { classes: ["dark"], attrs: { "data-theme": "dark" } },
  light: { classes: ["light"], attrs: { "data-theme": "light" } },
  night: { classes: ["dark"], attrs: { "data-theme": "dark", "data-night": "on" } },
  "rg-dark": { classes: ["dark"], attrs: { "data-theme": "dark", "data-cvd": "rg" } },
  "rg-light": { classes: ["light"], attrs: { "data-theme": "light", "data-cvd": "rg" } },
  "rg-night": { classes: ["dark"], attrs: { "data-theme": "dark", "data-night": "on", "data-cvd": "rg" } },
};
const DARKISH = ["dark", "night", "rg-dark", "rg-night"];

// ------------------------------------------------------------------------------------------------ checks

/**
 * [foreground, background, target, what, options]. `on` composites a translucent background over that token first
 * (soft chips, tints). `modes` limits a pair to some modes. `aim` marks a Drive glance pair (warn below it).
 */
export const CHECKS = [
  // HeroUI base text and surfaces
  ["--foreground", "--background", 4.5, "body text on the page"],
  ["--foreground", "--surface", 4.5, "text on cards", { aim: 7 }],
  ["--foreground", "--surface-secondary", 4.5, "text on secondary cards"],
  ["--foreground", "--surface-tertiary", 4.5, "text on tertiary surfaces / default chips"],
  ["--muted", "--background", 4.5, "secondary text on the page"],
  ["--muted", "--surface", 4.5, "secondary text on cards"],
  ["--muted", "--surface-secondary", 4.5, "secondary text on secondary cards"],
  ["--muted", "--surface-tertiary", 4.5, "INV tag text"],
  ["--pw-faint", "--background", 4.5, "labels, the unknown dash"],
  ["--pw-faint", "--surface", 4.5, "labels, the unknown dash on cards"],
  ["--pw-faint", "--surface-secondary", 4.5, "the unknown dash in a timing cell"],
  ["--pw-line-strong", "--background", 3, "control boundary on the page"],
  ["--pw-line-strong", "--surface", 3, "control boundary / running-sector outline"],
  ["--default-foreground", "--default", 4.5, "default chips and buttons"],
  ["--foreground", "--default", 4.5, "secondary button ink (index.css .button--secondary)"],
  ["--segment-foreground", "--segment", 4.5, "selected segment"],
  ["--overlay-foreground", "--overlay", 4.5, "popovers, menus"],
  ["--field-foreground", "--field-background", 4.5, "form fields"],
  // accent and status fills
  ["--accent", "--surface", 4.5, "accent text / active rail icon"],
  ["--accent", "--background", 4.5, "accent text on the page"],
  ["--accent-foreground", "--accent", 4.5, "primary button ink"],
  ["--success-foreground", "--success", 4.5, "success fill ink"],
  ["--warning-foreground", "--warning", 4.5, "warning fill ink"],
  ["--danger-foreground", "--danger", 4.5, "danger fill ink"],
  // HeroUI soft chips (Work on / Good / INVALID / Changed), composited on the card
  ["--accent-soft-foreground", "--accent-soft", 4.5, "accent soft chip", { on: "--surface" }],
  ["--success-soft-foreground", "--success-soft", 4.5, "success soft chip (Good · L6)", { on: "--surface" }],
  ["--warning-soft-foreground", "--warning-soft", 4.5, "warning soft chip (Work on · L6)", { on: "--surface" }],
  ["--danger-soft-foreground", "--danger-soft", 4.5, "danger soft chip (INVALID)", { on: "--surface" }],
  // timing colours: dark = coloured numerals on a 10 % tint, light = solid fill with ink
  ["--pw-rec-fg", "--pw-rec-bg", 4.5, "REC time in its cell", { aim: 7 }],
  ["--pw-pb-fg", "--pw-pb-bg", 4.5, "PB / SB time in its cell", { aim: 7 }],
  ["--pw-slower-fg", "--pw-slower-bg", 4.5, "slower time in its cell", { aim: 7 }],
  ["--pw-rec", "--surface", 4.5, "REC numerals / chart points", { modes: DARKISH, aim: 7 }],
  ["--pw-pb", "--surface", 4.5, "PB / SB numerals, ahead", { aim: 7 }],
  ["--pw-slower", "--surface", 4.5, "slower numerals (never text in light)", { modes: DARKISH, aim: 7 }],
  ["--pw-rec", "--surface", 4.5, "REC fill (light charts, legend)", { modes: ["light", "rg-light"] }],
  ["--pw-rec-ink", "--pw-rec", 4.5, "REC tag ink"],
  ["--pw-pb-ink", "--pw-pb", 4.5, "PB / SB tag ink"],
  ["--pw-slower-ink", "--pw-slower", 4.5, "yellow fill ink"],
  // delta, brake, state
  ["--pw-ahead", "--surface", 4.5, "delta ahead", { aim: 7 }],
  ["--pw-behind", "--surface", 4.5, "delta behind", { aim: 7 }],
  ["--pw-ahead", "--surface-secondary", 4.5, "ahead in a secondary cell"],
  ["--pw-behind", "--surface-secondary", 4.5, "behind in a secondary cell"],
  ["--pw-brake-ink", "--pw-brake", 4.5, "BRAKE chip"],
  ["--pw-stale", "--surface", 4.5, "stale outline band text"],
  ["--pw-bad", "--surface", 4.5, "offline outline band text"],
  ["--pw-status-live", "--surface", 4.5, "Live pill"],
  ["--pw-status-idle", "--surface", 4.5, "No data pill"],
  ["--pw-ref", "--surface", 4.5, "reference trace / info text"],
  ["--pw-synthetic", "--surface", 4.5, "SYNTHETIC chip text"],
  ["--pw-synthetic", "--pw-hatch-stripe", 4.5, "SYNTHETIC text on its hatch stripe", { on: "--surface" }],
  // flag bands (20 px / 800 words; filled, same in every theme)
  ["--pw-flag-yellow-ink", "--pw-flag-yellow", 4.5, "YELLOW band"],
  ["--pw-flag-sc-ink", "--pw-flag-sc", 4.5, "SAFETY CAR band"],
  ["--pw-flag-red-ink", "--pw-flag-red", 4.5, "RED FLAG band"],
  ["--pw-flag-blue-ink", "--pw-flag-blue", 4.5, "BLUE FLAG band"],
  ["--pw-pit-ink", "--pw-pit", 4.5, "PIT LANE band"],
  // lap ribbon: sector labels (13 px / 700) on the neutral sector bands. --foreground reaches 4.5:1 everywhere;
  // --muted (the mockup's choice) only 3:1, so labels that must be read use --foreground.
  ["--foreground", "--pw-sector-1", 4.5, "S1 label on its band"],
  ["--foreground", "--pw-sector-2", 4.5, "S2 label on its band"],
  ["--foreground", "--pw-sector-3", 4.5, "S3 label on its band"],
  ["--muted", "--pw-sector-1", 3, "S1 muted label on its band"],
  ["--muted", "--pw-sector-2", 3, "S2 muted label on its band"],
  ["--muted", "--pw-sector-3", 3, "S3 muted label on its band"],
];

/**
 * v1 tokens deprecated by spec 11 step 3 ([critic]): until phase 3 they may only exist as aliases of the new tokens
 * (so they carry the new meanings); after that they are removed. A raw colour, or an alias to anything else, fails.
 */
export const DEPRECATED_ALIASES = {
  "--pw-gain": "--pw-ahead",
  "--pw-loss": "--pw-stale",
  "--pw-sector-best": "--pw-pb",
  "--pw-sector-pb": "--pw-pb",
  "--pw-sector-slower": "--pw-slower",
};

// ------------------------------------------------------------------------------------------------ CSS parsing

function stripComments(css) {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function matchingBrace(text, open) {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    const c = text[i];
    if (c === "{") depth++;
    else if (c === "}" && --depth === 0) return i;
  }
  return -1;
}

/** Split on `sep` at parenthesis depth 0. */
function splitTop(text, sep) {
  const out = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "(") depth++;
    else if (c === ")") depth--;
    else if (c === sep && depth === 0) {
      out.push(text.slice(start, i));
      start = i + 1;
    }
  }
  out.push(text.slice(start));
  return out.map((s) => s.trim()).filter(Boolean);
}

/**
 * Style rules with their custom properties, in source order. Descends into @layer / @media / @supports (as if they
 * applied); skips @theme (Tailwind's utility mapping), @keyframes and anything else.
 */
export function parseRules(css, source = "css") {
  const text = stripComments(css);
  const rules = [];
  const walk = (from, to) => {
    let i = from;
    while (i < to) {
      const brace = text.indexOf("{", i);
      const semi = text.indexOf(";", i);
      if (brace === -1 || brace >= to) return;
      if (semi !== -1 && semi < brace) {
        i = semi + 1; // a statement (@import ...) or a stray declaration
        continue;
      }
      const prelude = text.slice(i, brace).trim();
      const close = matchingBrace(text, brace);
      if (close === -1) throw new Error(`${source}: unbalanced braces after "${prelude}"`);
      if (prelude.startsWith("@")) {
        if (/^@(layer|media|supports)\b/.test(prelude)) walk(brace + 1, close);
      } else {
        const decls = new Map();
        for (const d of splitTop(text.slice(brace + 1, close), ";")) {
          const colon = d.indexOf(":");
          if (colon > 0 && d.startsWith("--")) decls.set(d.slice(0, colon).trim(), d.slice(colon + 1).trim());
        }
        rules.push({ selectors: splitTop(prelude, ","), decls, source });
      }
      i = close + 1;
    }
  };
  walk(0, text.length);
  return rules;
}

// ------------------------------------------------------------------------------------------------ selectors

/** Specificity (a*10000 + b*100 + c) of `sel` when it matches the root element `el`, else null. */
export function matchRoot(sel, el) {
  const s = sel.trim();
  let i = 0;
  let spec = 0;
  const readIdent = () => {
    const m = /^-?[_a-zA-Z][-_a-zA-Z0-9]*/.exec(s.slice(i));
    if (!m) throw new Error(`selector: cannot read "${s}"`);
    i += m[0].length;
    return m[0];
  };
  const readParens = () => {
    let depth = 0;
    const start = i;
    for (; i < s.length; i++) {
      if (s[i] === "(") depth++;
      else if (s[i] === ")" && --depth === 0) {
        i++;
        return s.slice(start + 1, i - 1);
      }
    }
    throw new Error(`selector: unbalanced "${s}"`);
  };
  while (i < s.length) {
    const c = s[i];
    if (/\s|>|\+|~/.test(c)) return null; // a combinator: not the root element itself
    if (c === "*") {
      i++;
    } else if (c === ".") {
      i++;
      if (!el.classes.includes(readIdent())) return null;
      spec += 100;
    } else if (c === "[") {
      const end = s.indexOf("]", i);
      const m = /^\[\s*([-\w]+)\s*(?:=\s*"?([^"\]]*)"?)?\s*\]$/.exec(s.slice(i, end + 1));
      if (!m) throw new Error(`selector: unsupported attribute in "${s}"`);
      i = end + 1;
      const v = el.attrs[m[1]];
      if (v === undefined || (m[2] !== undefined && v !== m[2])) return null;
      spec += 100;
    } else if (c === ":") {
      i++;
      const name = readIdent();
      if (name === "root") spec += 100;
      else if (name === "host") return null; // shadow hosts: never the document root
      else if (name === "is" || name === "where" || name === "not") {
        const args = splitTop(readParens(), ",");
        const specs = args.map((a) => matchRoot(a, el));
        const hit = specs.filter((x) => x !== null);
        if (name === "not") {
          if (hit.length) return null;
          spec += 100; // the arguments used in these files are single classes / attributes
        } else {
          if (!hit.length) return null;
          if (name === "is") spec += Math.max(...hit);
        }
      } else return null; // :hover etc. never hold for the root at rest
    } else if (/[a-zA-Z]/.test(c)) {
      if (readIdent() !== "html") return null;
      spec += 1;
    } else throw new Error(`selector: unsupported "${s}"`);
  }
  return spec;
}

/** Cascade every rule onto the root: highest specificity wins, then the later rule (all sources share one layer). */
export function cascade(rules, el) {
  const won = new Map();
  rules.forEach((rule, order) => {
    let best = null;
    for (const sel of rule.selectors) {
      const sp = matchRoot(sel, el);
      if (sp !== null && (best === null || sp > best)) best = sp;
    }
    if (best === null) return;
    for (const [k, v] of rule.decls) {
      const prev = won.get(k);
      if (!prev || best > prev.spec || (best === prev.spec && order >= prev.order)) {
        won.set(k, { value: v, spec: best, order, source: rule.source });
      }
    }
  });
  return new Map([...won].map(([k, v]) => [k, v.value]));
}

/** Substitute var() references (with fallbacks); null when a reference cannot be resolved. */
export function resolveVar(props, name, seen = new Set()) {
  if (seen.has(name)) return null; // cycle: invalid at computed-value time
  const raw = props.get(name);
  if (raw === undefined) return null;
  return substitute(props, raw, new Set([...seen, name]));
}

function substitute(props, value, seen) {
  let out = "";
  let i = 0;
  while (i < value.length) {
    const at = value.indexOf("var(", i);
    if (at === -1) {
      out += value.slice(i);
      break;
    }
    out += value.slice(i, at);
    let depth = 0;
    let j = at + 3;
    for (; j < value.length; j++) {
      if (value[j] === "(") depth++;
      else if (value[j] === ")" && --depth === 0) break;
    }
    const inner = value.slice(at + 4, j);
    const comma = splitTop(inner, ",");
    const ref = comma[0];
    const fallback = inner.includes(",") ? inner.slice(inner.indexOf(",") + 1).trim() : null;
    let v = resolveVar(props, ref, seen);
    if (v === null && fallback !== null) v = substitute(props, fallback, seen);
    if (v === null) return null;
    out += v;
    i = j + 1;
  }
  return out.trim();
}

// ------------------------------------------------------------------------------------------------ colour

const clamp01 = (x) => Math.min(1, Math.max(0, x));
const toLinear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toGamma = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

function oklabToSrgb(L, a, b) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    toGamma(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    toGamma(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    toGamma(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

function srgbToOklab(r, g, b) {
  const [R, G, B] = [r, g, b].map(toLinear);
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}

const NAMED = { transparent: [0, 0, 0, 0], white: [1, 1, 1, 1], black: [0, 0, 0, 1] };

function parseNumber(tok, percentScale = 1) {
  if (tok === "none") return 0;
  if (tok.endsWith("%")) return (parseFloat(tok) / 100) * percentScale;
  const n = parseFloat(tok);
  if (Number.isNaN(n)) throw new Error(`colour: bad number "${tok}"`);
  return n;
}

/** CSS colour -> [r, g, b, alpha] in gamma-encoded sRGB (0..1, unclamped until display), or null if unsupported. */
export function parseColor(input) {
  const v = input.trim().toLowerCase();
  if (v in NAMED) return [...NAMED[v]];
  if (v.startsWith("#")) {
    let h = v.slice(1);
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("");
    if (h.length !== 6 && h.length !== 8) return null;
    const n = (k) => parseInt(h.slice(k, k + 2), 16) / 255;
    return [n(0), n(2), n(4), h.length === 8 ? n(6) : 1];
  }
  const fn = /^([a-z-]+)\((.*)\)$/s.exec(v);
  if (!fn) return null;
  const [, name, body] = fn;
  if (name === "color-mix") return colorMix(body);
  if (/\bfrom\b/.test(body)) return null; // relative colour syntax: not needed for these checks
  const [main, alphaTok] = body.split("/").map((p) => p.trim());
  const parts = main.includes(",") ? main.split(",").map((p) => p.trim()) : main.split(/\s+/);
  const alpha = alphaTok !== undefined ? clamp01(parseNumber(alphaTok)) : parts.length === 4 ? clamp01(parseNumber(parts[3])) : 1;
  if (name === "rgb" || name === "rgba") {
    const [r, g, b] = parts.slice(0, 3).map((p) => (p.endsWith("%") ? parseNumber(p) : parseNumber(p) / 255));
    return [r, g, b, alpha];
  }
  if (name === "oklch") {
    const L = parseNumber(parts[0]);
    const C = parseNumber(parts[1], 0.4);
    const H = (parseNumber(parts[2]) * Math.PI) / 180;
    return [...oklabToSrgb(L, C * Math.cos(H), C * Math.sin(H)), alpha];
  }
  if (name === "oklab") {
    return [...oklabToSrgb(parseNumber(parts[0]), parseNumber(parts[1], 0.4), parseNumber(parts[2], 0.4)), alpha];
  }
  return null;
}

/** color-mix(in <space>, c1 [p1], c2 [p2]) per CSS Color 5 (premultiplied alpha, percentage normalisation). */
function colorMix(body) {
  const [space, a, b] = splitTop(body, ",");
  if (!a || !b) return null;
  const sp = space.replace(/^in\s+/, "").trim();
  const split = (arg) => {
    const m = /^(.*?)\s+(-?[\d.]+%)$/s.exec(arg);
    return m ? [m[1].trim(), parseFloat(m[2]) / 100] : [arg.trim(), null];
  };
  const [ca, pa0] = split(a);
  const [cb, pb0] = split(b);
  let pa = pa0;
  let pb = pb0;
  if (pa === null && pb === null) pa = pb = 0.5;
  else if (pa === null) pa = 1 - pb;
  else if (pb === null) pb = 1 - pa;
  const sum = pa + pb;
  if (sum <= 0) return null;
  const alphaMult = sum < 1 ? sum : 1;
  pa /= sum;
  pb /= sum;
  const A = parseColor(ca);
  const B = parseColor(cb);
  if (!A || !B) return null;
  const coords = (c) => {
    if (sp === "srgb") return c.slice(0, 3);
    const lab = srgbToOklab(c[0], c[1], c[2]);
    if (sp === "oklab") return lab;
    if (sp === "oklch") {
      const C = Math.hypot(lab[1], lab[2]);
      return [lab[0], C, (Math.atan2(lab[2], lab[1]) * 180) / Math.PI];
    }
    throw new Error(`color-mix: unsupported space "${sp}"`);
  };
  const alpha = A[3] * pa + B[3] * pb;
  const ka = coords(A);
  const kb = coords(B);
  let mixed;
  if (sp === "oklch") {
    // hue of a fully transparent or achromatic side is powerless: take the other's
    let ha = ka[2];
    let hb = kb[2];
    if (A[3] === 0 || ka[1] < 1e-6) ha = hb;
    if (B[3] === 0 || kb[1] < 1e-6) hb = ha;
    let d = hb - ha;
    if (d > 180) d -= 360;
    else if (d < -180) d += 360;
    const pre = (k, i) => k[i];
    const L = alpha ? (pre(ka, 0) * A[3] * pa + pre(kb, 0) * B[3] * pb) / alpha : 0;
    const C = alpha ? (ka[1] * A[3] * pa + kb[1] * B[3] * pb) / alpha : 0;
    const H = ((ha + d * pb) * Math.PI) / 180;
    mixed = oklabToSrgb(L, C * Math.cos(H), C * Math.sin(H));
  } else {
    const pre = [0, 1, 2].map((i) => (alpha ? (ka[i] * A[3] * pa + kb[i] * B[3] * pb) / alpha : 0));
    mixed = sp === "srgb" ? pre : oklabToSrgb(pre[0], pre[1], pre[2]);
  }
  return [...mixed, alpha * alphaMult];
}

/** Alpha-composite `fg` over an opaque `bg` (in gamma sRGB, as browsers do). */
export function over(fg, bg) {
  const a = fg[3];
  return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)).concat(1);
}

function luminance(c) {
  const [r, g, b] = c.slice(0, 3).map((x) => toLinear(clamp01(x)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

export function hex(c) {
  return `#${c
    .slice(0, 3)
    .map((x) => Math.round(clamp01(x) * 255).toString(16).padStart(2, "0"))
    .join("")}${c[3] < 0.998 ? Math.round(c[3] * 255).toString(16).padStart(2, "0") : ""}`;
}

// ------------------------------------------------------------------------------------------------ run

/** Custom properties of one mode, resolved to colours (null where a value is not a colour). */
export function modeColours(rules, mode) {
  const props = cascade(rules, MODES[mode]);
  // The synthetic hatch stripe (tokens.css .pw-hatch-synthetic) as a pseudo-token for the checks.
  props.set("--pw-hatch-stripe", "color-mix(in oklab, var(--pw-synthetic) var(--pw-hatch-pct, 24%), transparent)");
  const colour = (name) => {
    const v = resolveVar(props, name);
    return v === null ? null : parseColor(v);
  };
  return { props, colour };
}

/** Scheme-parity check: every custom property tokens.css sets for one scheme is also set for the other. */
export function parityErrors(tokenRules) {
  const setBy = (pred) => {
    const names = new Set();
    for (const r of tokenRules) if (r.selectors.some(pred)) for (const k of r.decls.keys()) names.add(k);
    return names;
  };
  const light = setBy((s) => /^(\.light|\[data-theme="light"\])$/.test(s.trim()));
  const dark = setBy((s) => /^(\.dark|\[data-theme="dark"\])$/.test(s.trim()));
  const errors = [];
  for (const k of light) if (!dark.has(k)) errors.push(`${k} is set for light but not for dark (it would leak into dark)`);
  for (const k of dark) if (!light.has(k)) errors.push(`${k} is set for dark but not for light`);
  return errors;
}

export function runContrast({ tokensCss, herouiCss }) {
  const tokenRules = parseRules(tokensCss, "tokens.css");
  const rules = [...parseRules(herouiCss, "heroui"), ...tokenRules];
  const errors = parityErrors(tokenRules);
  for (const r of tokenRules) {
    for (const [name, target] of Object.entries(DEPRECATED_ALIASES)) {
      const v = r.decls.get(name);
      if (v !== undefined && v.replace(/\s+/g, "") !== `var(${target})`) {
        errors.push(`${name} is deprecated (spec 11 step 3): only "var(${target})" is allowed until it is removed, found "${v}"`);
      }
    }
  }

  const results = [];
  for (const mode of Object.keys(MODES)) {
    const { colour } = modeColours(rules, mode);
    for (const [fgName, bgName, target, what, opt = {}] of CHECKS) {
      if (opt.modes && !opt.modes.includes(mode)) continue;
      const fg = colour(fgName);
      let bg = colour(bgName);
      const base = opt.on ? colour(opt.on) : null;
      if (!fg || !bg || (opt.on && !base)) {
        errors.push(`${mode}: cannot resolve ${!fg ? fgName : !bg ? bgName : opt.on}`);
        continue;
      }
      if (bg[3] < 1) {
        const under = base ?? colour("--surface");
        if (!under) {
          errors.push(`${mode}: cannot resolve the surface under ${bgName}`);
          continue;
        }
        bg = over(bg, under);
      }
      const ratio = contrast(over(fg, bg), bg);
      results.push({
        mode,
        fg: fgName,
        bg: opt.on ? `${bgName} on ${opt.on}` : bgName,
        what,
        ratio,
        target,
        aim: opt.aim ?? null,
        pass: ratio >= target,
        warn: ratio >= target && opt.aim != null && ratio < opt.aim,
        fgHex: hex(fg),
        bgHex: hex(bg),
      });
    }
  }
  return { results, errors, ok: errors.length === 0 && results.every((r) => r.pass) };
}

export function readText(path) {
  return readFileSync(path, "utf8");
}

/** Read the stylesheets from disk (defaults: this repo's tokens.css and the installed HeroUI theme) and run. */
export function checkFiles({ tokensPath = DEFAULT_TOKENS_PATH, herouiPath = DEFAULT_HEROUI_PATH } = {}) {
  return runContrast({ tokensCss: readText(tokensPath), herouiCss: readText(herouiPath) });
}

const HEX_TOKENS = [
  "--background", "--surface", "--surface-secondary", "--surface-tertiary", "--border", "--pw-line-strong",
  "--foreground", "--muted", "--pw-faint", "--accent", "--accent-foreground", "--pw-rec", "--pw-pb", "--pw-slower",
  "--pw-behind", "--warning", "--pw-ref", "--pw-synthetic", "--pw-sector-1", "--pw-sector-2", "--pw-sector-3",
];

function main(argv) {
  const all = argv.includes("--all");
  const { results, errors, ok } = checkFiles();
  if (argv.includes("--hex")) {
    const rules = [
      ...parseRules(readFileSync(DEFAULT_HEROUI_PATH, "utf8"), "heroui"),
      ...parseRules(readFileSync(DEFAULT_TOKENS_PATH, "utf8"), "tokens.css"),
    ];
    for (const mode of Object.keys(MODES)) {
      const { colour } = modeColours(rules, mode);
      console.log(`\n${mode}`);
      for (const t of HEX_TOKENS) {
        const c = colour(t);
        console.log(`  ${t.padEnd(22)} ${c ? hex(c) : "?"}`);
      }
    }
  }
  const pad = (s, n) => String(s).padEnd(n);
  let lastMode = "";
  for (const r of results) {
    if (!all && r.pass && !r.warn) continue;
    if (r.mode !== lastMode) console.log(`\n${r.mode}`);
    lastMode = r.mode;
    const flag = !r.pass ? "FAIL" : r.warn ? "warn" : "ok  ";
    const tgt = r.aim ? `${r.target} (aim ${r.aim})` : `${r.target}`;
    console.log(`  ${flag} ${r.ratio.toFixed(2).padStart(6)} >= ${pad(tgt, 12)} ${pad(r.fg, 26)} on ${pad(r.bg, 34)} ${r.fgHex} / ${r.bgHex}  ${r.what}`);
  }
  for (const e of errors) console.log(`ERROR ${e}`);
  const failed = results.filter((r) => !r.pass).length;
  const warned = results.filter((r) => r.warn).length;
  console.log(`\n${results.length} pairs in ${Object.keys(MODES).length} modes: ${failed} failed, ${warned} below the 7:1 glance aim, ${errors.length} errors`);
  return ok ? 0 : 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  process.exit(main(process.argv.slice(2)));
}
