// Render tests for Settings › System › Updates (static markup in plain node, like ../render.test.ts). The view is pure:
// the status, errors, the clock and the actions are props.

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { EndpointError } from "../../../lib/endpoints/settings";
import type { UpdateStatus } from "../../../lib/endpoints/update";
import { UpdateCardView, type UpdateCardViewProps } from "./UpdateCard";
import { CARD_DESCRIPTION, GIT_LINE, HOW_HELP } from "./update-model";
import { NOW, updateFixture } from "./update-testkit";

function render(status: UpdateStatus | undefined, over: Partial<UpdateCardViewProps> = {}): string {
  const props: UpdateCardViewProps = {
    status,
    loadError: null,
    busy: false,
    actionError: null,
    nowUnix: NOW,
    expanded: new Set(),
    onToggle: vi.fn(),
    onCheck: vi.fn(),
    onRetry: vi.fn(),
    ...over,
  };
  return renderToStaticMarkup(createElement(UpdateCardView, props));
}

/** Visible text, tags stripped. */
const text = (m: string): string =>
  m
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();

/** The <button> elements whose text contains `label`. */
const buttons = (m: string, label: string): string[] =>
  (m.match(/<button[^>]*>[\s\S]*?<\/button>/g) ?? []).filter((b) => text(b).includes(label));

const listItems = (m: string): string[] => (m.match(/<li[^>]*>[\s\S]*?<\/li>/g) ?? []).map(text);

