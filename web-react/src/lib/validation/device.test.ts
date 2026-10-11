// Device facts for the validation kit (lane validate): UA, origin and microphone-label classification tables.

import { describe, expect, it } from "vitest";
import { CLIENT_ID_KEY, audioInputKind, clientId, defaultAudioInputLabel, detectDevice, isDriveRoute, isStandalone, originKind, randomId, routeName, safariVersion } from "./device";
import { memoryStorage } from "../../test/fakes";

const UA = {
  ipadSafari:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15",
  ipadHomeScreen: "Mozilla/5.0 (iPad; CPU OS 18_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
  iphone: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
  iphoneChrome: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0 Mobile/15E148 Safari/604.1",
  android: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36",
  macChrome: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
  macSafari: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",
};

describe("detectDevice", () => {
  it.each([
    [UA.ipadSafari, 5, "ipad"],
    [UA.ipadSafari, 0, "browser"], // a real Mac: no touch points
    [UA.ipadHomeScreen, 5, "ipad"],
    [UA.iphone, 5, "iphone"],
    [UA.android, 5, "android"],
    [UA.macChrome, 0, "browser"],
  ] as const)("%s (%i touch points) -> %s", (ua, touch, out) => {
    expect(detectDevice(ua, touch)).toBe(out);
  });
});

describe("originKind", () => {
  it.each([
    ["https:", "studio.tail1234.ts.net", "tailscale_https"],
    ["https:", "Studio.Tail1234.TS.NET.", "tailscale_https"],
    ["https:", "pitwall.example.org", "https"],
    ["http:", "localhost", "localhost"],
    ["http:", "127.0.0.1", "localhost"],
    ["http:", "[::1]", "localhost"],
    ["http:", "192.168.1.20", "lan_http"],
    ["http:", "studio.local", "lan_http"],
    ["file:", "", "other"],
  ] as const)("%s//%s -> %s", (proto, host, out) => {
    expect(originKind(proto, host)).toBe(out);
  });
});

describe("safariVersion", () => {
  it("Safari's Version/ token", () => {
    expect(safariVersion(UA.ipadSafari)).toBe("18.6");
    expect(safariVersion(UA.macSafari)).toBe("18.4");
    expect(safariVersion(UA.iphone)).toBe("17.5");
  });
  it("a Home Screen app has no Version/: the OS version stands in (same WebKit)", () => {
    expect(safariVersion(UA.ipadHomeScreen)).toBe("18.3.1");
    expect(safariVersion(UA.iphoneChrome)).toBe("18.1");
  });
  it("not WebKit-only: unknown, never guessed", () => {
    expect(safariVersion(UA.macChrome)).toBeNull();
    expect(safariVersion(UA.android)).toBeNull();
    expect(safariVersion("")).toBeNull();
  });
});

describe("audioInputKind (the label never leaves the device)", () => {
  it.each([
    ["James's AirPods Pro", "airpods"],
    ["AirPods (4th generation)", "airpods"],
    ["Bluetooth Headset", "bluetooth"],
    ["Galaxy Buds2", "bluetooth"],
    ["Beats Studio Buds", "bluetooth"],
    ["iPad Microphone", "built_in"],
    ["iPhone Microphone", "built_in"],
    ["MacBook Pro Microphone (Built-in)", "built_in"],
    ["Default - Internal Microphone", "built_in"],
    ["USB Audio Device", "wired"],
    ["Yeti USB microphone", "wired"],
    ["Line In", "wired"],
    ["Wired headphones", "wired"],
    ["Elgato Wave:3", "unknown"],
  ] as const)("%s -> %s", (label, out) => {
    expect(audioInputKind(label)).toBe(out);
  });
  it("no label (no microphone permission yet): unknown stays null", () => {
    expect(audioInputKind("")).toBeNull();
    expect(audioInputKind("   ")).toBeNull();
    expect(audioInputKind(null)).toBeNull();
  });
  it("the default input among enumerateDevices()", () => {
    const devs = [
      { kind: "audiooutput", deviceId: "default", label: "Speakers" },
      { kind: "audioinput", deviceId: "abc", label: "iPad Microphone" },
      { kind: "audioinput", deviceId: "default", label: "AirPods" },
    ];
    expect(defaultAudioInputLabel(devs)).toBe("AirPods");
    expect(defaultAudioInputLabel(devs.slice(0, 2))).toBe("iPad Microphone");
    expect(defaultAudioInputLabel([])).toBeNull();
  });
});

describe("page facts", () => {
  it("standalone: display-mode or iOS navigator.standalone", () => {
    expect(isStandalone(true, undefined)).toBe(true);
    expect(isStandalone(false, true)).toBe(true);
    expect(isStandalone(false, false)).toBe(false);
    expect(isStandalone(false, undefined)).toBe(false);
  });
  it("routes are area/page only, at most 64 characters", () => {
    expect(routeName("drive", "coach")).toBe("drive/coach");
    expect(routeName("setup", "validation")).toBe("setup/validation");
    expect(routeName("x".repeat(40), "y".repeat(40))).toHaveLength(64);
    expect(isDriveRoute("drive/radio")).toBe(true);
    expect(isDriveRoute("setup/validation")).toBe(false);
  });
  it("client id: kept in storage; a fresh one per page load without storage", () => {
    const s = memoryStorage();
    let n = 0;
    const make = () => `00000000-0000-4000-8000-00000000000${++n}`;
    const a = clientId(s, make);
    expect(clientId(s, make)).toBe(a);
    expect(s.getItem(CLIENT_ID_KEY)).toBe(a);
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {},
    };
    expect(clientId(broken, make)).not.toBe(a);
    expect(clientId(null, make)).toMatch(/^0{8}-/);
  });
  it("random ids look like UUIDs", () => {
    expect(randomId()).toMatch(/^[0-9a-f-]{20,}$|^x[0-9a-f]+-[0-9a-f]+$/);
  });
});
