// Test doubles for the browser globals the framework-agnostic stores use. Unit tests run in plain node (no DOM
// library): each test stubs exactly the globals it needs with vi.stubGlobal and vitest restores them afterwards.

import { vi } from "vitest";

/** In-memory Storage (sessionStorage). */
export function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => {
      m.delete(k);
    },
    setItem: (k, v) => {
      m.set(k, String(v));
    },
  };
}

export interface FakeWindow {
  location: { protocol: string; host: string; pathname: string; search: string; hash: string };
  history: { state: unknown; replaceState: ReturnType<typeof vi.fn> };
  addEventListener: ReturnType<typeof vi.fn>;
}

/** Stub `window` (location, history, addEventListener) and `sessionStorage` for a page at `url`. */
export function stubBrowser(url = "http://127.0.0.1:8770/next/"): { win: FakeWindow; storage: Storage } {
  const u = new URL(url);
  const win: FakeWindow = {
    location: { protocol: u.protocol, host: u.host, pathname: u.pathname, search: u.search, hash: u.hash },
    history: {
      state: null,
      replaceState: vi.fn((_state: unknown, _title: string, next: string) => {
        const n = new URL(next, url);
        win.location.pathname = n.pathname;
        win.location.search = n.search;
        win.location.hash = n.hash;
      }),
    },
    addEventListener: vi.fn(),
  };
  const storage = memoryStorage();
  vi.stubGlobal("window", win);
  vi.stubGlobal("sessionStorage", storage);
  return { win, storage };
}

/** A WebSocket the test drives from the "server" side: open(), drop(), message(). */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readonly url: string;
  binaryType = "blob";
  closed = false;
  onopen: ((ev: unknown) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: string | ArrayBuffer }) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  static reset(): void {
    FakeWebSocket.instances = [];
  }

  static last(): FakeWebSocket {
    const ws = FakeWebSocket.instances.at(-1);
    if (!ws) throw new Error("no WebSocket was created");
    return ws;
  }

  /** Client-side close (what the store calls). */
  close(): void {
    this.closed = true;
  }

  open(): void {
    this.onopen?.({});
  }

  /** The connection drops (server gone, network loss). */
  drop(): void {
    this.closed = true;
    this.onclose?.({ code: 1006 });
  }

  message(msg: unknown, binary = false): void {
    const text = typeof msg === "string" ? msg : JSON.stringify(msg);
    this.onmessage?.({ data: binary ? new TextEncoder().encode(text).slice().buffer : text });
  }
}

/** A promise the test resolves later, e.g. a fetch response held in flight. */
export function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void } {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

export const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Let pending promise chains (fetch -> json -> store update) run to completion. */
export const flush = (): Promise<void> => new Promise((r) => setTimeout(r, 0));
