import { describe, expect, it } from "vitest";
import {
  DOCS_URL,
  GIT_LINE,
  LABELS,
  NOTES_SHOWN,
  UNKNOWN_KIND_LINE,
  checkedAgo,
  releaseDate,
  safeReleaseUrl,
  showUpdateChip,
  shownNotes,
  stateOf,
  updateView,
} from "./update-model";
import { parseUpdateStatus } from "../../../lib/endpoints/update";
import { NOW, rawUpdateFixture, updateFixture, updateFixtureBlocks } from "./update-testkit";

describe("fixtures", () => {
  it("each says where it came from; contract fixtures are not presented as server output", () => {
    const blocks = updateFixtureBlocks();
    expect(blocks.length).toBeGreaterThanOrEqual(8);
    for (const { name, block } of blocks) {
      expect(block.source, name).toBeTruthy();
      expect(block.what, name).toBeTruthy();
      expect(name.startsWith(`${block.tier}-`), name).toBe(true);
    }
  });

  it("every fixture already has the contract's shape (the parser changes nothing), the real server's included", () => {
    for (const n of ["contract-available", "contract-off", "contract-git", "server-git-never", "server-git-available"] as const) {
      expect(parseUpdateStatus(rawUpdateFixture(n)), n).toEqual(rawUpdateFixture(n));
    }
  });

  it("the real server's answers read as expected: never checked, then one release behind (a git checkout)", () => {
    const never = updateView(updateFixture("server-git-never"), NOW);
    expect([never.state, never.label, never.isGit, never.command]).toEqual(["never", "Not checked yet", true, null]);
    expect(never.line).toBe("Press Check now to look for a new version on GitHub. You have v0.1.0.");
    const s = updateFixture("server-git-available");
    const v = updateView(s, (s.checked_unix ?? 0) + 120);
    expect(v.label).toBe("Update available");
    expect(v.line).toBe("v0.2.0 (released 12 Oct 2026). You have v0.1.0.");
    expect(v.releases.map((r) => r.version)).toEqual(["v0.2.0"]); // no pre-release, draft or zip-less release
    expect(v.notes[0]).toBe("One-line installers for macOS, Linux and Windows (docs)");
    expect(v.releaseUrl).toBe("https://github.com/Moment-Up/pitwall/releases/tag/v0.2.0");
    expect(v.howNote).toBe(GIT_LINE);
    expect(v.checked).toBe("Last checked 2 min ago");
  });
});

describe("dates and times", () => {
  it("release dates: 12 Oct 2026 (en-GB, UTC like the CLI); missing or unreadable is null", () => {
    expect(releaseDate("2026-10-12T09:30:00Z")).toBe("12 Oct 2026");
    expect(releaseDate("2026-10-12T23:30:00-05:00")).toBe("13 Oct 2026");
    expect(releaseDate(null)).toBeNull();
    expect(releaseDate("")).toBeNull();
    expect(releaseDate("not a date")).toBeNull();
  });

  it("checked: format.ago() wording against the given clock; over a day, the date", () => {
    expect(checkedAgo(NOW - 20, NOW)).toBe("just now");
    expect(checkedAgo(NOW - 5 * 60 - 10, NOW)).toBe("5 min ago");
    expect(checkedAgo(NOW - 3 * 3600 - 10, NOW)).toBe("3 h ago");
    expect(checkedAgo(NOW - 2 * 86_400, NOW)).toBe("on 10 Oct 2026");
    expect(checkedAgo(NOW + 30, NOW)).toBe("just now"); // a server clock slightly ahead
  });
});

describe("safe links", () => {
  it.each([
    ["https://github.com/Moment-Up/pitwall/releases/tag/v0.2.0", true],
    ["https://github.com/Moment-Up/pitwall/releases/download/v0.2.0/pitwall-v0.2.0.zip", true],
    ["http://github.com/Moment-Up/pitwall/releases/tag/v0.2.0", false],
    ["https://github.com/Moment-Up/pitwall-evil/releases/tag/v0.2.0", false],
    ["https://github.com/Moment-Up/pitwall/releases", false],
    ["https://evil.example/https://github.com/Moment-Up/pitwall/releases/", false],
    ["javascript:alert(1)//https://github.com/Moment-Up/pitwall/releases/", false],
    ["https://github.com/Moment-Up/pitwall/releases/tag/v0.2.0 onclick=x", false],
    ["", false],
  ])("%s -> %s", (url, ok) => {
    expect(safeReleaseUrl(url)).toBe(ok ? url : null);
  });

  it("a docs link that is not Pitwall's falls back to the install guide", () => {
    const v = updateView(updateFixture("contract-git", { how: { command: "git pull", folder: null, docs_url: "https://evil.example/" } }), NOW);
    expect(v.docsUrl).toBe(DOCS_URL);
    expect(updateView(updateFixture("contract-available"), NOW).docsUrl).toBe(DOCS_URL);
  });
});

