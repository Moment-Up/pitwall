#!/usr/bin/env node
// THIRD_PARTY_NOTICES.txt for the compiled Pitwall dashboard (web-react/dist). Node built-ins only.
//
//   node web-react/scripts/notices.mjs --out <file>      # write the notices file
//   node web-react/scripts/notices.mjs --out - --quiet   # print it to stdout
//   options: --project <dir> (default: this script's web-react/), --no-npm-ls (skip the npm cross-check)
//
// What it covers: every production dependency installed in web-react/node_modules, with its name, version,
// licence and the text of its LICENSE / LICENCE / COPYING / NOTICE files, read from the installed package.
//   1. The dashboard's tree: from package.json `dependencies` + `optionalDependencies`, following each installed
//      package's own package.json (`dependencies`, `optionalDependencies` and the `peerDependencies` that are
//      installed), resolved like Node does (nearest node_modules first). The compiled dashboard contains code from
//      some or all of these.
//   2. Build-time only: the other production entries of package-lock.json that are installed but not reachable in
//      (1) - today the HeroUI Pro installer CLI (`heroui-pro`, run by @heroui-pro/react's postinstall) and its
//      dependencies. None of their code is in the dashboard; they are listed for completeness.
//   3. Cross-check: `npm ls --omit=dev --all --json` must succeed (node_modules matches the lockfile), and any
//      package it reports that (1) and (2) missed is added, with a warning.
//
// HeroUI Pro (@heroui-pro/*, and the `heroui-pro` installer) is commercial: only an attribution line is written.
// Only its package.json is read (name, version, dependencies); its licence and other files are never read or copied
// (its licence allows no extraction or redistribution outside the licensed application).
//
// Output is deterministic: packages sorted by name then version (code-point order), files by name, no timestamps;
// identical licence texts are printed once and referenced afterwards.

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, renameSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const RULE = "-".repeat(100);
const LICENCE_FILE = /^(licen[cs]e|copying|notice|copyright)([-._][^/\\]*)?$/i;
const CODE_FILE = /\.(c?js|mjs|tsx?|json|map|css|html?)$/i; // e.g. a notice.js module is not a notice
const NPM_LS = ["ls", "--omit=dev", "--all", "--json"];

/** Commercial HeroUI Pro packages: attribution line only, never their files. */
function isHeroUIPro(name) {
  return name === "heroui-pro" || name.startsWith("@heroui-pro/");
}

function proAttribution(name, version) {
  if (name === "@heroui-pro/react") {
    return `${name} ${version} is © NextUI Inc. It is used under licence and is not covered by Pitwall's terms.`;
  }
  if (name === "heroui-pro") {
    return (
      `${name} ${version} (the HeroUI Pro installer, run only while the dashboard is built; not part of the ` +
      `dashboard) is proprietary software by HeroUI / NextUI Inc. It is not covered by Pitwall's terms.`
    );
  }
  return `${name} ${version} is © NextUI Inc. (HeroUI Pro). It is used under licence and is not covered by Pitwall's terms.`;
}

function fail(msg) {
  process.stderr.write(`notices: error: ${msg}\n`);
  process.exit(1);
}

function warn(msg) {
  process.stderr.write(`notices: warning: ${msg}\n`);
}

function parseArgs(argv) {
  const opts = { out: null, project: resolve(HERE, ".."), npmLs: true, quiet: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const value = () => {
      const v = argv[++i];
      if (v === undefined) fail(`${a} needs a value`);
      return v;
    };
    if (a === "--out") opts.out = value();
    else if (a === "--project") opts.project = resolve(value());
    else if (a === "--no-npm-ls") opts.npmLs = false;
    else if (a === "--quiet") opts.quiet = true;
    else if (a === "-h" || a === "--help") {
      process.stdout.write("usage: node notices.mjs --out <file|-> [--project <dir>] [--no-npm-ls] [--quiet]\n");
      process.exit(0);
    } else fail(`unknown argument ${a}`);
  }
  if (!opts.out) fail("--out <file> is required (use - for stdout)");
  return opts;
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch (e) {
    fail(`cannot read ${path}: ${e instanceof Error ? e.message : e}`);
  }
}

