// The lap ribbon on Drive › Coach (design spec 4.3 #8; mockup ribbonSvg): the lap as a straight strip with neutral
// sector bands, a tick per corner (labels for the next and focus corners), brake notches, dashed DRS zones, hatched
// yellow zones and the car as an orange triangle. Drawn by lane V's shared LapRibbon (components/viz, also Review ›
// Compare's header) from the Drive model's RibbonView: static SVG, only the car moves (4.11).
//
// Imported from its own module, not the viz index, so nothing else of the kit lands in the eager Drive bundle.

import { Card } from "@heroui/react";
import { memo } from "react";
import { LapRibbon } from "../../../components/viz/LapRibbon";
import type { RibbonView } from "../../../lib/drive/ribbon";
import { useMediaQuery } from "./parts";

/** Ribbon row height: 56 px, 44 px in the compact rows (iPad mini, Safari with toolbars; spec 4.2). */
export const RIBBON_H = 56;
export const RIBBON_H_COMPACT = 44;

export const CoachRibbon = memo(function CoachRibbon({ ribbon }: { ribbon: RibbonView }) {
  const compact = useMediaQuery("(max-height: 760px) and (min-width: 768px)");
  return (
    <Card className="pwc-ribbon">
      <LapRibbon ribbon={ribbon} height={compact ? RIBBON_H_COMPACT : RIBBON_H} />
    </Card>
  );
});
