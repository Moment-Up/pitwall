// The drill sheet (coachref, spec 10.2, 10.4): set up a practice drill while stopped. A HeroUI Modal on iPad, a Pro
// Sheet on a phone.
//
//   1  Corner      T1 Abbey · T3 Village [FOCUS] · T7 Copse [Work on] …        56 px rows, lap order
//   2  Skill       [Brake point | Minimum speed | Exit speed | Entry speed]   from GET /drills/options?corner=
//                  "Brake within 5 m of Sam's braking point"                  the server's target, verbatim
//   3  Laps        [3 | 5 | 8 | 10]
//   4  Window      [±3 m | ±5 m | ±10 m]                                       (hidden for beginners: the default)
//                  [ Start drill ]                                             64 px primary; a refusal inline
//
// Kinds the server cannot run here stay listed, disabled, with its reason. Nothing is computed here: targets,
// notes and refusals are the server's sentences (P9).

import { Alert, Button, Chip, ListBox, Modal, Skeleton } from "@heroui/react";
import { Segment, Sheet } from "@heroui-pro/react";
import { useEffect, useMemo, useState, type Key, type ReactNode } from "react";
import { Text } from "react-aria-components";
import { useApi } from "../../../hooks/useApi";
import { reviewApi, reviewKeys } from "../../../lib/endpoints/review";
import {
  DRILL_DEFAULT_LAPS,
  coachrefApi,
  coachrefErrorText,
  coachrefKeys,
  type DrillKind,
  type DrillOptionsResponse,
} from "../../../lib/endpoints/coachref";
import {
  cornersOf,
  defaultKind,
  kindChoices,
  lapsChoices,
  toleranceText,
  toleranceTitle,
  type KindChoice,
  type SheetCorner,
} from "../../../lib/drive/drill";
import { useMediaQuery } from "./parts";

const PHONE = "(max-width: 767px)";

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="grid content-start gap-2" aria-label={title}>
      <h3 className="m-0 flex items-center gap-2 text-[15px] font-semibold text-muted">
        <span
          aria-hidden="true"
          className="inline-flex size-6 items-center justify-center rounded-full bg-surface-tertiary text-[13px] text-foreground"
        >
          {n}
        </span>
        {title}
      </h3>
      {children}
    </section>
  );
}

function CornerList({ corners, value, onChange }: { corners: readonly SheetCorner[]; value: string | null; onChange: (c: string) => void }) {
  if (!corners.length) {
    return <p className="m-0 text-[15px] text-muted">Corners appear after your first clean lap.</p>;
  }
  return (
    <ListBox
      aria-label="Corner"
      selectionMode="single"
      disallowEmptySelection
      selectedKeys={value ? [value] : []}
      onSelectionChange={(keys) => {
        if (keys === "all") return;
        const [k] = [...keys] as Key[];
        if (k != null) onChange(String(k));
      }}
      className="max-h-[min(46dvh,420px)] gap-1 overflow-y-auto p-0"
    >
      {corners.map((c) => (
        <ListBox.Item
          key={c.name}
          id={c.name}
          textValue={[c.label, c.officialName, c.focus ? "focus" : null, c.workOn ? "work on" : null].filter(Boolean).join(" ")}
          /* pe-9: room for the selection tick (placed absolutely at the end), so a FOCUS / Work on chip never sits under it */
          className="min-h-14 gap-3 rounded-2xl ps-3 pe-9"
        >
          <span className="pw-num w-16 shrink-0 text-xl font-bold">{c.label}</span>
          <Text slot="label" className="min-w-0 flex-1 truncate text-[17px]">
            {c.officialName ?? ""}
          </Text>
          {c.focus && (
            <Chip size="sm" className="pwc-focus shrink-0">
              <Chip.Label>FOCUS</Chip.Label>
            </Chip>
          )}
          {c.workOn && (
            <Chip size="sm" variant="soft" color="warning" className="shrink-0">
              <Chip.Label>Work on</Chip.Label>
            </Chip>
          )}
          <ListBox.ItemIndicator />
        </ListBox.Item>
      ))}
    </ListBox>
  );
}

function ChoiceSegment<T extends string | number>({
  label,
  items,
  value,
  onChange,
  disabled = [],
  grid = false,
}: {
  label: string;
  items: readonly { id: T; text: string }[];
  value: T | null;
  onChange: (v: T) => void;
  disabled?: readonly T[];
  /** Two columns (four long skill names never fit one row). */
  grid?: boolean;
}) {
  return (
    <Segment
      aria-label={label}
      size="lg"
      selectedKey={value != null ? String(value) : null}
      onSelectionChange={(k: Key) => {
        const hit = items.find((i) => String(i.id) === String(k));
        if (hit) onChange(hit.id);
      }}
      className={grid ? "grid w-full grid-cols-2 gap-1" : "w-full max-w-full"}
    >
      {items.map((i) => (
        <Segment.Item key={String(i.id)} id={String(i.id)} isDisabled={disabled.includes(i.id)} className="h-14 min-w-14 flex-1 px-3 text-[15px]">
          {i.text}
        </Segment.Item>
      ))}
    </Segment>
  );
}