const byCodePoint = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

function licenceOf(pkg) {
  if (typeof pkg.license === "string" && pkg.license.trim()) return pkg.license.trim();
  if (pkg.license && typeof pkg.license.type === "string") return pkg.license.type;
  if (Array.isArray(pkg.licenses)) {
    const types = pkg.licenses.map((l) => (typeof l === "string" ? l : l && l.type)).filter(Boolean);
    if (types.length) return types.length > 1 ? `(${types.join(" OR ")})` : types[0];
  }
  return "UNKNOWN";
}

// Licence texts recognised in a package's own (root) licence file. When package.json declares another licence, the
// label names both: @heroui/react and @heroui/styles declare "MIT" but ship the Apache-2.0 text (docs/licences.md).
const FILE_LICENCES = [["Apache-2.0", /^Apache License\s*\n\s*Version 2\.0, January 2004/]];

/** `declared` (package.json), or "MIT (package.json); LICENSE file: Apache-2.0" when the package's own licence file
 * states a different licence. Checked on every run, so the label follows upstream when it is fixed. */
function licenceLabel(declared, dir) {
  const root = licenceFiles(dir).filter((f) => !f.name.includes("/"));
  for (const [id, text] of FILE_LICENCES) {
    const file = root.find((f) => text.test(f.text));
    if (file && !declared.toLowerCase().includes(id.split("-")[0].toLowerCase())) {
      return `${declared} (package.json); ${file.name} file: ${id}`;
    }
  }
  return declared;
}

