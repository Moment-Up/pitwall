// Minimal framework-agnostic external store: immutable state + subscribe, the contract React's
// useSyncExternalStore needs (getSnapshot must return the same object until the state changes).

export type Listener = () => void;

export class Store<S extends object> {
  private state: S;
  private readonly listeners = new Set<Listener>();

  constructor(initial: S) {
    this.state = initial;
  }

  /** Current state. Stable identity between changes. */
  readonly get = (): S => this.state;

  /** Subscribe to changes; returns the unsubscribe function. */
  readonly subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Replace part of the state (shallow merge) and notify. No-op when nothing changed. */
  protected set(patch: Partial<S>): void {
    let changed = false;
    for (const k of Object.keys(patch) as (keyof S)[]) {
      if (!Object.is(this.state[k], patch[k])) {
        changed = true;
        break;
      }
    }
    if (!changed) return;
    this.state = { ...this.state, ...patch };
    for (const l of [...this.listeners]) l();
  }
}
