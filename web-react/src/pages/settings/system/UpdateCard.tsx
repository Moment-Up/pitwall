// Settings › System › Updates (lane install, spec §8): whether a newer Pitwall is on GitHub, what changed, and the
// one command that updates it. Read-only: there is no "Update now" (the server cannot safely replace itself, and a
// device on the network must never trigger a code change). "Check now" asks the server to look again.
//
// Order: the status, then what to do (the command, or how a git checkout updates), then what changed in the newest
// release (older ones folded under "Also new"), then Check now. So the command is on the first screen, also on a phone.
//
// UpdateCardView is pure (render-tested in update-card.test.ts); UpdateCard binds it to GET /api/update, polling
// every 60 s and every 2 s while a check runs. An older server without /api/update renders nothing.

import { Alert, Button, Card, Chip, Link, Skeleton } from "@heroui/react";
import { useEffect, useRef, useState } from "react";
import { CopyField } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import { cache } from "../../../lib/cache";
import { messageOf } from "../../../lib/endpoints/settings";
import { UPDATE_KEY, isNotFound, updateApi, type UpdateStatus } from "../../../lib/endpoints/update";
import {
  CARD_DESCRIPTION,
  NOTES_SHOWN,
  OLDER_KEY,
  TOO_SOON_NOTE,
  checkSkipped,
  shownNotes,
  showUpdateChip,
  updateView,
  updatedTo,
  versionText,
  type ReleaseView,
  type UpdateTone,
} from "./update-model";

/** Links read as links: HeroUI's external-link icon after the text (the Link's colour is close to body text here). */
const LINK_CLASS = "inline-flex min-h-11 items-center gap-1 text-sm";

function StatusChip({ tone, children }: { tone: UpdateTone; children: string }) {
  return (
    <Chip variant="soft" color={tone} size="lg" className="gap-1.5">
      <span aria-hidden="true" className="size-2 rounded-full bg-current" />
      <Chip.Label>{children}</Chip.Label>
    </Chip>
  );
}

function GuideLink({ href }: { href: string }) {
  return (
    <Link
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={LINK_CLASS}
      aria-label="Updating Pitwall, in the install guide on GitHub (opens in a new tab)"
    >
      Install guide
      <Link.Icon />
    </Link>
  );
}

function ReleaseNotes(p: { r: ReleaseView; showDate: boolean; expanded: boolean; onToggle: () => void }) {
  const { r, expanded, onToggle } = p;
  const { items } = shownNotes(r.notes, expanded);
  const long = r.notes.length > NOTES_SHOWN;
  const id = `pw-update-notes-${r.version.replace(/[^0-9A-Za-z-]/g, "-")}`;
  return (
    <section aria-labelledby={id} className="grid min-w-0 gap-2 rounded-2xl bg-surface-secondary px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <h4 id={id} className="m-0 text-sm font-semibold">
          What changed in {r.version}
        </h4>
        {r.prerelease && (
          <Chip size="sm" variant="soft">
            <Chip.Label>Pre-release</Chip.Label>
          </Chip>
        )}
        {p.showDate && r.date && <span className="text-xs text-muted">{r.date}</span>}
      </div>
      {items.length > 0 ? (
        <ul className="m-0 grid min-w-0 list-disc gap-1 pl-5 text-sm break-words">
          {items.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-sm text-muted">The release notes have no list of changes.</p>
      )}
      {(long || r.url) && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          {long && (
            <Button className="min-h-11" variant="ghost" onPress={onToggle} aria-expanded={expanded}>
              {expanded ? "Show fewer" : `Show all ${r.notes.length}`}
            </Button>
          )}
          {r.url && (
            <Link
              href={r.url}
              target="_blank"
              rel="noopener noreferrer"
              className={LINK_CLASS}
              aria-label={`Release notes for ${r.version} on GitHub (opens in a new tab)`}
            >
              Release notes on GitHub
              <Link.Icon />
            </Link>
          )}
        </div>
      )}
    </section>
  );
}

