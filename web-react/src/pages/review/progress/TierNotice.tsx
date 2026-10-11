// Says when Progress / the Coaching plan run on lap-level data because the server's progress history (D5) is not
// there: an older server (the route answers 404) or an error. Nothing is shown while D5 answers.

import { Alert } from "@heroui/react";
import type { ProgressTier } from "./useReviewScope";

export function TierNotice({ tier, what }: { tier: ProgressTier; what: string }) {
  if (tier.kind === "d5" || tier.why === "loading") return null;
  return (
    <Alert status={tier.why === "error" ? "warning" : "default"}>
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>
          {tier.why === "missing"
            ? "Lap-level view: this Pitwall server does not send progress history yet"
            : "Progress history could not be loaded: showing lap-level data"}
        </Alert.Title>
        <Alert.Description>
          {what} appear once it does.
          {tier.why === "error" && tier.error ? ` (${tier.error.message})` : ""}
        </Alert.Description>
      </Alert.Content>
    </Alert>
  );
}
