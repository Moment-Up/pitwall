// Theme: now part of the display preferences (./prefs.ts, spec 12.3). Kept as a re-export for existing call sites.
// `theme.toggle()` flips the chosen theme between dark and light from what is on screen; on Drive with "Drive
// always dark" the screen stays dark and the change shows in Review, Setup and Settings.

import { prefs, type ThemeName } from "./prefs";

export type { ThemeName } from "./prefs";

export const theme = {
  /** The theme on screen now. */
  current: (): ThemeName => prefs.get().theme,
  setTheme: (t: ThemeName): void => prefs.setPref("theme", t),
  toggle: (): void => prefs.setPref("theme", prefs.get().prefs.theme === "light" ? "dark" : "light"),
};
