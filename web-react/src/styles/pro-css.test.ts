// index.css imports only the HeroUI Pro stylesheets the app renders, not the whole `@heroui-pro/react/css` bundle (68
// stylesheets, ~370 KB, mostly unused: a bigger sheet makes every style recalculation slower on the iPad at 20 Hz).
// Guard rails: every Pro component imported in src has its stylesheet, plus the stylesheets of the Pro components it
// renders internally; no Pro stylesheet is imported that nothing renders; each one goes into the `components` layer.
import { describe, expect, it } from "vitest";

type Fs = {
  readFileSync(p: URL, enc: "utf8"): string;
  readdirSync(p: URL): string[];
  existsSync(p: URL): boolean;
};
// vitest serves CSS imports empty, so files are read from disk (node:fs through the process object, as coach.test.ts).
const fs = (globalThis as unknown as { process: { getBuiltinModule(id: "node:fs"): Fs } }).process.getBuiltinModule(
  "node:fs",
);

const PRO_DIST = new URL("../../node_modules/@heroui-pro/react/dist/", import.meta.url);
const INDEX_CSS = fs.readFileSync(new URL("./index.css", import.meta.url), "utf8");
const SOURCES = import.meta.glob<string>(["../**/*.ts", "../**/*.tsx", "!../**/*.test.ts", "!../**/*.test.tsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** Stylesheets a Pro component needs that its JS does not import from another Pro component. */
const EXTRA_CSS: Record<string, string[]> = {
  // DataGrid renders HeroUI's Table; Pro's table.css adjusts it (last row border).
  "data-grid": ["table"],
};

/**
 * Stylesheets imported ahead of the file that will use them (spec-mapped Pro components another lane is building).
 * Allowed unused only while that file does not exist; once it does, the normal rule applies, so an entry whose file
 * landed without the component fails "imports no Pro stylesheet that nothing renders". Remove entries as they land.
 */
const PLANNED: Record<string, string> = {
  // e.g. command: "components/shell/CommandPalette.tsx" (stylesheet name: the file that will render it)
};
const sourceExists = (path: string): boolean => Object.keys(SOURCES).some((k) => k.endsWith(`/${path}`));

/** A regex group, "" when it did not take part (noUncheckedIndexedAccess). */
const group = (m: RegExpMatchArray, i: number): string => m[i] ?? "";
/** The part of `s` before the first `sep`. */
const head = (s: string, sep: string | RegExp): string => s.split(sep)[0] ?? "";

const cssExists = (name: string): boolean => fs.existsSync(new URL(`css/components/${name}.css`, PRO_DIST));

/** Root export name -> component folder, from dist/index.js (`export{ActionBar}from"./components/action-bar/..."`). */
function rootExports(): Map<string, string> {
  const js = fs.readFileSync(new URL("index.js", PRO_DIST), "utf8");
  const out = new Map<string, string>();
  for (const m of js.matchAll(/export\{([^}]*)\}from"\.\/components\/([a-z0-9-]+)\//g)) {
    for (const name of group(m, 1).split(",")) out.set(name.trim().split(/\s+as\s+/).pop() ?? "", group(m, 2));
  }
  return out;
}

/** Pro component folders the app's sources import (named imports from the root or a component subpath). */
function importedFolders(): Map<string, string[]> {
  const exports = rootExports();
  const used = new Map<string, string[]>();
  const add = (dir: string, file: string) => used.set(dir, [...(used.get(dir) ?? []), file]);
  for (const [file, text] of Object.entries(SOURCES)) {
    for (const m of text.matchAll(/import\s+(type\s+)?\{([^}]*)\}\s+from\s+"@heroui-pro\/react(?:\/([a-z0-9-]+))?"/g)) {
      if (m[1]) continue;
      const names = group(m, 2)
        .split(",")
        .map((n) => n.trim())
        .filter((n) => n && !n.startsWith("type "))
        .map((n) => head(n, /\s+as\s+/));
      if (names.length === 0) continue;
      if (m[3]) add(group(m, 3), file);
      else
        for (const n of names) {
          const dir = exports.get(n);
          if (dir) add(dir, file);
        }
    }
  }
  return used;
}

/** Pro component folders a folder's JS imports (`from"../area-chart/index.js"`), transitively. */
function withInternalDeps(dirs: Iterable<string>): Set<string> {
  const seen = new Set<string>();
  const queue = [...dirs];
  while (queue.length) {
    const dir = queue.pop() as string;
    if (seen.has(dir)) continue;
    seen.add(dir);
    const folder = new URL(`components/${dir}/`, PRO_DIST);
    if (!fs.existsSync(folder)) continue;
    for (const f of fs.readdirSync(folder).filter((n) => n.endsWith(".js"))) {
      const js = fs.readFileSync(new URL(f, folder), "utf8");
      for (const m of js.matchAll(/from\s*"\.\.\/([a-z0-9-]+)\//g)) queue.push(group(m, 1));
    }
  }
  return seen;
}

/** Pro block classes written directly in className strings (e.g. `chart-tooltip` in a custom Recharts tooltip). */
function classReferenced(): Set<string> {
  const out = new Set<string>();
  for (const text of Object.values(SOURCES)) {
    for (const m of text.matchAll(/className=\{?\s*["`]([^"`]*)["`]/g)) {
      for (const token of group(m, 1).split(/[\s${}]+/)) {
        const block = head(head(token, "__"), "--");
        if (/^[a-z][a-z0-9-]*$/.test(block) && cssExists(block)) out.add(block);
      }
    }
  }
  return out;
}

const PRO_IMPORT = /@import\s+"@heroui-pro\/react\/css\/components\/([a-z0-9-]+)\.css"([^;]*);/g;
const imported = [...INDEX_CSS.matchAll(PRO_IMPORT)].map((m) => ({ name: group(m, 1), rest: group(m, 2).trim() }));
const folders = importedFolders();

function required(): Set<string> {
  const dirs = withInternalDeps(folders.keys());
  const css = new Set<string>();
  for (const d of dirs) {
    for (const name of [d, ...(EXTRA_CSS[d] ?? [])]) if (cssExists(name)) css.add(name);
  }
  for (const c of classReferenced()) css.add(c);
  return css;
}

describe("HeroUI Pro stylesheets in index.css (only what the app renders)", () => {
  it("does not import the whole Pro bundle", () => {
    expect(INDEX_CSS).not.toMatch(/@import\s+"@heroui-pro\/react\/css"\s*;/);
    expect(imported.length).toBeGreaterThan(0);
  });

  it("finds the Pro components the app uses (sanity check of the scan)", () => {
    expect([...folders.keys()]).toEqual(expect.arrayContaining(["segment", "list-view", "kpi", "data-grid"]));
  });

  it("imports the stylesheet of every Pro component the app renders, and of the ones those render inside", () => {
    const have = new Set(imported.map((i) => i.name));
    const missing = [...required()].filter((n) => !have.has(n)).sort();
    expect(missing, "add these to src/styles/index.css with layer(components)").toEqual([]);
  });

  it("imports no Pro stylesheet that nothing renders", () => {
    const need = required();
    const pending = (n: string): boolean => n in PLANNED && !sourceExists(PLANNED[n] ?? "");
    const unused = imported.map((i) => i.name).filter((n) => !need.has(n) && !pending(n));
    expect(unused, "remove these from src/styles/index.css").toEqual([]);
  });

  it("imports each stylesheet once, into the components layer (where the bundle put them)", () => {
    const names = imported.map((i) => i.name);
    expect(new Set(names).size).toBe(names.length);
    for (const i of imported) expect(i.rest, i.name).toBe("layer(components)");
  });
});
