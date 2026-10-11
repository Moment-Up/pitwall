// Device facts for the rig validation kit (lane validate, spec 12.2). Pure functions: the reporter feeds them the
// browser's values, the tests feed them tables. Nothing here reads a global by itself, and nothing identifying leaves
// the device: the microphone's label is classified here and only the class is reported (never the label, never an
// address).

import type { AudioInputKind, Device, OriginKind } from "../endpoints/validation";

/** iPad, iPhone, Android or another browser. iPadOS 13+ reports a desktop Mac UA: touch support gives it away (the
 * same rule as the radio's client name in lib/radio.ts). */
export function detectDevice(ua: string, maxTouchPoints: number): Device {
  if (/iPad/.test(ua) || (/Macintosh/.test(ua) && maxTouchPoints > 1)) return "ipad";
  if (/iPhone|iPod/.test(ua)) return "iphone";
  if (/Android/.test(ua)) return "android";
  return "browser";
}

/** How the page was reached: Tailscale serve (HTTPS on *.ts.net), other HTTPS, this Mac, or plain HTTP on the LAN. */
export function originKind(protocol: string, hostname: string): OriginKind {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  if (protocol === "https:") return host.endsWith(".ts.net") ? "tailscale_https" : "https";
  if (host === "localhost" || host === "127.0.0.1" || host === "[::1]" || host === "::1") return "localhost";
  if (protocol === "http:") return "lan_http";
  return "other";
}

/** Max length the server accepts for a version string. */
const VERSION_MAX = 16;

/**
 * The WebKit version that matters for the wake lock (lib/wake.ts: before 18.4 a Home Screen app's lock resolves but
 * the screen still sleeps). Safari's `Version/18.6`; a Home Screen app on iPhone / iPad leaves that token out, so the
 * OS version (`CPU OS 18_6`) stands in for it. Other browsers on iOS use the same WebKit, so their OS version counts
 * too. Desktop Chrome / Firefox: null (unknown, not "no").
 */
export function safariVersion(ua: string): string | null {
  const isWebKitOnly = /AppleWebKit/.test(ua) && !/Chrome\/|Chromium\/|Edg\/|Firefox\/|OPR\//.test(ua);
  const v = /Version\/(\d+(?:\.\d+){0,2})/.exec(ua);
  if (v?.[1] && isWebKitOnly) return v[1].slice(0, VERSION_MAX);
  const os = /CPU (?:iPhone )?OS (\d+)_(\d+)(?:_(\d+))?/.exec(ua);
  if (os?.[1] && os[2]) return `${os[1]}.${os[2]}${os[3] ? `.${os[3]}` : ""}`.slice(0, VERSION_MAX);
  return null;
}

/** A Home Screen web app: `display-mode: standalone` (all browsers) or iOS's navigator.standalone. */
export function isStandalone(displayModeStandalone: boolean, navigatorStandalone: boolean | undefined): boolean {
  return displayModeStandalone || navigatorStandalone === true;
}

/**
 * The microphone's kind from its label (spec 12.2). The label only exists after the microphone permission; an empty
 * one is unknown (null). Order matters: AirPods are Bluetooth, and a USB or wired microphone is not the built-in one
 * even when its label says "microphone".
 */
export function audioInputKind(label: string | null | undefined): AudioInputKind | null {
  const l = (label ?? "").trim();
  if (!l) return null;
  if (/airpods/i.test(l)) return "airpods";
  if (/bluetooth|headset|buds|beats/i.test(l)) return "bluetooth";
  if (/\busb\b|wired|\bline\b/i.test(l)) return "wired";
  if (/ipad|iphone|built-in|internal|microphone/i.test(l)) return "built_in";
  return "unknown";
}

/** The default audio input among `enumerateDevices()` results: the "default" entry, else the first input. */
export function defaultAudioInputLabel(devices: readonly { kind: string; deviceId: string; label: string }[]): string | null {
  const inputs = devices.filter((d) => d.kind === "audioinput");
  const d = inputs.find((x) => x.deviceId === "default") ?? inputs[0];
  return d ? d.label : null;
}

/** Max length the server accepts for a route. */
const ROUTE_MAX = 64;

/** "drive/coach", "setup/validation"… (area and page only: a param may carry a session id). */
export function routeName(area: string, page: string): string {
  return `${area}/${page}`.slice(0, ROUTE_MAX);
}

export function isDriveRoute(route: string): boolean {
  return route.startsWith("drive/");
}

/** localStorage key of this device's random client id (spec 12.2). */
export const CLIENT_ID_KEY = "pitwall.validation.client";

/** This device's client id: kept in storage, or a fresh one per page load when storage is unavailable. */
export function clientId(storage: Pick<Storage, "getItem" | "setItem"> | null, makeId: () => string): string {
  try {
    const have = storage?.getItem(CLIENT_ID_KEY);
    if (have && /^[A-Za-z0-9-]{8,64}$/.test(have)) return have;
    const id = makeId();
    storage?.setItem(CLIENT_ID_KEY, id);
    return id;
  } catch {
    return makeId();
  }
}

/** A random UUID (crypto.randomUUID needs a secure context: plain LAN HTTP falls back to getRandomValues / Math). */
export function randomId(): string {
  try {
    const c = (globalThis as { crypto?: Crypto }).crypto;
    if (c && typeof c.randomUUID === "function") return c.randomUUID();
    if (c && typeof c.getRandomValues === "function") {
      const b = c.getRandomValues(new Uint8Array(16));
      b[6] = ((b[6] ?? 0) & 0x0f) | 0x40;
      b[8] = ((b[8] ?? 0) & 0x3f) | 0x80;
      const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
      return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
    }
  } catch {
    /* fall through */
  }
  return `x${Math.random().toString(16).slice(2, 14)}-${Date.now().toString(16)}`;
}