describe("updateView: every state", () => {
  it("labels are the spec's words", () => {
    expect(Object.values(LABELS)).toEqual(["Checking…", "Update available", "Up to date", "Couldn't check", "Checks off", "Not checked yet"]);
  });

  it("available: the latest release with its date, what you have, notes, the command, the release page", () => {
    const v = updateView(updateFixture("contract-available"), NOW);
    expect(v.state).toBe("available");
    expect(v.tone).toBe("warning");
    expect(v.label).toBe("Update available");
    expect(v.line).toBe("v0.2.0 (released 12 Oct 2026). You have v0.1.0.");
    expect(v.notes).toHaveLength(8);
    expect(v.releases.map((r) => r.version)).toEqual(["v0.2.0"]);
    expect(v.command).toBe('cd "/Users/you/Pitwall/pitwall-v0.1.0" && uv run pitwall update');
    expect(v.commandIntro).toBe("How to update");
    expect(v.howNote).toBeNull();
    expect(v.isGit).toBe(false);
    expect(v.releaseUrl).toBe("https://github.com/Moment-Up/pitwall/releases/tag/v0.2.0");
    expect(v.checked).toBe("Last checked 3 h ago");
    expect(v.canCheck).toBe(true);
  });

  it("available, several releases: newest first; a missing date and an empty list are said in words", () => {
    const v = updateView(updateFixture("contract-available-several"), NOW);
    expect(v.line).toBe("v0.3.0 (released 2 Nov 2026). You have v0.1.0.");
    expect(v.releases.map((r) => [r.version, r.title, r.notes.length])).toEqual([
      ["v0.3.0", "v0.3.0 (released 2 Nov 2026)", 3],
      ["v0.2.1", "v0.2.1 (release date not stated)", 0],
      ["v0.2.0", "v0.2.0 (released 12 Oct 2026)", 8],
    ]);
    expect(v.notes).toEqual(["Track maps for every F1 25 circuit", "Faster session list", "Fixes for the GT7 adapter"]);
  });

  it("available with an unsafe release URL: no link; a missing `newer` list falls back to `latest`", () => {
    const s = updateFixture("contract-available");
    s.newer = [];
    s.latest = { ...s.latest!, url: "https://evil.example/pitwall/releases/tag/v0.2.0" };
    const v = updateView(s, NOW);
    expect(v.releases.map((r) => r.version)).toEqual(["v0.2.0"]);
    expect(v.releaseUrl).toBeNull();
    expect(v.releases[0]?.url).toBeNull();
  });

  it("available, Windows: the server's PowerShell command is shown as it is", () => {
    const cmd = 'cd "C:\\Users\\you\\AppData\\Local\\Pitwall\\pitwall-v0.1.0"; uv run pitwall update';
    const v = updateView(updateFixture("contract-available", { how: { command: cmd, folder: null, docs_url: DOCS_URL } }), NOW);
    expect(v.command).toBe(cmd);
  });

  it("up to date: green, no releases, no command", () => {
    const v = updateView(updateFixture("contract-up-to-date"), NOW);
    expect([v.state, v.tone, v.label]).toEqual(["up-to-date", "success", "Up to date"]);
    expect(v.line).toBe("You have v0.2.0, the latest release.");
    expect(v.releases).toEqual([]);
    expect(v.command).toBeNull();
    expect(v.releaseUrl).toBeNull();
  });

  it("up to date ahead of the latest release (a pre-release build)", () => {
    const v = updateView(updateFixture("contract-up-to-date", { current: "v0.3.0-rc.1" }), NOW);
    expect(v.line).toBe("There is no newer release. You have v0.3.0-rc.1.");
  });

  it("never checked: auto says when it will look; manual says how to look", () => {
    const auto = updateView(updateFixture("contract-never-auto"), NOW);
    expect([auto.state, auto.tone, auto.label]).toEqual(["never", "default", "Not checked yet"]);
    expect(auto.line).toBe("Pitwall looks for a new version once a day, while no game is sending telemetry. You have v0.1.0.");
    expect(auto.checked).toBeNull();
    expect(auto.canCheck).toBe(true);
    const manual = updateView(updateFixture("contract-never-auto", { mode: "manual" }), NOW);
    expect(manual.line).toBe("Press Check now to look for a new version on GitHub. You have v0.1.0.");
  });

  it("checking: its own label; an update already known stays listed meanwhile (no flicker)", () => {
    const v = updateView(updateFixture("contract-checking"), NOW);
    expect([v.state, v.label]).toEqual(["checking", "Checking…"]);
    expect(v.line).toBe("Asking GitHub for the latest release… You have v0.1.0.");
    const again = updateView(updateFixture("contract-available", { checking: true }), NOW);
    expect(again.label).toBe("Checking…");
    expect(again.releases.map((r) => r.version)).toEqual(["v0.2.0"]);
    expect(again.command).not.toBeNull();
  });

  it("failed: the server's sentence, when it last tried, Check now still offered", () => {
    const v = updateView(updateFixture("contract-failed"), NOW);
    expect([v.state, v.tone, v.label]).toEqual(["failed", "default", "Couldn't check"]);
    expect(v.line).toBe("Couldn't reach GitHub (timed out). You have v0.1.0.");
    expect(v.checked).toBe("Last checked 10 min ago");
    expect(v.canCheck).toBe(true);
    expect(updateView(updateFixture("contract-failed", { error: "No internet connection" }), NOW).line).toBe(
      "No internet connection. You have v0.1.0.",
    );
  });

  it("checks off: no Check now; the command to check by hand", () => {
    const v = updateView(updateFixture("contract-off"), NOW);
    expect([v.state, v.label, v.canCheck]).toEqual(["off", "Checks off", false]);
    expect(v.line).toBe("Pitwall doesn't look for new versions: checks are turned off (PITWALL_UPDATE_CHECK=off). You have v0.1.0.");
    expect(v.command).toBe('cd "/Users/you/Pitwall/pitwall-v0.1.0" && uv run pitwall update');
    expect(v.commandIntro).toBe("To check and update by hand");
  });

  it("checks off but the CLI found an update earlier: the server's answer wins over the mode", () => {
    const v = updateView(updateFixture("contract-available", { mode: "off" }), NOW);
    expect(v.state).toBe("available");
    expect(v.canCheck).toBe(false);
  });

  it("git checkout: git pull, never the uv command", () => {
    const v = updateView(updateFixture("contract-git"), NOW);
    expect(v.isGit).toBe(true);
    expect(v.command).toBeNull();
    expect(v.howNote).toBe(GIT_LINE);
    expect(v.state).toBe("available");
    expect(updateView(updateFixture("contract-git", { update_available: false, newer: [] }), NOW).howNote).toBe(GIT_LINE);
  });

  it("a copy Pitwall cannot place: no command, the install guide", () => {
    const v = updateView(updateFixture("contract-available", { install_kind: "unknown", how: null }), NOW);
    expect(v.command).toBeNull();
    expect(v.howNote).toBe(UNKNOWN_KIND_LINE);
    expect(v.docsUrl).toBe(DOCS_URL);
    // Nothing to do: no note.
    expect(updateView(updateFixture("contract-up-to-date", { install_kind: "unknown", how: null }), NOW).howNote).toBeNull();
  });

  it("an unreadable running version: the sentence about it is left out, not invented", () => {
    const v = updateView(updateFixture("contract-available", { current: "" }), NOW);
    expect(v.line).toBe("v0.2.0 (released 12 Oct 2026).");
    expect(updateView(updateFixture("contract-up-to-date", { current: "" }), NOW).line).toBe("There is no newer release.");
  });

  it("stateOf precedence: checking > available > up to date > failed > off > never", () => {
    expect(stateOf(updateFixture("contract-failed", { checking: true }))).toBe("checking");
    expect(stateOf(updateFixture("contract-available", { error: "x" }))).toBe("available");
    expect(stateOf(updateFixture("contract-off", { error: "x" }))).toBe("failed");
  });
});

