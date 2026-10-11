// Starts the rig validation kit's device reporter for the whole app (lane validate, spec 12.2). No React state: the
// reporter reads the stores itself and never causes a render, so Drive is unaffected. While no validation run is
// active it only asks the server once every 20 s whether one is.

import { useEffect } from "react";
import { validationReporter } from "../lib/validation/browser";

export function useValidationReporter(): void {
  useEffect(() => {
    let r: ReturnType<typeof validationReporter> | null = null;
    try {
      r = validationReporter();
      r.start();
    } catch {
      /* no browser APIs: the kit simply gets no device reports */
    }
    return () => r?.stop();
  }, []);
}