export interface UpdateCardViewProps {
  status: UpdateStatus | undefined;
  /** The last GET /api/update error (stale data stays on screen with it). */
  loadError: Error | null;
  /** "Check now" is running. */
  busy: boolean;
  /** "Check now" failed: the server's words. */
  actionError: string | null;
  /** "Check now" answered without a new check (one finished less than a minute ago). */
  tooSoon?: boolean;
  /** The server now runs this version, not the one this page was loaded with (after `pitwall update`). */
  updatedTo?: string | null;
  /** Browser clock, seconds. */
  nowUnix: number;
  /** Releases whose full "What changed" list is open (and OLDER_KEY: the older releases are shown). */
  expanded: ReadonlySet<string>;
  onToggle: (version: string) => void;
  onCheck: () => void;
  onRetry: () => void;
  onReload?: () => void;
}

export function UpdateCardView(p: UpdateCardViewProps) {
  // An older server has no /api/update: nothing to show (not an error the driver can act on).
  if (isNotFound(p.loadError)) return null;
  const v = p.status ? updateView(p.status, p.nowUnix) : null;
  const checking = p.busy || v?.state === "checking";
  const [newest, ...older] = v?.releases ?? [];
  const olderOpen = p.expanded.has(OLDER_KEY);

  return (
    <Card className="min-w-0">
      <Card.Header>
        <Card.Title className="text-base font-semibold">Updates</Card.Title>
        <Card.Description>{CARD_DESCRIPTION}</Card.Description>
      </Card.Header>
      <Card.Content className="grid min-w-0 grid-cols-1 gap-3">
        {p.updatedTo && (
          <Alert status="success">
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Title>Pitwall was updated to {p.updatedTo}</Alert.Title>
              <Alert.Description>Reload this page to use it.</Alert.Description>
            </Alert.Content>
            {p.onReload && (
              <Button className="min-h-11" size="lg" variant="secondary" onPress={p.onReload}>
                Reload
              </Button>
            )}
          </Alert>
        )}
        {!v ? (
          p.loadError ? (
            <div className="grid gap-2">
              <p className="m-0 text-sm text-bad">Couldn&apos;t load the update status: {messageOf(p.loadError)}</p>
              <div>
                <Button className="min-h-11" size="lg" variant="secondary" onPress={p.onRetry}>
                  Try again
                </Button>
              </div>
            </div>
          ) : (
            <Skeleton className="h-24 rounded-2xl" />
          )
        ) : (
          <>
            <div className="grid min-w-0 gap-2" role="status" aria-live="polite">
              <div>
                <StatusChip tone={v.tone}>{v.label}</StatusChip>
              </div>
              <p className="m-0 min-w-0 text-sm break-words">{v.line}</p>
            </div>

            {v.command && (
              <div className="grid min-w-0 gap-2">
                <h4 className="m-0 text-sm font-semibold">{v.commandIntro}</h4>
                <CopyField value={v.command} label="Update command" labelHidden />
                <p className="m-0 text-xs text-muted">{v.commandHelp}</p>
                <div>
                  <GuideLink href={v.docsUrl} />
                </div>
              </div>
            )}
            {v.howNote && (
              <div className="grid min-w-0 gap-1">
                <p className="m-0 text-sm text-muted">{v.howNote}</p>
                <div>
                  <GuideLink href={v.docsUrl} />
                </div>
              </div>
            )}

            {newest && (
              <ReleaseNotes
                r={newest}
                showDate={false /* the newest one's date is in the line above */}
                expanded={p.expanded.has(newest.version)}
                onToggle={() => p.onToggle(newest.version)}
              />
            )}
            {older.length > 0 && (
              <div className="grid min-w-0 gap-3">
                <div>
                  <Button
                    className="min-h-11"
                    variant="ghost"
                    onPress={() => p.onToggle(OLDER_KEY)}
                    aria-expanded={olderOpen}
                  >
                    {olderOpen ? "Hide older releases" : `Also new: ${older.map((r) => r.version).join(", ")}`}
                  </Button>
                </div>
                {olderOpen &&
                  older.map((r) => (
                    <ReleaseNotes
                      key={r.version}
                      r={r}
                      showDate
                      expanded={p.expanded.has(r.version)}
                      onToggle={() => p.onToggle(r.version)}
                    />
                  ))}
              </div>
            )}

            {p.actionError && (
              <Alert status="danger">
                <Alert.Indicator />
                <Alert.Content>
                  <Alert.Title>Couldn&apos;t check for updates</Alert.Title>
                  <Alert.Description>{p.actionError}</Alert.Description>
                </Alert.Content>
              </Alert>
            )}
            {p.loadError && <p className="m-0 text-xs text-warning">Couldn&apos;t refresh: {messageOf(p.loadError)}</p>}

            <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
              {v.canCheck && (
                <Button className="min-h-11" size="lg" variant="secondary" isPending={checking} onPress={p.onCheck}>
                  Check now
                </Button>
              )}
              {v.checked && <span className="text-xs text-muted">{v.checked}</span>}
              {p.tooSoon && !checking && <span className="text-xs text-muted">{TOO_SOON_NOTE}</span>}
            </div>
          </>
        )}
      </Card.Content>
    </Card>
  );
}

