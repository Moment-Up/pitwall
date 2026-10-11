// Every item of the walkthrough section beside the step card (spec 7.2): a Pro ListView with the menu code (rows),
// a short line, the value and a done tick; the current item is highlighted and tapping a row jumps to it. Rows are
// 56 px (touch on a rig, P12).

import { ListView } from "@heroui-pro/react";
import { useEffect, useRef, type Key } from "react";
import { SettingValue } from "../../../components/ui";
import { itemState, itemTitle, type Ticks, type WalkSection } from "../../../lib/setup/walkthrough";
import { TickIcon } from "./parts";

export function SectionList({
  section,
  current,
  ticks,
  onJump,
  className = "",
}: {
  section: WalkSection;
  current: number;
  ticks: Ticks;
  onJump: (index: number) => void;
  className?: string;
}) {
  const rows = section.items.map((item, index) => ({ item, index, id: item.id }));
  const box = useRef<HTMLDivElement>(null);
  const currentId = rows[current]?.id;
  // Keep the step on screen in view in the scrolling list (react-aria renders data-key on each row).
  useEffect(() => {
    if (!currentId) return;
    // After the collection has rendered its rows (react-aria builds them in a second pass).
    const raf = requestAnimationFrame(() => {
      const c = box.current;
      const el = c?.querySelector<HTMLElement>(`[data-key="${CSS.escape(currentId)}"]`);
      if (!c || !el) return;
      // Scroll the list only (scrollIntoView would also move the page under the step card).
      const cr = c.getBoundingClientRect();
      const er = el.getBoundingClientRect();
      // Out of the list's upper half: bring it to about a third of the way down.
      if (er.top < cr.top || er.bottom > cr.top + cr.height / 2) c.scrollTop += er.top - cr.top - cr.height / 3;
    });
    return () => cancelAnimationFrame(raf);
  }, [currentId]);
  return (
    <div ref={box} className={className}>
      <ListView
        aria-label={`${section.title}: every step`}
        items={rows}
        onAction={(key: Key) => {
          const r = rows.find((x) => x.id === key);
          if (r) onJump(r.index);
        }}
      >
        {({ item, index, id }) => {
          const t = itemTitle(item);
          const state = itemState(item, ticks);
          const cur = index === current;
          return (
            <ListView.Item
              id={id}
              textValue={`${t.code ?? index + 1} ${t.text}`}
              aria-current={cur ? "step" : undefined}
              className={`min-h-14 ${cur ? "bg-[color-mix(in_oklab,var(--accent)_12%,var(--surface))]" : ""}`}
            >
              <ListView.ItemContent>
                <div className="flex w-full min-w-0 items-center gap-3">
                  <span className={`w-12 shrink-0 font-mono text-[13px] font-bold ${t.code ? "" : "text-faint"}`}>{t.code ?? index + 1}</span>
                  <span className={`min-w-0 flex-1 truncate text-sm ${cur ? "text-foreground" : "text-muted"}`}>{t.text}</span>
                  {t.value !== null ? (
                    t.value === "check" ? (
                      <span className="shrink-0 text-sm font-semibold">check</span>
                    ) : (
                      <SettingValue value={t.value} size="list" className="max-w-24 shrink-0 truncate" />
                    )
                  ) : null}
                  <span
                    className="flex w-[18px] shrink-0 justify-center"
                    aria-label={state === "done" ? "done" : state === "updated" ? "updated since ticked" : undefined}
                  >
                    {state === "done" ? (
                      <TickIcon />
                    ) : state === "updated" ? (
                      <span className="size-2 rounded-full bg-warning" aria-hidden="true" />
                    ) : null}
                  </span>
                </div>
              </ListView.ItemContent>
            </ListView.Item>
          );
        }}
      </ListView>
    </div>
  );
}
