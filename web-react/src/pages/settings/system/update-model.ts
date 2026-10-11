// Settings › System › Updates: pure wording for the update status (lane install, spec §8; unit-tested in
// update-model.test.ts). The card (UpdateCard.tsx) only lays this out.
//
// Rules: the server decides whether an update exists (`update_available`); the page never compares versions itself.
// Release notes are shown as plain text, and a link is only offered when it points at Pitwall's own GitHub releases.
// There is no "Update now": updating runs on the computer running Pitwall (`uv run pitwall update`).

import { ago } from "../../../lib/format";
import type { ReleaseInfo, UpdateStatus } from "../../../lib/endpoints/update";

/** Release pages the card may link to. Anything else (a tampered cache, another host) is not shown as a link. */
export const RELEASES_URL_PREFIX = "https://github.com/Moment-Up/pitwall/releases/";
/** The install guide's "Updating" section (also the fallback when the server sends no usable docs link). */
export const DOCS_URL = "https://github.com/Moment-Up/pitwall/blob/main/docs/install.md#updating";
const DOCS_URL_PREFIX = "https://github.com/Moment-Up/pitwall/";
/** "What changed" items shown before "Show all n". */
export const NOTES_SHOWN = 6;

export const HOW_HELP =
  "Run it in Terminal (PowerShell on Windows) on the computer running Pitwall, between sessions. It checks the " +
  "download, keeps your data and settings, and restarts the background service if you use one.";
export const GIT_LINE = "This copy is a git checkout: update it with git pull.";
export const UNKNOWN_KIND_LINE = "Pitwall can't tell how this copy was installed, so it can't update it for you. The install guide explains how.";
export const CARD_DESCRIPTION = "New versions of Pitwall from GitHub. Updating never touches your sessions or settings.";

export type UpdateState = "checking" | "available" | "up-to-date" | "failed" | "off" | "never";
export type UpdateTone = "success" | "warning" | "default";

export const LABELS: Readonly<Record<UpdateState, string>> = {
  checking: "Checking…",
  available: "Update available",
  "up-to-date": "Up to date",
  failed: "Couldn't check",
  off: "Checks off",
  never: "Not checked yet",
};

/** Green only for "up to date"; amber when this copy is behind; everything else neutral (the words say why). */
const TONES: Readonly<Record<UpdateState, UpdateTone>> = {
  checking: "default",
  available: "warning",
  "up-to-date": "success",
  failed: "default",
  off: "default",
  never: "default",
};

export interface ReleaseView {
  version: string;
  prerelease: boolean;
  /** "12 Oct 2026", or null when GitHub did not say. */
  date: string | null;
  /** "v0.2.0 (released 12 Oct 2026)". */
  title: string;
  notes: string[];
  /** Only a Pitwall release page, else null. */
  url: string | null;
}

export interface UpdateView {
  state: UpdateState;
  tone: UpdateTone;
  label: string;
  /** One or two plain sentences under the status. */
  line: string;
  /** The latest release's "What changed" items (available only). */
  notes: string[];
  /** Releases newer than this copy, newest first (available only). */
  releases: ReleaseView[];
  /** What to run to update (managed or release installs, when there is something to do); null otherwise. */
  command: string | null;
  /** The heading above the command. */
  commandIntro: string | null;
  /** How this copy updates when there is no command: a git checkout, or a copy Pitwall cannot place. */
  howNote: string | null;
  isGit: boolean;
  /** The latest release's page (available only), when it is a Pitwall release page. */
  releaseUrl: string | null;
  docsUrl: string;
  /** "Last checked 3 h ago"; null when never checked. */
  checked: string | null;
  /** "Check now" is offered (not when checks are off). */
  canCheck: boolean;
}

const DATE_FMT = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

/** "12 Oct 2026" (UTC, like `pitwall update`), or null for a missing or unreadable date. */
export function releaseDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? DATE_FMT.format(t) : null;
}

/** A release page link, only when it is one of Pitwall's own. */
export function safeReleaseUrl(url: string | null | undefined): string | null {
  return typeof url === "string" && url.startsWith(RELEASES_URL_PREFIX) && !/\s/.test(url) ? url : null;
}

function safeDocsUrl(url: string | null | undefined): string {
  return typeof url === "string" && url.startsWith(DOCS_URL_PREFIX) && !/\s/.test(url) ? url : DOCS_URL;
}