describe("Settings › System › Updates", () => {
  it("always: the card's title and promise; never an Update now button", () => {
    for (const s of [undefined, updateFixture("contract-available"), updateFixture("contract-off")]) {
      const t = text(render(s));
      expect(t).toContain("Updates");
      expect(t).toContain(CARD_DESCRIPTION);
      expect(t).not.toMatch(/update now/i);
    }
  });

  it("loading: a skeleton, no status yet", () => {
    const m = render(undefined);
    expect(m).toContain("skeleton");
    expect(text(m)).not.toContain("Check now");
  });

  it("an older server without /api/update: nothing at all", () => {
    expect(render(undefined, { loadError: new EndpointError(404, "Not Found") })).toBe("");
    expect(render(updateFixture("contract-available"), { loadError: new EndpointError(404, "Not Found") })).toBe("");
  });

  it("the status could not be loaded: says so with Try again", () => {
    const t = text(render(undefined, { loadError: new EndpointError(500, "Internal Server Error") }));
    expect(t).toContain("Couldn't load the update status: Internal Server Error");
    expect(t).toContain("Try again");
  });

  it("a refresh failed with data on screen: the data stays, with a short note", () => {
    const t = text(render(updateFixture("contract-up-to-date"), { loadError: new Error("Failed to fetch") }));
    expect(t).toContain("Up to date");
    expect(t).toContain("Couldn't refresh: Failed to fetch");
  });

  it("available: version and date, What changed (six, then Show all 8), How to update with the helper, release notes link", () => {
    const m = render(updateFixture("contract-available"));
    const t = text(m);
    expect(t).toContain("Update available");
    expect(t).toContain("v0.2.0 (released 12 Oct 2026). You have v0.1.0.");
    expect(t).toContain("What changed in v0.2.0");
    expect(listItems(m)).toHaveLength(6);
    expect(listItems(m)[0]).toBe("One-line installers for macOS, Linux and Windows");
    expect(buttons(m, "Show all 8")).toHaveLength(1);
    expect(t).toContain("How to update");
    expect(t).toContain('cd "/Users/you/Pitwall/pitwall-v0.1.0" && uv run pitwall update');
    expect(m).toContain('aria-label="Copy Update command"');
    expect(t).toContain(HOW_HELP);
    expect(t).toContain("Last checked 3 h ago");
    // The release page opens in a new tab without giving it this page.
    const link = m.match(/<a[^>]*href="https:\/\/github.com\/Moment-Up\/pitwall\/releases\/tag\/v0.2.0"[^>]*>/)?.[0] ?? "";
    expect(link).toContain('target="_blank"');
    expect(link).toContain('rel="noopener noreferrer"');
    expect(t).toContain("Release notes on GitHub");
    // Check now: 44 px, secondary, large.
    const check = buttons(m, "Check now")[0] ?? "";
    expect(check).toContain("min-h-11");
    expect(check).toMatch(/button--lg/);
    expect(check).toMatch(/button--secondary/);
  });

  it("available, expanded: all eight notes and Show fewer", () => {
    const m = render(updateFixture("contract-available"), { expanded: new Set(["v0.2.0"]) });
    expect(listItems(m)).toHaveLength(8);
    expect(buttons(m, "Show fewer")).toHaveLength(1);
    expect(m).toMatch(/aria-expanded="true"/);
  });

  it("several releases: one section each, newest first; an empty list is said in words", () => {
    const m = render(updateFixture("contract-available-several"));
    const t = text(m);
    const order = ["What changed in v0.3.0", "What changed in v0.2.1", "What changed in v0.2.0"].map((h) => t.indexOf(h));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(t).toContain("The release notes have no list of changes.");
    // The newest release's date is in the status line; older ones carry their own (when GitHub gave one).
    expect(t).toContain("What changed in v0.3.0 Track maps");
    expect(t).toContain("What changed in v0.2.1 The release notes");
    expect(t).toContain("What changed in v0.2.0 12 Oct 2026");
    expect(buttons(m, "Show all").map(text)).toEqual(["Show all 8"]); // only the long one
  });

  it("release notes are text, never markup", () => {
    const s = updateFixture("contract-available");
    s.newer = [{ ...s.newer[0]!, notes: ['<img src=x onerror="alert(1)">', "**bold** stays as typed"] }];
    const m = render(s);
    expect(m).not.toContain("<img");
    expect(m).toContain("&lt;img src=x onerror=");
  });

  it("an unsafe release URL is not linked", () => {
    const s = updateFixture("contract-available");
    s.newer = [{ ...s.newer[0]!, url: "https://evil.example/pitwall/releases/tag/v0.2.0" }];
    const m = render(s);
    expect(m).not.toContain("evil.example");
    expect(text(m)).not.toContain("Release notes on GitHub");
  });

  it("pre-release: labelled", () => {
    const s = updateFixture("contract-available");
    s.newer = [{ ...s.newer[0]!, version: "v0.3.0-rc.1", prerelease: true }];
    expect(text(render(s))).toContain("What changed in v0.3.0-rc.1 Pre-release");
  });

  it("up to date: a success chip, no notes, no command", () => {
    const m = render(updateFixture("contract-up-to-date"));
    const t = text(m);
    expect(t).toContain("Up to date");
    expect(m).toMatch(/chip--success/);
    expect(t).toContain("You have v0.2.0, the latest release.");
    expect(t).not.toContain("What changed");
    expect(t).not.toContain("How to update");
  });

  it("never checked (no data yet): says when Pitwall will look; Check now offered", () => {
    const t = text(render(updateFixture("contract-never-auto")));
    expect(t).toContain("Not checked yet");
    expect(t).toContain("once a day, while no game is sending telemetry");
    expect(t).toContain("Check now");
    expect(t).not.toContain("Last checked");
  });

  it("checking: Check now is pending (and while the POST runs)", () => {
    const m = render(updateFixture("contract-checking"));
    expect(text(m)).toContain("Checking…");
    expect(buttons(m, "Check now")[0]).toMatch(/data-pending="true"/);
    const busy = render(updateFixture("contract-never-auto"), { busy: true });
    expect(buttons(busy, "Check now")[0]).toMatch(/data-pending="true"/);
    expect(buttons(render(updateFixture("contract-never-auto")), "Check now")[0]).not.toMatch(/data-pending="true"/);
  });

  it("failed: the server's sentence; Check now to try again", () => {
    const t = text(render(updateFixture("contract-failed")));
    expect(t).toContain("Couldn't check");
    expect(t).toContain("Couldn't reach GitHub (timed out). You have v0.1.0.");
    expect(t).toContain("Last checked 10 min ago");
    expect(t).toContain("Check now");
  });

  it("Check now refused: the server's words in an alert", () => {
    const t = text(render(updateFixture("contract-never-auto"), { actionError: "Update checks are off (PITWALL_UPDATE_CHECK=off)." }));
    expect(t).toContain("Couldn't check for updates");
    expect(t).toContain("Update checks are off (PITWALL_UPDATE_CHECK=off).");
  });

  it("checks off: no Check now; the command to check by hand and the install guide", () => {
    const m = render(updateFixture("contract-off"));
    const t = text(m);
    expect(t).toContain("Checks off");
    expect(buttons(m, "Check now")).toHaveLength(0);
    expect(t).toContain("To check and update by hand");
    expect(t).toContain("uv run pitwall update");
    expect(m).toContain('href="https://github.com/Moment-Up/pitwall/blob/main/docs/install.md#updating"');
  });

  it("git checkout: git pull, not the uv command", () => {
    const t = text(render(updateFixture("contract-git")));
    expect(t).toContain(GIT_LINE);
    expect(t).not.toContain("uv run pitwall update");
    expect(t).toContain("What changed in v0.2.0");
  });

  it("phone layout (390 px): rows wrap, long values break, nothing has a fixed width", () => {
    const m = render(updateFixture("contract-available-several"));
    expect(m).not.toMatch(/\bw-\[\d+px\]|min-w-\[\d+px\]|whitespace-nowrap/);
    expect(m).toContain("flex-wrap");
    expect(m).toContain("break-words");
    expect(m).toContain("pw-copy"); // CopyField: the value wraps anywhere (index.css .pw-copy__value)
    for (const b of (m.match(/<button[^>]*>/g) ?? [])) expect(b).toMatch(/min-h-11|pw-copy__button/);
    for (const a of (m.match(/<a [^>]*>/g) ?? [])) expect(a).toContain("min-h-11");
  });
});
