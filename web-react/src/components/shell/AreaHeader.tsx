// Area header (spec 3.2) for Review, Setup and Settings: 64 px, the area title (24 px / 600, sentence case), the
// sub-nav Segment, then the area's actions on the right. Sticky at the top of the scrolling content. On phones the
// title moves to the app bar and the Segment scrolls sideways, with the actions on a row under it.
//
// Pages put their actions in the header with <AreaActions>…</AreaActions> (a portal into the header's slot), e.g.
//   <AreaActions><Button onPress={openReport}>Session report</Button></AreaActions>

import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { AreaId } from "../../lib/router";
import { areaById } from "../../routes";
import { ScrollRow } from "../ScrollRow";
import { SubNav } from "./SubNav";

export const AreaActionsContext = createContext<HTMLElement | null>(null);

/** Render children into the current area header's action slot (right end; under the Segment on phones). */
export function AreaActions({ children }: { children: ReactNode }) {
  const el = useContext(AreaActionsContext);
  return el ? createPortal(children, el) : null;
}

export function AreaHeader({ area, actionsRef }: { area: AreaId; actionsRef: (el: HTMLElement | null) => void }) {
  const def = areaById(area);
  return (
    <header className="sticky top-0 z-20 -mx-4 flex flex-col gap-2 bg-background px-4 py-2 md:-mx-6 md:h-16 md:flex-row md:items-center md:gap-4 md:px-6 md:py-0">
      <h1 className="hidden shrink-0 text-2xl leading-none font-semibold tracking-[-0.01em] md:block">{def.label}</h1>
      {/* On phones the Segment scrolls sideways when it does not fit (Settings' five pages), its cut-off end faded. */}
      <ScrollRow className="-mx-4 px-4 md:mx-0 md:px-0">
        <SubNav key={area} area={area} placement="area" className="w-max" />
      </ScrollRow>
      <div ref={actionsRef} className="flex min-w-0 flex-wrap items-center gap-2 empty:hidden md:ml-auto md:flex-nowrap" />
    </header>
  );
}