/** The update status for this page (one cache key, shared with the Version row and the Server tile). */
function useUpdateStatus(intervalMs?: number) {
  return useApi(UPDATE_KEY, updateApi.status, intervalMs ? { intervalMs } : {});
}

export function UpdateCard() {
  const st = useUpdateStatus(60_000);
  // A faster poll while the server is checking GitHub (the answer usually lands within a few seconds).
  useApi(st.data?.checking ? UPDATE_KEY : null, updateApi.status, { intervalMs: 2_000, maxAgeMs: 0 });
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [tooSoon, setTooSoon] = useState(false);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  // The version this page was loaded with: a different one later means `pitwall update` restarted the server.
  const firstSeen = useRef<string | null>(null);
  useEffect(() => {
    if (firstSeen.current === null && st.data?.current) firstSeen.current = st.data.current;
  }, [st.data?.current]);

  async function check() {
    const before = st.data;
    setBusy(true);
    setActionError(null);
    setTooSoon(false);
    try {
      const after = await updateApi.check();
      cache.set(UPDATE_KEY, after);
      setTooSoon(checkSkipped(before, after));
    } catch (e) {
      setActionError(messageOf(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <UpdateCardView
      status={st.data}
      loadError={st.error}
      busy={busy}
      actionError={actionError}
      tooSoon={tooSoon}
      updatedTo={updatedTo(firstSeen.current, st.data)}
      nowUnix={Date.now() / 1000}
      expanded={expanded}
      onToggle={(version) =>
        setExpanded((prev) => {
          const next = new Set(prev);
          if (next.has(version)) next.delete(version);
          else next.add(version);
          return next;
        })
      }
      onCheck={() => void check()}
      onRetry={() => void st.refresh()}
      onReload={() => window.location.reload()}
    />
  );
}

/** The Version row's chip: "Update available" when the server says so, else nothing (also on an older server). */
export function UpdateChip() {
  const st = useUpdateStatus();
  if (!showUpdateChip(st.data)) return null;
  return (
    <Chip size="sm" variant="soft" color="warning">
      <Chip.Label>Update available</Chip.Label>
    </Chip>
  );
}

/** The running version for the Server card and tile: the update status's tag (RELEASE.txt in a release), else
 * "v" + /api/health's version (an older server, or before the status loads). */
export function VersionText({ fallback }: { fallback: string | null | undefined }) {
  const st = useUpdateStatus();
  return <>{versionText(st.data, fallback) ?? ""}</>;
}