describe("plain wording (beginners read this page too)", () => {
  it("no jargon in what the card says; British spelling; no instruction to update from the dashboard", () => {
    const names = [
      "contract-available",
      "contract-available-several",
      "contract-up-to-date",
      "contract-never-auto",
      "contract-checking",
      "contract-failed",
      "contract-off",
      "contract-git",
    ] as const;
    for (const n of names) {
      const v = updateView(updateFixture(n), NOW);
      const words = [v.label, v.line, v.commandIntro ?? "", v.howNote ?? "", v.checked ?? ""].join(" ");
      expect(words, n).not.toMatch(/sha-?256|venv|uv sync|semver|schema|null|undefined|NaN|\bAPI\b|endpoint/i);
      expect(words, n).not.toMatch(/color|behavior|license\b|analyze/i);
      expect(words, n).not.toMatch(/update now/i);
    }
  });
});

describe("helpers", () => {
  it("the Version row chip shows only when the server says an update is out", () => {
    expect(showUpdateChip(undefined)).toBe(false);
    expect(showUpdateChip(updateFixture("contract-available"))).toBe(true);
    expect(showUpdateChip(updateFixture("contract-up-to-date"))).toBe(false);
    expect(showUpdateChip(updateFixture("contract-failed"))).toBe(false);
  });

  it("notes: the first six, then all when expanded", () => {
    const notes = updateFixture("contract-available").latest!.notes;
    expect(shownNotes(notes, false)).toEqual({ items: notes.slice(0, NOTES_SHOWN), hidden: 2 });
    expect(shownNotes(notes, true)).toEqual({ items: notes, hidden: 0 });
    expect(shownNotes(["a"], false)).toEqual({ items: ["a"], hidden: 0 });
  });
});
