// A short notice in the Drive status slot (coachref, spec 10.1): "Delta to Sam's best from the next lap" (6 s) after
// a reference change that waits for the next lap, and "Change the reference when stopped" (2 s) after a tap on the
// locked reference control. It sits in the transient-chip position, like the Drive lock hint (no toast: nothing
// pops up over the hero while driving). One notice at a time; a newer one replaces it.

import { Store } from "../store";

export const NOTICE_CHANGE_MS = 6000;
export const NOTICE_HINT_MS = 2000;
/** A popover opened while driving ("Back to your best", the drill chip's) covers the delta: it closes by itself. */
export const POPOVER_AUTO_CLOSE_MS = 5000;

export interface DriveNoticeState {
  text: string | null;
}

export class DriveNoticeStore extends Store<DriveNoticeState> {
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    super({ text: null });
  }

  show(text: string, ms: number): void {
    if (this.timer) clearTimeout(this.timer);
    this.set({ text });
    this.timer = setTimeout(() => {
      this.timer = null;
      this.set({ text: null });
    }, ms);
  }

  clear(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.set({ text: null });
  }
}

export const driveNotice = new DriveNoticeStore();
