// "Use for my delta" (coachref, spec 10.5): next to picker A when A is another driver's lap. One tap asks inline, a
// second stores that lap as the driver's live reference at this track (PUT /api/coachref/choice, kind "lap"); the
// delta, the braking calls (never later than the driver's own braking point) and the lap coaching then measure
// against it. Other tracks keep their own choice.

import { Button } from "@heroui/react";
import { useState } from "react";
import { coachrefApi, coachrefErrorText } from "../../../../lib/endpoints/coachref";

export interface UseForDeltaProps {
  lapId: number;
  driverId: number;
  /** The driver is the one in the seat: "my delta"; else "Sam's delta". */
  self: boolean;
  driverName: string | null;
  trackName: string | null;
  /** "Sam's best". */
  refLabel: string;
}

export function UseForDelta({ lapId, driverId, self, driverName, trackName, refLabel }: UseForDeltaProps) {
  const [step, setStep] = useState<"idle" | "confirm" | "saved">("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const whose = self || !driverName ? "your" : `${driverName}'s`;
  const where = trackName ?? "this track";

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
        Saved: {whose} delta at {where} is now against this lap
      </span>
    );
  }
  if (step === "confirm") {
    return (
      <span className="flex flex-wrap items-center gap-2 text-sm">
        <span>
          Measure {whose} live delta at {where} against {refLabel}?
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
      {self || !driverName ? "Use for my delta" : `Use for ${driverName}'s delta`}
    </Button>
  );
}
