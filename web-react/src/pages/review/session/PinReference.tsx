// Pin as reference (spec 6.4): the server call (POST /api/references) behind an inline confirmation, never a browser
// dialog (3.4). A pin is per driver, game, track and car (repo.pin_reference: the lap's own session decides whose
// reference it becomes), so only a clean lap of this session can be pinned here, and never from synthetic or replay
// data. Success says what changed; a failure keeps the button and says why.

import { Button } from "@heroui/react";
import { useState } from "react";
import { useDrivers } from "../../../hooks/stores";
import { carText } from "../../../lib/carclass";
import type { SessionDetail } from "../../../lib/endpoints/review";
import { reviewApi } from "../../../lib/endpoints/review";
import { timingEligible } from "../../../lib/review/kpis";
import { trackLabel } from "../../../lib/review/words";
import { errorText } from "./data";

export interface PinReferenceProps {
  lapId: number;
  lapNumber: number;
  session: Pick<SessionDetail, "driver_id" | "driver_name" | "track_name" | "car_name" | "car_label" | "synthetic" | "source">;
  /** After a successful pin (the session's analyses are invalidated by the endpoint). */
  onPinned?: () => void;
  /** Button text; default "Pin lap N as reference". */
  label?: string;
}

export function PinReference({ lapId, lapNumber, session, onPinned, label }: PinReferenceProps) {
  const list = useDrivers((s) => s.drivers);
  const [step, setStep] = useState<"idle" | "confirm" | "saving" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  if (!timingEligible(session)) return null;
  const owner = list.find((d) => d.id === session.driver_id)?.name ?? session.driver_name ?? null;
  const where = trackLabel(session);
  // the car in words ("F2 · Art GP '24", F2 support), never a raw id ("team_214")
  const text = carText(session);
  const car = text ? ` in the ${text}` : " in this car";

  async function pin() {
    setStep("saving");
    setError(null);
    try {
      await reviewApi.pinReference(lapId);
      setStep("done");
      onPinned?.();
    } catch (e) {
      setError(errorText(e));
      setStep("confirm");
    }
  }

  if (step === "done") {
    return (
      <p role="status" className="m-0 text-sm text-ahead">
        Lap {lapNumber} is now {owner ? `${owner}'s` : "the"} reference at {where}
        {car}.
      </p>
    );
  }
  if (step === "idle") {
    return (
      <Button variant="outline" size="sm" className="min-h-11" onPress={() => setStep("confirm")}>
        {label ?? `Pin lap ${lapNumber} as reference`}
      </Button>
    );
  }
  return (
    <div role="group" aria-label="Pin as reference" className="flex flex-wrap items-center gap-2 rounded-2xl bg-surface-secondary px-4 py-2">
      <span className="text-sm">
        Pin lap {lapNumber} as {owner ? `${owner}'s` : "the"} reference at {where}
        {car}? Pitwall then compares {owner ? `${owner}'s` : "these"} laps here with it: the delta on Drive, the coaching
        and Review.
      </span>
      <Button size="sm" className="min-h-11" isPending={step === "saving"} onPress={pin}>
        Pin it
      </Button>
      <Button variant="ghost" size="sm" className="min-h-11" isDisabled={step === "saving"} onPress={() => setStep("idle")}>
        Cancel
      </Button>
      {error && (
        <span role="alert" className="w-full text-sm text-bad">
          Not pinned: {error}
        </span>
      )}
    </div>
  );
}
