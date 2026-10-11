// The validation reporter's browser wiring (lane validate): reads the app's stores (screen wake lock, radio, router)
// and the page, and builds the ReporterEnv. Imported only by hooks/useValidationReporter.ts, so nothing runs at import
// in unit tests. Every browser call is guarded: a missing API means "unknown", never an error.

import type { ClientRadio } from "../endpoints/validation";
import { postClientReport, validationApi } from "../endpoints/validation";
import { radio, type RadioState } from "../radio";
import { router } from "../router";
import { screenWake } from "../wake";
import { clientId, defaultAudioInputLabel, detectDevice, isStandalone, originKind, randomId, routeName, safariVersion } from "./device";
import { ValidationReporter, type DeviceSnapshot, type ReporterEnv } from "./reporter";

function safe<T>(f: () => T, fallback: T): T {
  try {
    return f();
  } catch {
    return fallback;
  }
}

function radioFacts(s: RadioState): ClientRadio {
  return {
    phase: s.phase,
    conn: s.conn,
    mic: s.mic,
    mic_silent: s.micSilent,
    wake: s.wake,
    audio: s.audio,
    audio_session: s.audioSession,
    tts_mode: s.settings.voiceSource === "device" ? "device" : "server",
    rtt_ms: typeof s.rttMs === "number" && Number.isFinite(s.rttMs) ? Math.round(s.rttMs) : null,
  };
}

function storage(): Storage | null {
  return safe(() => window.localStorage, null);
}

/** The ReporterEnv of this page. The static facts (device, origin, version) are read once. */
export function browserEnv(): ReporterEnv {
  const nav = safe(() => window.navigator, undefined as Navigator | undefined);
  const ua = nav?.userAgent ?? "";
  const device = detectDevice(ua, nav?.maxTouchPoints ?? 0);
  const origin = safe(() => originKind(window.location.protocol, window.location.hostname), "other" as const);
  const version = safariVersion(ua);
  const secure = safe(() => window.isSecureContext === true, false);
  const standaloneMq = safe(() => window.matchMedia?.("(display-mode: standalone)") ?? null, null);
  const navStandalone = (nav as (Navigator & { standalone?: boolean }) | undefined)?.standalone;

  const snapshot = (): DeviceSnapshot => {
    const w = safe(() => window.innerWidth, 0);
    const h = safe(() => window.innerHeight, 0);
    const route = router.get().route;
    const wake = screenWake.get();
    return {
      device,
      standalone: isStandalone(standaloneMq?.matches === true, navStandalone),
      secure_context: secure,
      origin_kind: origin,
      safari_version: version,
      viewport: { w, h, dpr: safe(() => window.devicePixelRatio || 1, 1), orientation: w >= h ? "landscape" : "portrait" },
      visibility: safe(() => (document.visibilityState === "hidden" ? "hidden" : "visible"), "visible" as const),
      route: routeName(route.area, route.page),
      wake: { wanted: wake.wanted, state: wake.state },
      radio: safe(() => radioFacts(radio.get()), null),
    };
  };

  return {
    clientId: clientId(storage(), randomId),
    snapshot,
    subscribe(onChange) {
      const offs = [screenWake.subscribe(onChange), radio.subscribe(onChange), router.subscribe(onChange)];
      const mqListener = (): void => onChange();
      safe(() => standaloneMq?.addEventListener("change", mqListener), undefined);
      return () => {
        for (const off of offs) off();
        safe(() => standaloneMq?.removeEventListener("change", mqListener), undefined);
      };
    },
    onVisibility(cb) {
      const l = (): void => cb(document.visibilityState !== "hidden");
      safe(() => document.addEventListener("visibilitychange", l), undefined);
      return () => safe(() => document.removeEventListener("visibilitychange", l), undefined);
    },
    fetchActive: () => validationApi.active(),
    post: (report, hidden) => postClientReport(report, hidden),
    micAllowed: () => {
      const s = radio.get();
      return s.phase === "live" && (s.mic === "live" || s.mic === "muted");
    },
    micLabel: async () => {
      const md = nav?.mediaDevices;
      if (!md || typeof md.enumerateDevices !== "function") return null;
      return defaultAudioInputLabel(await md.enumerateDevices());
    },
    now: () => Date.now(),
    perfNow: () => safe(() => performance.now(), Date.now()),
    raf: typeof requestAnimationFrame === "function" ? (cb) => requestAnimationFrame(() => cb()) : null,
    cancelRaf: typeof cancelAnimationFrame === "function" ? (id) => cancelAnimationFrame(id) : null,
  };
}

let instance: ValidationReporter | null = null;

/** The app's one reporter (created on first use, in the browser only). */
export function validationReporter(): ValidationReporter {
  instance ??= new ValidationReporter(browserEnv());
  return instance;
}

/** Ask the server now if the reporter is running (after the page starts, finishes or moves a run). */
export function pokeValidationReporter(): void {
  instance?.refresh();
}