function sourceOf(pkg) {
  let url = typeof pkg.repository === "string" ? pkg.repository : pkg.repository && pkg.repository.url;
  if (typeof url === "string" && url) {
    url = url.trim();
    if (/^[\w.-]+\/[\w.-]+$/.test(url)) return `https://github.com/${url}`;
    const short = /^(github|gitlab|bitbucket):([\w.-]+\/[\w.-]+)$/.exec(url);
    if (short) return `https://${short[1]}.${short[1] === "bitbucket" ? "org" : "com"}/${short[2]}`;
    return url.replace(/^git\+/, "").replace(/^git:\/\//, "https://").replace(/^ssh:\/\/git@/, "https://").replace(/\.git$/, "");
  }
  return typeof pkg.homepage === "string" ? pkg.homepage : "";
}

/** Lockfile-style key ("node_modules/a/node_modules/@s/b") -> the package names along it (["a", "@s/b"]). */
function keyParts(key) {
  return key ? key.replace(/^node_modules\//, "").split("/node_modules/") : [];
}

/** Node's resolution from the package at `fromKey`: its own node_modules first, then each ancestor's. */
function resolveDep(project, fromKey, dep) {
  const parts = keyParts(fromKey);
  for (let i = parts.length; i >= 0; i--) {
    const prefix = parts.slice(0, i).map((p) => `node_modules/${p}`).join("/");
    const key = prefix ? `${prefix}/node_modules/${dep}` : `node_modules/${dep}`;
    if (existsSync(join(project, key, "package.json"))) return key;
  }
  return null;
}

/** The dashboard's production tree, walked over the installed package.json files. Map key -> package.json. */
function walkInstalled(project, rootPkg) {
  const seen = new Map();
  const queue = [];
  const enqueue = (fromKey, deps, kind, owner) => {
    for (const dep of Object.keys(deps || {}).sort(byCodePoint)) {
      const key = resolveDep(project, fromKey, dep);
      if (key === null) {
        if (kind === "dependencies") warn(`${owner} depends on ${dep}, which is not installed (skipped)`);
        continue;
      }
      if (!seen.has(key)) {
        seen.set(key, null);
        queue.push(key);
      }
    }
  };
  enqueue("", rootPkg.dependencies, "dependencies", "package.json");
  enqueue("", rootPkg.optionalDependencies, "optionalDependencies", "package.json");
  while (queue.length) {
    const key = queue.shift();
    const pkg = readJson(join(project, key, "package.json"));
    seen.set(key, pkg);
    const owner = `${pkg.name}@${pkg.version}`;
    enqueue(key, pkg.dependencies, "dependencies", owner);
    enqueue(key, pkg.optionalDependencies, "optionalDependencies", owner);
    enqueue(key, pkg.peerDependencies, "peerDependencies", owner);
  }
  return seen;
}

function runNpmLs(project) {
  const opts = { cwd: project, encoding: "utf8", maxBuffer: 256 * 1024 * 1024, stdio: ["ignore", "pipe", "pipe"] };
  let cmd = "npm";
  let args = NPM_LS;
  const execPath = process.env.npm_execpath;
  if (execPath && /\.c?js$/.test(execPath)) {
    cmd = process.execPath;
    args = [execPath, ...NPM_LS];
  } else if (process.platform === "win32") {
    opts.shell = true; // npm is npm.cmd on Windows
  }
  const r = spawnSync(cmd, args, opts);
  if (r.error) {
    warn(`could not run npm (${r.error.message}); skipping the npm ls cross-check`);
    return null;
  }
  let tree = null;
  try {
    tree = JSON.parse(r.stdout || "{}");
  } catch {
    tree = null;
  }
  if (tree && r.status !== 0) {
    // The HeroUI Pro postinstall adds its own CLI packages to node_modules after `npm ci`, so npm ls reports them
    // (extraneous / invalid / missing) and exits 1 even on a clean CI install. The notices come from package-lock.json
    // and the installed tree (steps 1-2); npm ls is only a cross-check, so its problems are warnings here.
    const problems = Array.isArray(tree.problems) ? tree.problems : [];
    warn(`npm ls reported ${problems.length} problem(s) (exit ${r.status}); continuing:\n  ${problems.join("\n  ")}`);
  }
  if (!tree) {
    const problems = (r.stderr || "").trim();
    fail(
      `\`npm ${NPM_LS.join(" ")}\` failed (exit ${r.status}): node_modules does not match package-lock.json.\n  ` +
        `${problems}\nRun \`npm ci\` in ${project} (or pass --no-npm-ls).`,
    );
  }
  const found = new Set();
  const visit = (deps) => {
    for (const [name, node] of Object.entries(deps || {})) {
      if (node && typeof node.version === "string" && !node.missing) found.add(`${name}@${node.version}`);
      visit(node && node.dependencies);
    }
  };
  visit(tree.dependencies);
  return found;
}

function readText(path) {
  return readFileSync(path, "utf8")
    .replace(/^\uFEFF/, "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+$/, ""))
    .join("\n")
    .trim();
}

/** Licence files of the package at `dir`: those at its root or, when it has none there, those in its sub-folders
 * (e.g. vendored code, depth <= 3; never a nested node_modules or dot-folder). [{ name: relative path, text }]. */
function licenceFiles(dir) {
  const listDir = (rel) => {
    try {
      return readdirSync(join(dir, rel), { withFileTypes: true }).sort((a, b) => byCodePoint(a.name, b.name));
    } catch {
      return [];
    }
  };
  const pick = (d) => d.isFile() && LICENCE_FILE.test(d.name) && !CODE_FILE.test(d.name);
  const read = (relPath) => ({ name: relPath, text: readText(join(dir, relPath)) });
  const root = listDir("").filter(pick).map((d) => read(d.name));
  if (root.length) return root;
  const deep = [];
  const walk = (rel, depth) => {
    for (const d of listDir(rel)) {
      const relPath = rel ? `${rel}/${d.name}` : d.name;
      if (rel && pick(d)) deep.push(read(relPath));
      else if (d.isDirectory() && depth < 3 && d.name !== "node_modules" && !d.name.startsWith(".")) walk(relPath, depth + 1);
    }
  };
  walk("", 0);
  return deep;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  const project = opts.project;
  const rootPkg = readJson(join(project, "package.json"));
  const lock = readJson(join(project, "package-lock.json"));
  if (!lock.packages || !(lock.lockfileVersion >= 2)) fail("package-lock.json must be lockfileVersion 2 or later");
  if (!existsSync(join(project, "node_modules"))) fail(`${project}/node_modules is missing: run \`npm ci\` first`);

  // 1. the dashboard's production tree (what the compiled dashboard can contain)
  const entries = new Map(); // "name@version" -> entry
  const add = (key, pkg, role) => {
    if (!pkg || typeof pkg.name !== "string" || typeof pkg.version !== "string") {
      warn(`${key}/package.json has no name or version (skipped)`);
      return;
    }
    const id = `${pkg.name}@${pkg.version}`;
    const prev = entries.get(id);
    if (prev) {
      if (role === "dashboard") prev.role = "dashboard";
      return;
    }
    const licence = isHeroUIPro(pkg.name) ? "commercial (HeroUI Pro)" : licenceLabel(licenceOf(pkg), join(project, key));
    const author = typeof pkg.author === "string" ? pkg.author : (pkg.author && pkg.author.name) || "";
    entries.set(id, { id, key, name: pkg.name, version: pkg.version, licence, author, source: sourceOf(pkg), role });
  };
  const tree = walkInstalled(project, rootPkg);
  for (const [key, pkg] of tree) add(key, pkg, "dashboard");

  // 2. other installed production entries of the lockfile (build-time only)
  for (const [key, meta] of Object.entries(lock.packages)) {
    if (!key || meta.dev || meta.devOptional || meta.link || tree.has(key)) continue;
    if (!/(^|\/)node_modules\//.test(key)) continue; // workspace folders, not installed packages
    const pj = join(project, key, "package.json");
    if (!existsSync(pj)) {
      if (!meta.optional) warn(`${key} is in package-lock.json but not installed (skipped)`);
      continue;
    }
    add(key, readJson(pj), "build");
  }

  // 3. cross-check with npm's own view of the production tree
  if (opts.npmLs) {
    const npmSet = runNpmLs(project);
    if (npmSet) {
      const lockKeys = Object.keys(lock.packages).sort(byCodePoint);
      for (const id of [...npmSet].sort(byCodePoint)) {
        if (entries.has(id)) continue;
        const at = id.lastIndexOf("@");
        const name = id.slice(0, at);
        const version = id.slice(at + 1);
        const key = lockKeys.find((k) => {
          if (!(k === `node_modules/${name}` || k.endsWith(`/node_modules/${name}`))) return false;
          const pj = join(project, k, "package.json");
          return existsSync(pj) && readJson(pj).version === version;
        });
        if (!key) {
          warn(`npm ls lists ${id} but it was not found in node_modules (skipped)`);
          continue;
        }
        warn(`npm ls lists ${id} as a production dependency; added (not reached from the dashboard's own tree)`);
        add(key, readJson(join(project, key, "package.json")), "build");
      }
    }
  }

  const list = [...entries.values()].sort((a, b) => byCodePoint(a.name, b.name) || byCodePoint(a.version, b.version));
  if (!list.some((e) => e.name === "react")) fail("react is not among the production dependencies - wrong --project?");
  const pro = list.filter((e) => isHeroUIPro(e.name));
  const open = list.filter((e) => !isHeroUIPro(e.name));
  for (const e of open) {
    if (/^(UNLICENSED|UNKNOWN)$/i.test(e.licence) || /SEE LICEN[CS]E IN/i.test(e.licence)) {
      warn(`${e.id} declares licence "${e.licence}" - check it before releasing`);
    }
  }

  // ------------------------------------------------------------------------------------------- render
  const counts = new Map();
  for (const e of list) counts.set(e.licence, (counts.get(e.licence) || 0) + 1);
  const licenceSummary = [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || byCodePoint(a[0], b[0]))
    .map(([l, n]) => `${l} ${n}`)
    .join(", ");
  const nDashboard = list.filter((e) => e.role === "dashboard").length;
  const nBuild = list.length - nDashboard;

  const out = [];
  out.push("THIRD-PARTY NOTICES - Pitwall dashboard (web-react/dist)");
  out.push("=".repeat(100));
  out.push("");
  out.push("The Pitwall dashboard in this release is compiled (bundled and minified) from Pitwall's own code and");
  out.push("third-party packages. Each third-party package is used under its own licence, reproduced below; those");
  out.push("licences, not Pitwall's terms, apply to the packages.");
  out.push("");
  out.push("HeroUI Pro");
  out.push(RULE);
  for (const e of pro) out.push(proAttribution(e.name, e.version));
  if (!pro.length) out.push("(not installed)");
  out.push("HeroUI Pro's own files and licence text are not reproduced here, and nothing in this release grants any");
  out.push("right to use, extract or redistribute HeroUI Pro separately from the Pitwall application.");
  out.push("");
  out.push("Summary");
  out.push(RULE);
  out.push(`${list.length} production packages installed for the dashboard build (package-lock.json lockfileVersion ${lock.lockfileVersion}):`);
  out.push(`  ${nDashboard} in the dashboard's dependency tree: the compiled dashboard contains code from some or all of them;`);
  out.push(`  ${nBuild} used only while building (marked "build only"): none of their code is in the dashboard.`);
  out.push(`Licences: ${licenceSummary}.`);
  out.push("");
  out.push("Index");
  out.push(RULE);
  const w1 = Math.max(...list.map((e) => e.name.length));
  const w2 = Math.max(...list.map((e) => e.version.length));
  for (const e of list) {
    const tag = e.role === "build" ? "  [build only]" : "";
    out.push(`${e.name.padEnd(w1)}  ${e.version.padEnd(w2)}  ${e.licence}${tag}`.trimEnd());
  }
  out.push("");
  out.push("Licence texts");
  out.push("=".repeat(100));
  const firstSeen = new Map(); // text -> "name version"
  let missingFiles = 0;
  for (const e of list) {
    out.push("");
    out.push(RULE);
    out.push(`${e.name} ${e.version}${e.role === "build" ? " [build only]" : ""}`);
    out.push(`Licence: ${e.licence}`);
    if (e.source) out.push(`Source: ${e.source}`);
    if (isHeroUIPro(e.name)) {
      out.push(proAttribution(e.name, e.version));
      continue;
    }
    const files = licenceFiles(join(project, e.key));
    if (!files.length) {
      missingFiles++;
      out.push(`The package includes no licence file; its package.json declares the licence as ${e.licence}.`);
      if (e.author) out.push(`Declared author: ${e.author}`);
      continue;
    }
    for (const f of files) {
      const prev = firstSeen.get(f.text);
      if (prev) {
        out.push(`[${f.name}] Same text as ${prev} above.`);
      } else {
        firstSeen.set(f.text, `${f.name} of ${e.name} ${e.version}`);
        out.push("");
        out.push(`[${f.name}]`);
        out.push(f.text);
      }
    }
  }
  out.push("");
  const text = `${out.join("\n")}\n`;

  if (opts.out === "-") {
    process.stdout.write(text);
  } else {
    const dest = resolve(opts.out);
    mkdirSync(dirname(dest), { recursive: true });
    const tmp = `${dest}.tmp-${process.pid}`;
    writeFileSync(tmp, text, "utf8");
    renameSync(tmp, dest);
  }
  if (!opts.quiet) {
    process.stderr.write(
      `notices: ${list.length} packages (${nDashboard} dashboard, ${nBuild} build only; ${pro.length} HeroUI Pro ` +
        `attribution-only; ${missingFiles} without a licence file) -> ${opts.out === "-" ? "stdout" : resolve(opts.out)}\n`,
    );
  }
}

main();
