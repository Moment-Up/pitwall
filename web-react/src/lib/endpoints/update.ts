// Update status (lane install, spec §7): typed client for GET /api/update and POST /api/update/check
// (src/pitwall/api/routes_update.py, the status computed by src/pitwall/install/check.py from
// <data_dir>/update_check.json). Settings › System shows it (pages/settings/system/UpdateCard.tsx); Drive, the shell and
// the nav never do.
//
// The dashboard only READS the update status and can ask the server to look again ("Check now"). It never installs
// anything: updating is `uv run pitwall update` on the computer running Pitwall, so a device on the network can never
// trigger a code change. With PITWALL_UPDATE_CHECK=off the server never contacts GitHub and POST /check answers 409.
// An older server has no /api/update (404): the card then renders nothing.

import { authFetch } from "../auth";
import { EndpointError, errorText } from "./settings";

export type InstallKind = "managed" | "release" | "git" | "unknown";
export type UpdateMode = "auto" | "manual" | "off";

export interface ReleaseInfo {
  /** The release tag, e.g. "v0.2.0" or "v0.3.0-rc.1". */
  version: string;
  /** ISO 8601 from GitHub; null when not stated. */
  published_at: string | null;
  url: string;
  prerelease: boolean;
  /** The "What changed" list items of the release notes (plain text, at most 20, each at most 200 characters). */
  notes: string[];
}

export interface UpdateHow {
  /** What to run on the computer running Pitwall (`cd "<root>" && uv run pitwall update`, or `git pull`). */
  command: string;
  folder: string | null;
  docs_url: string;
}

/** GET /api/update (and the answer of POST /api/update/check). */
export interface UpdateStatus {
  schema: 1;
  /** The running version, e.g. "v0.1.0". */
  current: string;
  install_kind: InstallKind;
  mode: UpdateMode;
  checked_unix: number | null;
  checking: boolean;
  /** null = never checked, the last check failed, or checks are off. */
  update_available: boolean | null;
  latest: ReleaseInfo | null;
  /** Releases newer than `current`, newest first, at most 5. */
  newer: ReleaseInfo[];
  /** A plain sentence, e.g. "Couldn't reach GitHub (timed out)." */
  error: string | null;
  how: UpdateHow | null;
}

/** Request-cache key (src/lib/cache.ts). */
export const UPDATE_KEY = "update";

async function call(path: string, init?: RequestInit): Promise<unknown> {
  const r = await authFetch(path, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      detail = errorText(((await r.json()) as { detail?: unknown }).detail, detail);
    } catch {
      /* not json */
    }
    throw new EndpointError(r.status, detail || `HTTP ${r.status}`);
  }
  return r.json() as Promise<unknown>;
}

// ---------------------------------------------------------------------------------------------- parsing

const KINDS: readonly InstallKind[] = ["managed", "release", "git", "unknown"];
const MODES: readonly UpdateMode[] = ["auto", "manual", "off"];

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function release(v: unknown): ReleaseInfo | null {
  if (!isObj(v)) return null;
  const version = str(v.version);
  if (!version) return null;
  return {
    version,
    published_at: str(v.published_at),
    url: str(v.url) ?? "",
    prerelease: v.prerelease === true,
    notes: Array.isArray(v.notes) ? v.notes.filter((n): n is string => typeof n === "string" && n.trim() !== "") : [],
  };
}

/**
 * The server's answer as an UpdateStatus. Tolerant of a newer or older server: missing lists become [], unknown
 * words become "unknown" / "manual", and a value that is not there stays null (never guessed).
 */
export function parseUpdateStatus(raw: unknown): UpdateStatus {
  const o = isObj(raw) ? raw : {};
  const kind = KINDS.find((k) => k === o.install_kind) ?? "unknown";
  const mode = MODES.find((m) => m === o.mode) ?? "manual";
  const how = isObj(o.how) && str(o.how.command)
    ? { command: String(o.how.command), folder: str(o.how.folder), docs_url: str(o.how.docs_url) ?? "" }
    : null;
  return {
    schema: 1,
    current: str(o.current) ?? "",
    install_kind: kind,
    mode,
    checked_unix: num(o.checked_unix),
    checking: o.checking === true,
    update_available: typeof o.update_available === "boolean" ? o.update_available : null,
    latest: release(o.latest),
    newer: Array.isArray(o.newer) ? o.newer.map(release).filter((r): r is ReleaseInfo => r !== null) : [],
    error: str(o.error),
    how,
  };
}

// ---------------------------------------------------------------------------------------------- calls

export const updateApi = {
  /** The cached status; with PITWALL_UPDATE_CHECK=auto the server may start a background check (once a day, never
   * while telemetry is live). */
  status: async (): Promise<UpdateStatus> => parseUpdateStatus(await call("/api/update")),
  /** Ask the server to check GitHub now. Answers the current status (`checking: true` while it runs); 409 when checks
   * are off. JSON body: the server refuses JSON-less POSTs (cross-site protection). */
  check: async (): Promise<UpdateStatus> =>
    parseUpdateStatus(
      await call("/api/update/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }),
    ),
};

/** An older server without /api/update. */
export function isNotFound(e: unknown): boolean {
  return e instanceof EndpointError && e.status === 404;
}
