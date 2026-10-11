// Mini radio bar (spec 3.5): outside Drive, while the radio is live, a Pro ActionBar floating pill at the bottom
// centre of the content area (above the tab bar on phones). Prefix: live dot + "Radio". Content: the latest message
// (one line, ellipsis, 8 s). Suffix: a 48 px Hold to talk button and an icon button that opens Drive › Radio. While
// it shows, the shell pads every page's bottom by 96 px so it never covers a primary action.
//
// The radio store is module level (lib/radio.ts, lane A), so the radio keeps running on every page; the message and
// the push-to-talk button are lane A's radio kit (components/radio).

import { ArrowUpRightFromSquare } from "@gravity-ui/icons";
import { ActionBar } from "@heroui-pro/react";
import { Button, Chip } from "@heroui/react";
import { PushToTalkButton, RadioMessage } from "../radio";
import { router } from "../../lib/router";

/** `visible` = the radio is live and no Drive page is open (AppShell decides, and pads pages by 96 px meanwhile). */
export function MiniRadioBar({ visible }: { visible: boolean }) {
  // ActionBar's className styles its inner toolbar; the fixed outer `.action-bar` is placed from this wrapper:
  // centred on the content area (right of the rail) on iPad and Mac, above the tab bar on phones.
  return (
    <div className="contents [&_.action-bar]:bottom-[calc(var(--pw-tabbar-h,64px)+env(safe-area-inset-bottom)+12px)] [&_.action-bar]:px-4 md:[&_.action-bar]:bottom-[calc(18px+env(safe-area-inset-bottom))] md:[&_.action-bar]:left-[var(--pw-rail-w,72px)]">
      <ActionBar aria-label="Radio" isOpen={visible} className="max-w-[640px]">
        <ActionBar.Prefix>
          <Chip size="sm" variant="soft" color="success" className="gap-1.5 font-bold tracking-[0.08em]">
            <span aria-hidden="true" className="size-2 rounded-full bg-current" />
            <Chip.Label>RADIO</Chip.Label>
          </Chip>
        </ActionBar.Prefix>
        <ActionBar.Content className="min-w-0 max-w-[440px]">
          {visible && <RadioMessage size="mini" hideAfterS={8} />}
        </ActionBar.Content>
        <ActionBar.Suffix className="gap-2">
          {visible && <PushToTalkButton size="mini" />}
          <Button
            isIconOnly
            variant="ghost"
            aria-label="Open Drive › Radio"
            onPress={() => router.navigate("/drive/radio")}
            className="size-12"
          >
            <ArrowUpRightFromSquare aria-hidden="true" />
          </Button>
        </ActionBar.Suffix>
      </ActionBar>
    </div>
  );
}
