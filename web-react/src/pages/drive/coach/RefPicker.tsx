// The delta reference control and picker (coachref, spec 10.1, 10.2, 10.4). The delta panel's label row and the
// Ready card's Target column carry the same control:
//
//   [ Delta to · Sam's best ⌄ ]   (56 px ghost button, 22 px text; Ready card 64 px)
//
// Stopped (pit, garage, paused, under 30 km/h): it opens the picker - a HeroUI Popover on iPad, a Pro Sheet on a
// phone - with rows of at least 56 px from GET /api/coachref/options: Your best, Family record, each other driver's
// best (unavailable rows disabled, with the server's reason), then "A saved lap…". "Only at {track}" stores the
// choice for this track only. A change made now applies at once; one that waits says so in the status slot.
// Moving: the picker stays shut. If the choice is not "Your best", a one-row popover offers "Back to your best" (the
// one trivial change allowed on track; it closes by itself after 5 s, as it covers the delta); otherwise the status
// slot says "Change the reference when stopped".

import { ChevronDown } from "@gravity-ui/icons";
import { Avatar, Button, Popover } from "@heroui/react";
import { lazy, memo, Suspense, useEffect, useState } from "react";
import { inkOn } from "../../../lib/drivers";
import { coachrefApi, coachrefErrorText } from "../../../lib/endpoints/coachref";
import { NOTICE_CHANGE_MS, NOTICE_HINT_MS, POPOVER_AUTO_CLOSE_MS, driveNotice } from "../../../lib/drive/notice";
import { BACK_TO_BEST, LOCKED_HINT, appliesNotice, type RefControlView, type RefHolder } from "../../../lib/drive/reference";
import { useMediaQuery } from "./parts";
import { sameProps } from "./view";

// The picker's content and the phone Sheet are their own chunk (spec 4.11): loaded the first time the picker opens.
const RefPickerBody = lazy(async () => ({ default: (await import("./RefPickerBody")).RefPickerBody }));
const RefPickerSheet = lazy(async () => ({ default: (await import("./RefPickerBody")).RefPickerSheet }));

const PHONE = "(max-width: 767px)";

/** A reference holder's initials (their profile colour when there is a profile). */
export function HolderAvatar({ holder, size = 20 }: { holder: RefHolder; size?: number }) {
  const colour = holder.colour;
  return (
    <Avatar aria-hidden="true" className="shrink-0 overflow-hidden rounded-full" style={{ width: size, height: size }}>
      <Avatar.Fallback
        className="font-bold"
        style={{
          fontSize: Math.max(9, Math.round(size * 0.42)),
          ...(colour ? { backgroundColor: colour, color: inkOn(colour) } : {}),
        }}
      >
        {holder.initials}
      </Avatar.Fallback>
    </Avatar>
  );
}

function BackToBestRow({ view, onClose }: { view: RefControlView; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function go() {
    if (!view.backToBest) return;
    setBusy(true);
    setError(null);
    try {
      const r = await coachrefApi.setChoice(view.backToBest);
      const notice = appliesNotice(r.applies, "own_best", "Your best");
      if (notice) driveNotice.show(notice, NOTICE_CHANGE_MS);
      onClose();
    } catch (e) {
      setError(coachrefErrorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="grid gap-2">
      <Button variant="secondary" className="min-h-14 w-full justify-start text-[17px]" isPending={busy} onPress={() => void go()}>
        {BACK_TO_BEST}
      </Button>
      <p className="m-0 px-1 text-[13px] text-muted">
        Other choices when stopped. It applies {view.frozen ? "after the drill" : "from the next lap"}.
      </p>
      {error && (
        <p role="alert" className="m-0 px-1 text-[15px] text-bad">
          {error}
        </p>
      )}
    </div>
  );
}

export interface RefControlProps {
  view: RefControlView;
  /** "delta": the delta panel's label row (56 px); "ready": the Ready card's Target column (64 px). */
  variant: "delta" | "ready";
}

export const RefControl = memo(function RefControl({ view, variant }: RefControlProps) {
  const phone = useMediaQuery(PHONE);
  const [popover, setPopover] = useState<"none" | "back" | "picker">("none");
  const [sheet, setSheet] = useState(false);

  // Moving again with the picker open: it closes (P2, nothing to fiddle with on track); "Back to your best" stays.
  useEffect(() => {
    if (view.locked && popover === "picker") setPopover("none");
    if (view.locked && sheet) setSheet(false);
  }, [view.locked, popover, sheet]);
  // "Back to your best" covers the delta while driving: it closes by itself (the control opens it again).
  useEffect(() => {
    if (popover !== "back") return;
    const t = setTimeout(() => setPopover("none"), POPOVER_AUTO_CLOSE_MS);
    return () => clearTimeout(t);
  }, [popover]);

  const onPress = () => {
    // A second tap on the control closes what it opened (the Popover's trigger has already toggled it shut).
    if (popover !== "none") {
      close();
      return;
    }
    if (view.locked) {
      if (view.backToBest) setPopover("back");
      else driveNotice.show(LOCKED_HINT, NOTICE_HINT_MS);
      return;
    }
    if (phone) setSheet(true);
    else setPopover("picker");
  };
  const close = () => {
    setPopover("none");
    setSheet(false);
  };

  const ready = variant === "ready";
  const words = ready ? view.label : view.text;
  const button = (
    <Button
      variant={ready ? "secondary" : "ghost"}
      className={ready ? "pwc-refctl pwc-refctl--ready" : "pwc-refctl"}
      // The visible words first (label in name), then what a tap does.
      aria-label={`${ready ? `Delta reference: ${words}` : words}, ${view.ariaHint}`}
      onPress={onPress}
    >
      <span className="pwc-refctl__text">{words}</span>
      <ChevronDown aria-hidden="true" className="pwc-refctl__chev" />
    </Button>
  );

  return (
    <>
      <Popover isOpen={popover !== "none"} onOpenChange={(o) => (o ? undefined : close())}>
        {button}
        <Popover.Content placement="bottom start" className="w-[min(440px,92vw)]">
          <Popover.Dialog aria-label={popover === "back" ? BACK_TO_BEST : "Delta reference"} className="max-h-[70dvh] overflow-y-auto p-2">
            {popover === "back" ? (
              <BackToBestRow view={view} onClose={close} />
            ) : popover === "picker" ? (
              <>
                <Popover.Heading className="m-0 px-3 pt-1 pb-2 text-[15px] font-semibold text-muted">
                  What the delta and braking calls measure against
                </Popover.Heading>
                <Suspense fallback={<p className="m-0 px-3 py-2 text-[15px] text-muted">Loading…</p>}>
                  <RefPickerBody driverId={view.driverId} trackName={view.trackName} onClose={close} />
                </Suspense>
              </>
            ) : null}
          </Popover.Dialog>
        </Popover.Content>
      </Popover>
      {phone && sheet && (
        <Suspense fallback={null}>
          <RefPickerSheet isOpen={sheet} driverId={view.driverId} trackName={view.trackName} onClose={close} />
        </Suspense>
      )}
    </>
  );
}, sameProps);
