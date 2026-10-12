// App shell (spec 3, 10.2). Not Pro AppLayout/Sidebar (0.3): C needs a labelled 72 px rail and a phone tab bar.
//
//   >= 768 px   rail (72) | content            Review/Setup/Settings: area header (title, Segment, actions) on top;
//                                              Drive: no header, its Segment sits in the status slot (DriveStatusSlot)
//   <  768 px   app bar (52) / content / tab bar (64 + safe area); the Segment scrolls under the app bar
//
// Review, Setup and Settings carry the game alert (another game's data arriving, or a suggestion) above the page;
// Drive never does (P2). The content column scrolls; the rail, app bar and tab bar stay put. Content max width 1680 px, centred. The app
// runs as a Home Screen web app with a translucent status bar, so the shell pads by the safe-area insets (the bottom
// one: the tab bar on phones, the rail foot and the mini radio bar on iPad; Drive's grids pad their own bottom).
//
// The mini radio bar (Pro ActionBar, which brings motion) and the ⌘K command palette are lazy chunks, loaded the first
// time they are needed, so neither weighs on the eager Drive bundle (spec 4.11).

import { Component, lazy, Suspense, useState, type ErrorInfo, type ReactNode } from "react";
import { useRoute } from "../../hooks/stores";
import { AreaActionsContext, AreaHeader } from "./AreaHeader";
import { BottomTabBar } from "./BottomTabBar";
import { GameAlert } from "./GameAlert";
import { useRadio } from "../radio";
import { SpotterBars } from "../drive/SpotterBars"; // --- spotter ---
import { ScrollRow } from "../ScrollRow";
import { NavRail } from "./NavRail";
import { PhoneAppBar } from "./PhoneAppBar";
import { SubNav } from "./SubNav";
import { useDriveLock } from "./useDriveLock";
import { useShellShortcuts } from "./useShellShortcuts";

const MiniRadioBar = lazy(() => import("./MiniRadioBar").then((m) => ({ default: m.MiniRadioBar })));
const CommandPalette = lazy(() => import("./CommandPalette").then((m) => ({ default: m.CommandPalette })));

/** Around the lazy overlays: a failed chunk load (offline right after a deploy) or a render error hides the overlay
 * instead of taking the whole app down. */
class OverlayBoundary extends Component<{ name: string; children: ReactNode }, { failed: boolean }> {
  override state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`${this.props.name} failed`, error, info.componentStack);
  }

  override render(): ReactNode {
    return this.state.failed ? null : this.props.children;
  }
}

function SkipLink() {
  return (
    <a
      href="#main"
      className="sr-only z-50 rounded-lg bg-accent text-accent-foreground focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:px-3 focus:py-2"
      onClick={(e) => {
        e.preventDefault();
        document.getElementById("main")?.focus();
      }}
    >
      Skip to content
    </a>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const route = useRoute();
  const lock = useDriveLock();
  const radioLive = useRadio((s) => s.phase === "live");
  const [actionsEl, setActionsEl] = useState<HTMLElement | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteLoaded, setPaletteLoaded] = useState(false);
  useShellShortcuts(lock.locked, () => {
    setPaletteLoaded(true);
    setPaletteOpen(true);
  });
  const drive = route.area === "drive";
  const miniBar = radioLive && !drive;
  // Mounted from its first showing on (then it stays, so its exit animation still runs when it hides).
  const [barLoaded, setBarLoaded] = useState(false);
  if (miniBar && !barLoaded) setBarLoaded(true);

  return (
    <div className="flex h-dvh overflow-hidden bg-background pt-[env(safe-area-inset-top)] pr-[env(safe-area-inset-right)] pl-[env(safe-area-inset-left)]">
      <SkipLink />
      <NavRail />
      <div className="flex min-w-0 flex-1 flex-col">
        <PhoneAppBar />
        <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto overscroll-contain outline-none">
          {drive ? (
            <div className="pw-drive mx-auto w-full max-w-[1680px] md:h-full">
              <h1 className="sr-only max-md:hidden">Drive</h1>
              <ScrollRow className="sticky top-0 z-20 bg-background px-4 py-2 md:hidden">
                <SubNav area="drive" placement="drive" className="w-max" />
              </ScrollRow>
              {children}
              {/* --- spotter --- */}
              <SpotterBars />
              {/* --- end spotter --- */}
            </div>
          ) : (
            <div className={`mx-auto w-full max-w-[1680px] px-4 md:px-6 ${miniBar ? "pb-24" : "pb-8"}`}>
              <AreaHeader area={route.area} actionsRef={setActionsEl} />
              <AreaActionsContext.Provider value={actionsEl}>
                <div className="pt-2 md:pt-6">
                  <GameAlert />
                  {children}
                </div>
              </AreaActionsContext.Provider>
            </div>
          )}
        </main>
        <BottomTabBar />
      </div>
      {barLoaded && (
        <OverlayBoundary name="Mini radio bar">
          <Suspense fallback={null}>
            <MiniRadioBar visible={miniBar} />
          </Suspense>
        </OverlayBoundary>
      )}
      {paletteLoaded && (
        <OverlayBoundary name="Command palette">
          <Suspense fallback={null}>
            <CommandPalette isOpen={paletteOpen} onOpenChange={setPaletteOpen} />
          </Suspense>
        </OverlayBoundary>
      )}
    </div>
  );
}