export function DrillSettings({
  opts,
  beginner,
  onStarted,
}: {
  opts: DrillOptionsResponse;
  beginner: boolean;
  onStarted: () => void;
}) {
  const choices = useMemo(() => kindChoices(opts), [opts]);
  const [kind, setKind] = useState<DrillKind | null>(() => defaultKind(choices));
  const [laps, setLaps] = useState<number>(opts.default_laps || DRILL_DEFAULT_LAPS);
  const chosen: KindChoice | null = choices.find((c) => c.kind === kind) ?? null;
  const [tolerance, setTolerance] = useState<number | null>(chosen?.tolerance ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Another kind: back to that kind's default window or step. (Another corner remounts this, key={corner}.)
  useEffect(() => setTolerance(chosen?.tolerance ?? null), [chosen?.kind, chosen?.tolerance]);

  if (!opts.available) {
    return (
      <p role="status" className="m-0 rounded-2xl bg-surface-secondary px-4 py-3 text-[15px]">
        {opts.reason ?? "No drill can start here now."}
      </p>
    );
  }

  const unavailable = choices.filter((c) => c.disabled && c.reason);
  async function start() {
    if (!chosen || chosen.disabled) return;
    setBusy(true);
    setError(null);
    try {
      await coachrefApi.startDrill({
        corner: opts.corner,
        kind: chosen.kind,
        laps,
        ...(tolerance != null && !beginner ? { tolerance } : {}),
        source: "manual",
      });
      onStarted();
    } catch (e) {
      setError(coachrefErrorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid content-start gap-4">
      <Step n={2} title="Skill">
        <ChoiceSegment
          label="Skill"
          items={choices.map((c) => ({ id: c.kind, text: c.label }))}
          value={kind}
          onChange={setKind}
          disabled={choices.filter((c) => c.disabled).map((c) => c.kind)}
          grid
        />
        {chosen?.targetText && <p className="m-0 text-[17px] font-medium">{chosen.targetText}</p>}
        {chosen?.note && <p className="m-0 text-[15px] text-muted">{chosen.note}</p>}
        {unavailable.length > 0 && (
          <ul className="m-0 grid list-none gap-1 p-0 text-[15px] text-muted">
            {unavailable.map((c) => (
              <li key={c.kind}>
                {c.label}: {c.reason}
              </li>
            ))}
          </ul>
        )}
      </Step>
      <Step n={3} title="Laps">
        <ChoiceSegment label="Laps" items={lapsChoices(opts).map((n) => ({ id: n, text: String(n) }))} value={laps} onChange={setLaps} />
      </Step>
      {!beginner && chosen && chosen.toleranceChoices.length > 1 && (
        <Step n={4} title={toleranceTitle(chosen.kind)}>
          <ChoiceSegment
            label={toleranceTitle(chosen.kind)}
            items={chosen.toleranceChoices.map((t) => ({ id: t, text: toleranceText(chosen.kind, t, chosen.unit) }))}
            value={tolerance}
            onChange={setTolerance}
          />
        </Step>
      )}
      {error && (
        <Alert status="danger">
          <Alert.Content>
            <Alert.Description>{error}</Alert.Description>
          </Alert.Content>
        </Alert>
      )}
      <Button
        variant="primary"
        className="pwc-glove w-full"
        isDisabled={!chosen || chosen.disabled}
        isPending={busy}
        onPress={() => void start()}
      >
        Start drill
      </Button>
    </div>
  );
}

function DrillOptionsPane({ corner, beginner, onStarted }: { corner: string | null; beginner: boolean; onStarted: () => void }) {
  const opts = useApi(corner ? coachrefKeys.drillOptions(corner) : null, () => coachrefApi.drillOptions({ corner: corner as string }), {
    maxAgeMs: 0,
  });
  if (!corner) return <p className="m-0 text-[15px] text-muted">Choose a corner to see what can be drilled there.</p>;
  if (opts.error && !opts.data) {
    return (
      <p role="alert" className="m-0 text-[15px] text-bad">
        The drill choices could not be loaded: {coachrefErrorText(opts.error)}
      </p>
    );
  }
  if (!opts.data || opts.data.corner !== corner) {
    return (
      <div aria-busy="true" aria-label="Loading the drill choices" className="grid gap-3">
        <Skeleton className="h-14 rounded-2xl" />
        <Skeleton className="h-14 rounded-2xl" />
        <Skeleton className="h-16 rounded-2xl" />
      </div>
    );
  }
  return <DrillSettings key={corner} opts={opts.data} beginner={beginner} onStarted={onStarted} />;
}

/**
 * The corners when the live snapshot has none yet (the first lap of a session: the server publishes the live model
 * with the first lap): the newest stored session at this game and track with laps, from its analysis (same learned
 * keys). Two cached requests, only while the sheet is open.
 */
function useStoredCorners(track: { game: string; trackId: string } | null): { corners: SheetCorner[] | null; loading: boolean } {
  const list = useApi(track ? reviewKeys.sessions : null, () => reviewApi.sessions());
  const sid =
    track && list.data
      ? (list.data
          .filter((r) => r.game === track.game && r.track_id === track.trackId && r.lap_count > 0)
          .sort((a, b) => b.started_unix - a.started_unix)[0]?.id ?? null)
      : null;
  const an = useApi(sid ? reviewKeys.analysis(sid) : null, () => reviewApi.analysis(sid as string), { maxAgeMs: 60_000 });
  const model = an.data?.track_model;
  return {
    corners: model?.corners.length ? cornersOf(model) : null,
    loading: !!track && (list.data === undefined || (sid != null && an.data === undefined && !an.error)) && !list.error,
  };
}

export interface DrillSheetProps {
  isOpen: boolean;
  onClose: () => void;
  corners: readonly SheetCorner[];
  /** The live game and track: when `corners` is empty, a stored model's corners stand in. */
  track?: { game: string; trackId: string } | null;
  /** The corner to start on (the coaching point's); else the first Work on / focus corner. */
  initialCorner?: string | null;
  beginner: boolean;
}

function startCorner(corners: readonly SheetCorner[], initial: string | null | undefined): string | null {
  if (initial && corners.some((c) => c.name === initial)) return initial;
  return (corners.find((c) => c.workOn) ?? corners.find((c) => c.focus))?.name ?? null;
}

export function DrillSheet({ isOpen, onClose, corners: live, track = null, initialCorner = null, beginner }: DrillSheetProps) {
  const phone = useMediaQuery(PHONE);
  const stored = useStoredCorners(isOpen && !live.length ? track : null);
  const corners = live.length ? live : (stored.corners ?? []);
  const [corner, setCorner] = useState<string | null>(() => startCorner(corners, initialCorner));
  // Only when it opens: later snapshots (the same corners, a new object) must not reset the choice.
  const [opened, setOpened] = useState(isOpen);
  const [hadCorners, setHadCorners] = useState(corners.length > 0);
  if (isOpen !== opened) {
    setOpened(isOpen);
    setHadCorners(corners.length > 0);
    if (isOpen) setCorner(startCorner(corners, initialCorner));
  } else if (isOpen && !hadCorners && corners.length > 0) {
    // The stored model's corners arrived after opening: start where it would have.
    setHadCorners(true);
    if (corner == null) setCorner(startCorner(corners, initialCorner));
  }

  const body = (
    <div className="grid gap-5 md:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <Step n={1} title="Corner">
        {!corners.length && stored.loading ? (
          <div aria-busy="true" aria-label="Loading the corners" className="grid gap-2">
            <Skeleton className="h-14 rounded-2xl" />
            <Skeleton className="h-14 rounded-2xl" />
          </div>
        ) : (
          <CornerList corners={corners} value={corner} onChange={setCorner} />
        )}
      </Step>
      <DrillOptionsPane corner={corner} beginner={beginner} onStarted={onClose} />
    </div>
  );
  const intro = "Several laps on one corner with one measurable target. The radio and the calls talk only about that corner.";

  if (phone) {
    return (
      <Sheet isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())} placement="bottom">
        <Sheet.Backdrop>
          <Sheet.Content className="max-h-[92dvh]">
            <Sheet.Dialog aria-label="Practice drill">
              <Sheet.Handle />
              <Sheet.CloseTrigger />
              <Sheet.Header>
                <Sheet.Heading className="pr-10 text-lg font-semibold">Practice drill</Sheet.Heading>
                <p className="m-0 text-sm text-muted">{intro}</p>
              </Sheet.Header>
              <Sheet.Body className="overflow-y-auto pb-[max(1rem,env(safe-area-inset-bottom))]">{isOpen && body}</Sheet.Body>
            </Sheet.Dialog>
          </Sheet.Content>
        </Sheet.Backdrop>
      </Sheet>
    );
  }
  return (
    <Modal isOpen={isOpen} onOpenChange={(o) => (o ? undefined : onClose())}>
      <Modal.Backdrop>
        <Modal.Container size="lg" scroll="inside">
          <Modal.Dialog aria-label="Practice drill" className="w-[min(880px,94vw)] max-w-[min(880px,94vw)]">
            <Modal.CloseTrigger />
            <Modal.Header>
              <Modal.Heading>Practice drill</Modal.Heading>
              <p className="m-0 text-sm text-muted">{intro}</p>
            </Modal.Header>
            <Modal.Body>{isOpen && body}</Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
