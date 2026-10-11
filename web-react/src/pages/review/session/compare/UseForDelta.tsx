// "Drive against this lap" (coachref, spec 10.5): next to picker A when A is another driver's lap. One tap asks inline
// (whose lap, which lap, its time, where: a saved lap stays that lap, it does not follow the driver's best), a second
// stores it as the driver's live reference at this track (PUT /api/coachref/choice, kind "lap"); the delta, the
// braking calls (never later than the driver's own braking point) and the lap coaching then measure against it.
// Other tracks keep their own choice.

import { Button } from "@heroui/react";
import { useState } from "react";
import { coachrefApi, coachrefErrorText } from "../../../../lib/endpoints/coachref";
import { savedLapWords } from "../../../../lib/drive/reference";

export interface UseForDeltaProps {
  lapId: number;
  driverId: number;
  /** The driver is the one in the seat: "Drive against this lap"; else "Sam: drive against this lap". */
  self: boolean;
  driverName: string | null;
  trackName: string | null;
  /** "Sam's best": used when the lap's holder is unknown. */
  refLabel: string;
  /** Whose lap it is ("Alex"), its number and time (the confirm names the one lap it stays on). */
  holder?: string | null;
  lapNumber?: number | null;
  lapTimeMs?: number | null;
}

export function UseForDelta({ lapId, driverId, self, driverName, trackName, refLabel, holder, lapNumber, lapTimeMs }: UseForDeltaProps) {
  const [step, setStep] = useState<"idle" | "confirm" | "saved">("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mine = self || !driverName;
  const where = trackName ?? "this track";
  const lap = savedLapWords(holder, lapNumber, lapTimeMs, refLabel);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await coachrefApi.setChoice({ driver_id: driverId, kind: "lap", lap_id: lapId });
      setStep("saved");
    } catch (e) {
      setError(coachrefErrorText(e));
    } finally {
      setBusy(false);
    }
  }

  if (step === "saved") {
    return (
      <span role="status" className="text-sm">
        Saved: {mine ? "you drive" : `${driverName} drives`} against {lap} at {where}
      </span>
    );
  }
  if (step === "confirm") {
    return (
      <span className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          {mine ? `Drive against ${lap} at ${where}?` : `Should ${driverName} drive against ${lap} at ${where}?`} It stays on
          this lap.
        </span>
        <Button variant="primary" size="sm" className="min-h-11" isPending={busy} onPress={() => void save()}>
          Use this lap
        </Button>
        <Button variant="ghost" size="sm" className="min-h-11" onPress={() => setStep("idle")}>
          Cancel
        </Button>
        {error && (
          <span role="alert" className="basis-full text-bad">
            {error}
          </span>
        )}
      </span>
    );
  }
  return (
    <Button variant="ghost" size="sm" className="min-h-11" onPress={() => setStep("confirm")}>
      {mine ? "Drive against this lap" : `${driverName}: drive against this lap`}
    </Button>
  );
}
