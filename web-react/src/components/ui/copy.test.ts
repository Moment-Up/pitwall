import { describe, expect, it, vi } from "vitest";
import { copyText } from "./copy";

describe("copyText()", () => {
  it("uses the Clipboard API when there is one", async () => {
    const writeText = vi.fn(async () => {});
    const legacyCopy = vi.fn(() => true);
    expect(await copyText("https://studio.example:8443/", { clipboard: { writeText }, legacyCopy })).toBe(true);
    expect(writeText).toHaveBeenCalledWith("https://studio.example:8443/");
    expect(legacyCopy).not.toHaveBeenCalled();
  });

  it("falls back to the legacy copy on plain HTTP (no clipboard) or when the API refuses", async () => {
    const legacyCopy = vi.fn(() => true);
    expect(await copyText("192.168.1.20", { clipboard: null, legacyCopy })).toBe(true);
    const refuse = { writeText: vi.fn(async () => Promise.reject(new Error("denied"))) };
    expect(await copyText("20777", { clipboard: refuse, legacyCopy })).toBe(true);
    expect(legacyCopy).toHaveBeenCalledTimes(2);
  });

  it("reports failure when nothing can copy, and never copies an empty value", async () => {
    expect(await copyText("x", { clipboard: null, legacyCopy: () => false })).toBe(false);
    expect(await copyText("x", { clipboard: null, legacyCopy: null })).toBe(false);
    const writeText = vi.fn(async () => {});
    expect(await copyText("", { clipboard: { writeText } })).toBe(false);
    expect(writeText).not.toHaveBeenCalled();
  });
});
