// ⌘K command palette (spec 3.4, 10.2): a Pro Command over every page, the recent sessions and the two display
// settings people flip most (theme, night dim). A page is found by its label, its summary and its keywords
// (routes.tsx `pageSearchText`: "badge" finds Review › Goals, "strategy" finds Drive › Car). Mac keyboard first
// (useShellShortcuts opens it); a lazy chunk, loaded on the first ⌘K. Leaving Drive › Coach while the Drive lock
// applies shows the lock hint instead (as a tap would).

import { ChartLine, Gear, Magnifier, Moon, Sun } from "@gravity-ui/icons";
import { Command } from "@heroui-pro/react";
import { useMemo, type Key, type ReactNode } from "react";
import { useApi } from "../../hooks/useApi";
import { usePrefs, useTheme } from "../../hooks/stores";
import { api, type SessionRow } from "../../lib/api";
import { prefs } from "../../lib/prefs";
import { router, sessionPath, type AreaId } from "../../lib/router";
import { dayTitle, sessionTitle } from "../../lib/review/words";
import { classChip, type SessionCarFields } from "../../lib/carclass";
import { sessionSearchText } from "../../lib/review/sessions";
import { AREAS, pageSearchText } from "../../routes";
import { EvidenceChips } from "../ui/EvidenceChips";
import { navLock } from "./navLock";
import { holdNeeded, useDriveLock } from "./useDriveLock";

const RECENT_SESSIONS = 8;

interface PaletteItem {
  id: string;
  label: ReactNode;
  textValue: string;
  detail?: ReactNode;
  icon?: ReactNode;
  run: () => void;
}

function Row({ item }: { item: PaletteItem }) {
  return (
    <span className="flex min-w-0 flex-1 items-center gap-3">
      {item.icon && <span className="grid size-5 shrink-0 place-items-center text-muted">{item.icon}</span>}
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
      {item.detail && <span className="shrink-0 text-sm text-muted">{item.detail}</span>}
    </span>
  );
}

/** A session row as /api/sessions sends it (F2 support: + car_class, car_label, session_label). */
type PaletteSession = SessionRow & SessionCarFields;

function sessionDetail(s: PaletteSession, nowMs: number): ReactNode {
  const cls = classChip(s.car_class); // "F2": F1 cars carry no chip
  return (
    <span className="inline-flex items-center gap-2">
      <EvidenceChips synthetic={s.synthetic} source={s.source} />
      {cls && <span className="font-semibold">{cls}</span>}
      {dayTitle(s.started_unix, nowMs)}
    </span>
  );
}

export function CommandPalette({ isOpen, onOpenChange }: { isOpen: boolean; onOpenChange: (open: boolean) => void }) {
  const lock = useDriveLock();
  const night = usePrefs((p) => p.night);
  const theme = useTheme();
  const { data: sessions } = useApi(isOpen ? "sessions" : null, api.sessions);

  const go = (path: string, area: AreaId, page?: string) => {
    if (holdNeeded(lock, area, page)) navLock.showHint();
    else router.navigate(path);
  };

  const groups = useMemo(() => {
    const nowMs = Date.now();
    const pages: PaletteItem[] = AREAS.flatMap((a) =>
      a.pages.map((p) => ({
        id: `page:${a.id}/${p.id}`,
        label: (
          <>
            {a.label} <span className="text-muted">›</span> {p.label}
          </>
        ),
        textValue: pageSearchText(a, p),
        detail: p.summary,
        icon: <a.icon aria-hidden="true" className="size-4" />,
        run: () => go(`/${a.id}/${p.id}`, a.id, p.id),
      })),
    );
    const recent: PaletteItem[] = [...((sessions ?? []) as PaletteSession[])]
      .sort((x, y) => y.started_unix - x.started_unix)
      .slice(0, RECENT_SESSIONS)
      .map((s) => ({
        id: `session:${s.id}`,
        label: sessionTitle(s),
        textValue: sessionSearchText(s), // "F2" finds the F2 sessions
        detail: sessionDetail(s, nowMs),
        icon: <ChartLine aria-hidden="true" className="size-4" />,
        run: () => go(sessionPath(s.id), "review", "sessions"),
      }));
    const settings: PaletteItem[] = [
      {
        id: "pref:night",
        label: night ? "Turn night dim off" : "Turn night dim on",
        textValue: "night dim dark room display",
        icon: <Moon aria-hidden="true" className="size-4" />,
        run: () => prefs.setPref("night", !night),
      },
      {
        id: "pref:theme",
        label: theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme",
        textValue: "theme light dark display appearance",
        icon: theme === "dark" ? <Sun aria-hidden="true" className="size-4" /> : <Moon aria-hidden="true" className="size-4" />,
        run: () => prefs.setPref("theme", theme === "dark" ? "light" : "dark"),
      },
      {
        id: "pref:display",
        label: "All display settings",
        textValue: "display settings text size colour vision drive lock",
        icon: <Gear aria-hidden="true" className="size-4" />,
        run: () => go("/settings/display", "settings", "display"),
      },
    ];
    return { pages, recent, settings };
  }, [sessions, night, theme, lock.locked]); // `go` reads the lock: lock.locked is the dependency

  const byId = useMemo(() => {
    const m = new Map<string, PaletteItem>();
    for (const item of [...groups.pages, ...groups.recent, ...groups.settings]) m.set(item.id, item);
    return m;
  }, [groups]);

  function onAction(key: Key) {
    const item = byId.get(String(key));
    onOpenChange(false);
    item?.run();
  }

  const item = (it: PaletteItem) => (
    <Command.Item key={it.id} id={it.id} textValue={it.textValue} className="min-h-11">
      <Row item={it} />
    </Command.Item>
  );

  return (
    <Command>
      <Command.Backdrop isOpen={isOpen} onOpenChange={onOpenChange}>
        <Command.Container>
          <Command.Dialog aria-label="Go to a page, session or setting">
            <Command.InputGroup aria-label="Search pages, sessions and settings">
              <Command.InputGroup.Prefix>
                <Magnifier aria-hidden="true" className="size-4" />
              </Command.InputGroup.Prefix>
              <Command.InputGroup.Input placeholder="Go to a page, session or setting" />
              <Command.InputGroup.ClearButton />
            </Command.InputGroup>
            <Command.List onAction={onAction} renderEmptyState={() => "Nothing matches"}>
              <Command.Group heading="Pages">{groups.pages.map(item)}</Command.Group>
              {groups.recent.length > 0 && <Command.Group heading="Recent sessions">{groups.recent.map(item)}</Command.Group>}
              <Command.Group heading="Display">{groups.settings.map(item)}</Command.Group>
            </Command.List>
          </Command.Dialog>
        </Command.Container>
      </Command.Backdrop>
    </Command>
  );
}
