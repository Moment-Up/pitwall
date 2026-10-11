// Drive › Track (design spec 5.2, C; mockup driveTrack): for learning a new track in practice. Left (7 columns): the
// large map with the live car, the corner highlighted (the one picked in the list, else the car's next corner),
// sector labels, yellow zones and brake notches. Right (5 columns): every corner as a Pro ListView row with its
// official label and long name, direction, FOCUS, and what the coach said about it on the last lap (verbatim).
// Tapping a row selects it on the map; "Follow the car" under the map goes back to the car's next corner. The picked
// row's "See it on the lap" opens Review › Compare at that corner. Pure: the page owns the selection. Lane DV.

import { Button, Chip } from "@heroui/react";
import { ListView } from "@heroui-pro/react";
import { memo } from "react";
import type { Key, Selection } from "react-aria-components";
import { TrackMap } from "../../../components/viz";
import { gameLength } from "../../../lib/drive/geometry";
import type { DriveModel } from "../../../lib/drive/model";
import type { SnapshotNext } from "../../../lib/drive/types";
import { router } from "../../../lib/router";
import type { BrakePrior, TrackOutline } from "../../../lib/viz/outline";
import { DriveFrame } from "../DriveFrame";
import { sameProps } from "../coach/view";
import { Tile } from "../wall-parts";
import type { CornerRow, TrackView } from "./view";

export interface TrackScreenProps {
  model: DriveModel;
  snap: SnapshotNext | null;
  view: TrackView;
  /** The corner picked in the list (learned name), or null to follow the car. */
  selected: string | null;
  onSelect: (corner: string | null) => void;
  maySleep?: boolean;
  outline?: TrackOutline | null;
  prior?: BrakePrior | null;
}

function CornerTitle({ r }: { r: CornerRow }) {
  return (
    <span className="pww-corner__title">
      <span className={r.title ? "" : "text-muted"}>{r.title ?? "Learned corner"}</span>
      {r.focus && (
        <Chip size="sm" className="pww-focus">
          <Chip.Label>FOCUS</Chip.Label>
        </Chip>
      )}
      {r.live && (
        <Chip size="sm" variant="soft">
          <Chip.Label>{r.live === "in" ? "In corner" : "Next"}</Chip.Label>
        </Chip>
      )}
    </span>
  );
}

function CornerSub({ r }: { r: CornerRow }) {
  const parts: string[] = [];
  if (r.direction) parts.push(r.direction);
  if (r.focusReason) parts.push(r.focusReason);
  return (
    <span className="pww-corner__sub">
      {parts.join(" · ")}
      {r.note && (
        <>
          {parts.length ? " · " : ""}
          <span className="pww-corner__note">{r.note.text}</span>
          {r.note.lap != null && <span> (lap {r.note.lap})</span>}
        </>
      )}
      {!r.note && !parts.length && <span>No note on the last lap</span>}
    </span>
  );
}

interface CornerListProps {
  rows: CornerRow[];
  empty: string | null;
  selected: string | null;
  onSelect: (corner: string | null) => void;
}

/** The corner list, memoised on its content: it re-renders when a note, the live corner or the pick changes, never
 * per frame (the map next to it moves the car 20 times a second). */
const CornerList = memo(function CornerList({ rows, empty, selected, onSelect }: CornerListProps) {
  return (
    <Tile span={5} title="Corners" aside="what the coach said on the last lap" className="pww-wide">
      <div className="pww-scroll">
        {empty ? (
          <p className="m-0 py-3 text-sm text-muted">{empty}</p>
        ) : (
          <ListView
            aria-label="Corners in lap order"
            items={rows}
            variant="secondary"
            selectionMode="single"
            // Replace, not toggle: a tap picks the row (no checkbox column); "Follow the car" under the map un-picks.
            selectionBehavior="replace"
            selectedKeys={selected ? [selected] : []}
            onSelectionChange={(keys) => onSelect(selectedOf(keys))}
            className="pww-corners"
          >
            {(r) => (
              <ListView.Item id={r.name} textValue={`${r.label} ${r.title ?? ""}`}>
                <ListView.ItemContent className="items-start">
                  <span className="pww-kbd">{r.label}</span>
                  <span className="grid min-w-0 gap-1">
                    <CornerTitle r={r} />
                    <CornerSub r={r} />
                  </span>
                </ListView.ItemContent>
                {r.name === selected && r.compareHref && (
                  <ListView.ItemAction>
                    <Button variant="tertiary" className="h-11" onPress={() => router.navigate(r.compareHref as string)}>
                      See it on the lap
                    </Button>
                  </ListView.ItemAction>
                )}
              </ListView.Item>
            )}
          </ListView>
        )}
      </div>
    </Tile>
  );
}, sameProps);

function selectedOf(keys: Selection): string | null {
  if (keys === "all") return null;
  const first = [...keys][0] as Key | undefined;
  return first == null ? null : String(first);
}

export function TrackScreen({ model, snap, view, selected, onSelect, maySleep = false, outline = null, prior = null }: TrackScreenProps) {
  const sel = selected && view.rows.some((r) => r.name === selected) ? selected : null;
  const shown = sel ? view.rows.find((r) => r.name === sel) : null;
  const highlight = sel ?? view.liveCorner;
  return (
    <DriveFrame status={model.status} maySleep={maySleep} dim={model.dim} state={model.state}>
      <Tile
        span={7}
        title="Track"
        aside={view.caption}
        className="pww-wide"
        foot={
          shown ? (
            <span className="pww-follow">
              Showing {shown.label}
              {shown.title ? ` ${shown.title}` : ""} ·{" "}
              <Button size="sm" variant="ghost" onPress={() => onSelect(null)} className="h-11 px-3 align-middle">
                Follow the car
              </Button>
            </span>
          ) : view.note ? (
            view.note
          ) : view.car || view.carM != null ? (
            "Following the car: the next corner is highlighted"
          ) : (
            "Tap a corner in the list to find it on the map"
          )
        }
      >
        <TrackMap
          model={snap?.track_model}
          skeleton={snap?.skeleton ?? null}
          lengthM={gameLength(snap)}
          car={view.car}
          carM={view.car ? null : view.carM}
          highlight={highlight}
          focus={view.focus}
          cueTargetsM={view.cueTargetsM}
          flags={view.flags}
          outline={outline}
          prior={prior}
          labels="all"
          height="100%"
          className="pww-map pww-maptall"
        />
      </Tile>
      <CornerList rows={view.rows} empty={view.empty} selected={sel} onSelect={onSelect} />
    </DriveFrame>
  );
}
