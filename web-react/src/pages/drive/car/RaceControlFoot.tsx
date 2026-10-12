// Drive › Car, the Track tile's footer with race radio (lane "radio"; race-radio spec 10.2): the race-control line and,
// under it, the backend's note on the race position's evidence (GT7, Forza: "not yet checked against the game's
// screen"). Both texts come from ./view.ts (raceControlLine, raceNote); this only lays them out.

import "./race.css";

export function RaceControlFoot({ line, note }: { line: string; note: string }) {
  return (
    <>
      <span className="pww-foot__line" title={line}>
        {line}
      </span>
      <span className="pww-foot__note" title={note}>
        {note}
      </span>
    </>
  );
}
