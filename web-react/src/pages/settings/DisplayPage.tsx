// Settings › Display (spec 8; mockup displayPage): theme, Drive always dark, Drive text size, night dim, colour
// vision, dimming the rail on track and the Drive lock, each changing a live preview (a timing cell and the delta).
// Stored per device by lib/prefs.ts (lane S): this page only calls prefs.setPref(), which also applies the change
// to <html> at once (class, data-night, data-cvd, data-drive-size), so the preview and the whole app follow.
// Pro Segment and CellSwitch rows in one HeroUI Card; the preview in a second Card (sticky beside the rows on iPad).

import { useActiveDriver, usePrefs, usePrefsState } from "../../hooks/stores";
import { prefs } from "../../lib/prefs";
import type { PageProps } from "../../routes";
import { CellGroup, SegmentRow, SwitchRow } from "./cells";
import { DisplayPreview } from "./display/DisplayPreview";
import {
  COLOUR_VISION,
  DRIVE_LOCKS,
  DRIVE_SIZES,
  HINTS,
  THEMES,
  lockNow,
  nightHint,
  previewCaption,
} from "./display/model";

export function DisplayPage(_props: PageProps) {
  const p = usePrefs((x) => x);
  const systemDark = usePrefsState((s) => s.systemDark);
  const seated = useActiveDriver();
  const seat = seated ? { name: seated.name, skill: seated.preferences.skill_level } : null;

  return (
    <div className="grid items-start gap-4 lg:grid-cols-2">
      <CellGroup label="Display settings">
        <SegmentRow
          title="Theme"
          hint={HINTS.theme}
          value={p.theme}
          choices={THEMES}
          onChange={(v) => prefs.setPref("theme", v)}
        />
        <SwitchRow
          title="Drive always dark"
          hint={HINTS.driveAlwaysDark}
          isSelected={p.driveAlwaysDark}
          onChange={(v) => prefs.setPref("driveAlwaysDark", v)}
        />
        <SegmentRow
          title="Drive text size"
          hint={HINTS.driveSize}
          value={p.driveSize}
          choices={DRIVE_SIZES}
          onChange={(v) => prefs.setPref("driveSize", v)}
        />
        <SwitchRow
          title="Night dim"
          hint={nightHint(p, systemDark)}
          isSelected={p.night}
          onChange={(v) => prefs.setPref("night", v)}
        />
        <SegmentRow
          title="Colour vision"
          hint={HINTS.cvd}
          value={p.cvd}
          choices={COLOUR_VISION}
          onChange={(v) => prefs.setPref("cvd", v)}
        />
        <SwitchRow
          title="Dim navigation on track"
          hint={HINTS.dimNav}
          isSelected={p.dimNav}
          onChange={(v) => prefs.setPref("dimNav", v)}
        />
        <SegmentRow
          title="Drive lock"
          hint={
            <>
              {HINTS.driveLock}
              <span className="block">{lockNow(p.driveLock, seat)}</span>
            </>
          }
          value={p.driveLock}
          choices={DRIVE_LOCKS}
          onChange={(v) => prefs.setPref("driveLock", v)}
        />
      </CellGroup>
      <div className="lg:sticky lg:top-20">
        <DisplayPreview caption={previewCaption(p, systemDark)} />
      </div>
    </div>
  );
}