/**
 * "3 h ago" through format.ago() (which reads the clock itself): the timestamp is shifted by the difference between
 * the clock and `nowUnix`, so the result depends on `nowUnix` only. Older than a day: "on 12 Oct 2026".
 */
export function checkedAgo(checkedUnix: number, nowUnix: number): string {
  if (nowUnix - checkedUnix >= 86_400) return `on ${DATE_FMT.format(checkedUnix * 1000)}`;
  return ago(checkedUnix + (Date.now() / 1000 - nowUnix));
}

function releaseView(r: ReleaseInfo): ReleaseView {
  const date = releaseDate(r.published_at);
  return {
    version: r.version,
    prerelease: r.prerelease,
    date,
    title: `${r.version} (${date ? `released ${date}` : "release date not stated"})`,
    notes: r.notes,
    url: safeReleaseUrl(r.url),
  };
}

const sentence = (s: string): string => {
  const t = s.trim();
  return /[.!?…]$/.test(t) ? t : `${t}.`;
};

export function stateOf(s: UpdateStatus): UpdateState {
  if (s.checking) return "checking";
  if (s.update_available === true) return "available";
  if (s.update_available === false) return "up-to-date";
  if (s.error) return "failed";
  if (s.mode === "off") return "off";
  return "never";
}

/** Everything the Updates card shows, from the server's status. `nowUnix` is the browser's clock in seconds. */
export function updateView(s: UpdateStatus, nowUnix: number): UpdateView {
  const state = stateOf(s);
  const isGit = s.install_kind === "git";
  const youHave = s.current ? ` You have ${s.current}.` : "";
  // The releases stay on screen while a new check runs (no flicker every 2 s); they go when the server says otherwise.
  const hasUpdate = s.update_available === true;
  const newer = hasUpdate ? (s.newer.length ? s.newer : s.latest ? [s.latest] : []) : [];
  const releases = newer.map(releaseView);
  const top = releases[0] ?? null;

  let line: string;
  switch (state) {
    case "available":
      line = top ? `${top.title}.${youHave}` : `A newer release is out.${youHave}`;
      break;
    case "up-to-date":
      if (s.current && s.latest?.version === s.current) line = `You have ${s.current}, the latest release.`;
      else line = `There is no newer release.${youHave}`;
      break;
    case "checking":
      line = `Asking GitHub for the latest release…${youHave}`;
      break;
    case "failed":
      line = `${sentence(s.error ?? "The last check failed")}${youHave}`;
      break;
    case "off":
      line = `Pitwall doesn't look for new versions: checks are turned off (PITWALL_UPDATE_CHECK=off).${youHave}`;
      break;
    case "never":
      line =
        s.mode === "auto"
          ? `Pitwall looks for a new version once a day, while no game is sending telemetry.${youHave}`
          : `Press Check now to look for a new version on GitHub.${youHave}`;
      break;
  }

  // The command only where it does something useful: to update, or (checks off) to check by hand. A git checkout
  // updates with git; a copy Pitwall cannot place gets the install guide.
  const updatable = (s.install_kind === "managed" || s.install_kind === "release") && s.how !== null;
  let command: string | null = null;
  let commandIntro: string | null = null;
  let howNote: string | null = isGit ? GIT_LINE : null;
  if (updatable && s.how && (hasUpdate || state === "off")) {
    command = s.how.command;
    commandIntro = hasUpdate ? "How to update" : "To check and update by hand";
  } else if (!isGit && !updatable && (hasUpdate || state === "off")) {
    howNote = UNKNOWN_KIND_LINE;
  }

  return {
    state,
    tone: TONES[state],
    label: LABELS[state],
    line,
    notes: top?.notes ?? [],
    releases,
    command,
    commandIntro,
    howNote,
    isGit,
    releaseUrl: top?.url ?? null,
    docsUrl: safeDocsUrl(s.how?.docs_url),
    checked: s.checked_unix !== null ? `Last checked ${checkedAgo(s.checked_unix, nowUnix)}` : null,
    canCheck: s.mode !== "off",
  };
}

/** The Version row's "Update available" chip. */
export function showUpdateChip(s: UpdateStatus | undefined): boolean {
  return s?.update_available === true;
}

/** The notes to list for one release: the first NOTES_SHOWN unless expanded. */
export function shownNotes(notes: readonly string[], expanded: boolean): { items: readonly string[]; hidden: number } {
  if (expanded || notes.length <= NOTES_SHOWN) return { items: notes, hidden: 0 };
  return { items: notes.slice(0, NOTES_SHOWN), hidden: notes.length - NOTES_SHOWN };
}
