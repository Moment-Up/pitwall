// Live WebSocket store (Svelte 5 runes). Reconnects with backoff; keeps a short rolling history for traces.
import type { Snapshot } from "./api";

export interface HistoryPoint {
  t: number;
  speed: number | null;
  throttle: number | null;
  brake: number | null;
}

const HISTORY_SECONDS = 12;

class LiveStore {
  snap = $state<Snapshot | null>(null);
  connected = $state(false);
  history = $state<HistoryPoint[]>([]);
  lastLapEvent = $state<{ lap: any; observations: any[] } | null>(null);
  private ws: WebSocket | null = null;
  private retry = 500;
  private started = false;

  start() {
    if (this.started) return;
    this.started = true;
    this.connect();
  }

  private connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const token = new URLSearchParams(location.search).get("token");
    const ws = new WebSocket(`${proto}://${location.host}/ws/live${token ? `?token=${token}` : ""}`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      this.connected = true;
      this.retry = 500;
    };
    ws.onclose = () => {
      this.connected = false;
      setTimeout(() => this.connect(), this.retry);
      this.retry = Math.min(this.retry * 2, 5000);
    };
    ws.onmessage = (ev) => {
      const text = typeof ev.data === "string" ? ev.data : new TextDecoder().decode(ev.data);
      const msg = JSON.parse(text);
      if (msg.type === "snapshot") {
        const prevModel = this.snap?.track_model;
        const s: Snapshot = msg.data;
        if (s.track_model === undefined && prevModel !== undefined) s.track_model = prevModel;
        const prevSkeleton = this.snap?.skeleton;
        if (s.skeleton === undefined && prevSkeleton !== undefined) s.skeleton = prevSkeleton;
        const prevKnowledge = this.snap?.track_knowledge;
        if (s.track_knowledge === undefined && prevKnowledge !== undefined) s.track_knowledge = prevKnowledge;
        this.snap = s;
        const f = s.frame;
        if (f) {
          const now = performance.now() / 1000;
          const h = this.history;
          h.push({ t: now, speed: f.speed_kph, throttle: f.throttle, brake: f.brake });
          while (h.length && now - h[0].t > HISTORY_SECONDS) h.shift();
        }
      } else if (msg.type === "lap") {
        this.lastLapEvent = msg.data;
      }
    };
  }
}

export const live = new LiveStore();
