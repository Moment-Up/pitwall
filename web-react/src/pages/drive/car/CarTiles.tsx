// The Car wall's tiles (design spec 5.1; mockup driveCar). Each tile receives a plain view model from ./view.ts and
// is memoised on its content, so a tile re-renders only when its own text changes (the car tile at the snapshot
// rate, the laps tile once a lap). Lane DV.
//
//   Car (4)             speed · gear · RPM · throttle · brake · steering · bias · DRS · telemetry health
//   Track (5)           TrackMap: sectors as set (D1), car, next corner, focus rings, brake notches, live yellows
//   Tyres & energy (3)  FL FR / RL RR temperature (inside with the carcass model, else surface; colour + word against
//                       the driver's own warm laps, health lane), wear · pressure; fuel, ERS; brakes · engine; the last
//                       lap's lock-ups and wheelspin (what the game does not send in words: one line for no tyre data,
//                       a caption for no wear / pressures)
//   Inputs (4)          LiveTrace: speed / throttle / brake, last 12 s, canvas at 10 Hz
//   Laps (5)            Pro DataGrid, 8 newest by current standing, R / PIT / INV; two-line rows below 600 px
//   Coaching (3)        Pro ListView, up to 3 points of the last lap: corner chip, text, time in the corner

import { Chip, Meter } from "@heroui/react";
import { DataGrid, ListView, type DataGridColumn } from "@heroui-pro/react";
import { memo } from "react";
import { TimingLegend, TimingTag, TimingValue } from "../../../components/ui";
import { LiveTrace, TrackMap, useElementSize } from "../../../components/viz";
import { cssVars } from "../../../lib/css";
import type { TrackModelNext } from "../../../lib/drive/types";
import type { HistoryPoint } from "../../../lib/live";
import type { TrackSkeleton } from "../../../lib/skeleton";
import type { BrakePrior, TrackOutline } from "../../../lib/viz/outline";
import { sameProps } from "../coach/view";
import { useMediaQuery } from "../coach/parts";
import { Tile, Val } from "../wall-parts";
import { RaceControlFoot } from "./RaceControlFoot"; // race radio (pitwall.raceradio)
import type { CarTileView, CoachingTileView, LapRowView, LapsTileView, MeterView, TyresView, WallMapView } from "./view";

// ------------------------------------------------------------------------------------------------------- car

function LiveMeter({ label, m, fill }: { label: string; m: MeterView; fill: string }) {
  const unknown = m.frac == null;
  return (
    <Meter
      aria-label={label}
      value={unknown ? 0 : (m.frac as number) * 100}
      // The meter needs a number; assistive tech reads this text instead, so an unknown value is never "0 percent".
      valueLabel={unknown ? "unknown" : m.text}
      className={unknown ? "pww-meter pww-meter--unknown" : "pww-meter"}
      style={cssVars({ "--meter-fill": fill })}
    >
      <span data-slot="label">{label}</span>
      <Meter.Output>{m.text}</Meter.Output>
      <Meter.Track>
        <Meter.Fill />
      </Meter.Track>
    </Meter>
  );
}

export const CarTile = memo(function CarTile({ v }: { v: CarTileView }) {
  return (
    <Tile
      span={4}
      title="Car"
      aside={
        <Chip size="sm" variant="soft">
          <Chip.Label>{v.rate}</Chip.Label>
        </Chip>
      }
      foot={v.health}
      footWrap
    >
      <div className="pww-big">
        <div>
          <div className="pww-big__v" aria-label={`Speed ${v.speed === "-" ? "unknown" : `${v.speed} km/h`}`}>
            <Val text={v.speed} />
          </div>
          <div className="pww-big__u">km/h</div>
        </div>
        <div className="text-right">
          <div className="pww-big__v" data-gear="" aria-label={`Gear ${v.gear === "-" ? "unknown" : v.gear}`}>
            <Val text={v.gear} />
          </div>
          <div className="pww-big__u">gear</div>
        </div>
      </div>
      <div className="pww-meters">
        <LiveMeter label="RPM" m={v.rpm} fill={v.rpm.hot ? "var(--pw-bad)" : "var(--accent)"} />
        <LiveMeter label="Throttle" m={v.throttle} fill="var(--pw-throttle)" />
        <LiveMeter label="Brake" m={v.brake} fill="var(--pw-brake)" />
      </div>
      <div className="pww-kv">
        <span>
          Steering
          <b>
            <Val text={v.steering} label="Steering" />
          </b>
        </span>
        <span>
          Bias
          <b>
            <Val text={v.bias} label="Brake bias" />
          </b>
        </span>
        {v.drsShown && (
          <span>
            DRS
            <b>
              <Val text={v.drs} label="DRS" />
            </b>
          </span>
        )}
      </div>
    </Tile>
  );
}, sameProps);

// ------------------------------------------------------------------------------------------------------- map

export interface MapTileProps {
  model: TrackModelNext | null | undefined;
  skeleton: TrackSkeleton | null | undefined;
  lengthM: number | null;
  view: WallMapView;
  outline: TrackOutline | null;
  prior: BrakePrior | null;
  raceControl: string;
  /** race radio: the note on the race position's evidence (view.raceNote), shown under the line; null = none. */
  raceNote?: string | null;
}

export function MapTile({ model, skeleton, lengthM, view, outline, prior, raceControl, raceNote = null }: MapTileProps) {
  const foot = raceNote ? <RaceControlFoot line={raceControl} note={raceNote} /> : raceControl;
  return (
    <Tile span={5} title="Track" aside={view.caption} foot={foot}>
      <TrackMap
        model={model}
        skeleton={skeleton ?? null}
        lengthM={lengthM}
        car={view.car}
        carM={view.car ? null : view.carM}
        highlight={view.highlight}
        focus={view.focus}
        sectorStatus={view.sectorStatus}
        cueTargetsM={view.cueTargetsM}
        flags={view.flags}
        outline={outline}
        prior={prior}
        labels="key"
        height="100%"
        className="pww-map"
      />
      {view.borrowed && <p className="pww-map__note">{view.borrowed}</p>}
    </Tile>
  );
}

// ----------------------------------------------------------------------------------------------------- tyres

/** The energy line; (health lane) low tank fuel is amber, its words first ("Fuel low: ≈ 2 laps (tank level)"). */
function Energy({ v }: { v: TyresView }) {
  if (!v.energyWarn) return <span>{v.energy}</span>;
  return (
    <span>
      <span data-tone="warn">{v.energyWarn}</span>
      {v.energy.slice(v.energyWarn.length)}
    </span>
  );
}

/** The foot: energy, then (health lane) brakes and engine, then the last lap's lock-ups and wheelspin, one per line. */
function TyresFoot({ v }: { v: TyresView }) {
  if (!v.temps && !v.slip) return <Energy v={v} />;
  return (
    <span className="pww-tyres__foot">
      <Energy v={v} />
      {v.temps && <span>{v.temps}</span>}
      {v.slip && <span>{v.slip}</span>}
    </span>
  );
}

export const TyresTile = memo(function TyresTile({ v }: { v: TyresView }) {
  return (
    <Tile
      span={3}
      title="Tyres & energy"
      aside={
        v.chip ? (
          // health lane: "Cold tyres" is amber with its words (colour is never the only signal)
          <Chip size="sm" variant="soft" color={v.chipTone === "warn" ? "warning" : undefined}>
            <Chip.Label>{v.chip}</Chip.Label>
          </Chip>
        ) : undefined
      }
      foot={<TyresFoot v={v} />}
      footWrap
    >
      {v.empty ? (
        <p className="pww-tyres__none">{v.empty}</p>
      ) : (
        <div className="pww-tyres">
          {v.wheels.map((w) => (
            <div key={w.wheel} className="pww-tyre" aria-label={w.aria} role="group">
              <div className="pww-tyre__k" aria-hidden="true">
                <span className="pww-tyre__w">{w.wheel}</span>
                {w.word && <span style={{ color: w.colour }}>{w.word}</span>}
              </div>
              <b className="pww-tyre__t" style={{ color: w.colour }} aria-hidden="true">
                <Val text={w.temp} />
              </b>
              {w.sub !== null && (
                <span className="pww-tyre__s" aria-hidden="true">
                  {w.sub}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {!v.empty && v.basis && <p className="pww-tyres__caption">{v.basis}</p>}
      {!v.empty && v.caption && <p className="pww-tyres__caption">{v.caption}</p>}
    </Tile>
  );
}, sameProps);

// ---------------------------------------------------------------------------------------------------- inputs

export function InputsTile({ history, dim }: { history: readonly HistoryPoint[]; dim: boolean }) {
  const [ref, size, measured] = useElementSize<HTMLDivElement>({ width: 0, height: 200 });
  const h = measured ? Math.max(120, Math.floor(size.height)) : 200;
  return (
    <Tile span={4} title="Inputs · last 12 s">
      <div ref={ref} className="pww-body">
        <LiveTrace history={history} hz={10} height={h} dim={dim} />
      </div>
    </Tile>
  );
}

// ------------------------------------------------------------------------------------------------------ laps

function LapNo({ r }: { r: LapRowView }) {
  return (
    <div>
      <span className="pww-lapno">
        <span className="pww-lapno__n">{r.lap}</span>
        {r.ref && (
          <Chip size="sm" className="pww-mini" aria-label="Reference lap">
            <Chip.Label>R</Chip.Label>
          </Chip>
        )}
        {r.pit && (
          <Chip size="sm" className="pww-mini">
            <Chip.Label>PIT</Chip.Label>
          </Chip>
        )}
      </span>
      {r.reason && (
        <span className="pww-lapno__why" title={r.reason}>
          {r.reason}
        </span>
      )}
    </div>
  );
}

function LapTime({ r }: { r: LapRowView }) {
  return (
    <span className="pww-time">
      <TimingValue ms={r.time.ms} kind="lap" status={r.time.status} context="table" />
      <TimingTag status={r.time.status} />
    </span>
  );
}

function DeltaRef({ r }: { r: LapRowView }) {
  if (r.ref) return <span className="pww-dref" aria-label="Reference lap">R</span>;
  return (
    <span className="pww-dref">
      <Val text={r.delta ?? "-"} label="Difference to the reference" />
    </span>
  );
}

const ALL_COLUMNS: DataGridColumn<LapRowView>[] = [
  { id: "lap", header: "Lap", isRowHeader: true, cell: (r) => <LapNo r={r} /> },
  { id: "time", header: "Time", cell: (r) => <LapTime r={r} /> },
  ...([0, 1, 2] as const).map(
    (i): DataGridColumn<LapRowView> => ({
      id: `s${i + 1}`,
      header: `S${i + 1}`,
      cell: (r) => <TimingValue ms={r.sectors[i].ms} kind="sector" status={r.sectors[i].status} context="table" />,
    }),
  ),
  { id: "dref", header: "Δ ref", align: "end", cell: (r) => <DeltaRef r={r} /> },
];
/** Without S1-S3 when the game sends no sector times (game selection). */
const NO_SECTOR_COLUMNS = ALL_COLUMNS.filter((c) => !/^s\d$/.test(c.id));

/** Below 600 px the table becomes two-line rows (spec 5.4: DataGrid -> ListView), read only. */
function LapRowsNarrow({ rows, sectors }: { rows: LapRowView[]; sectors: boolean }) {
  return (
    <ListView aria-label="Laps, newest first" items={rows} variant="secondary" className="pww-readonly">
      {(r) => (
        <ListView.Item id={r.id} textValue={`Lap ${r.lap}`}>
          <div className="pww-laprow">
            <div className="pww-laprow__a">
              <LapNo r={r} />
              <LapTime r={r} />
              <DeltaRef r={r} />
            </div>
            {sectors && (
              <div className="pww-laprow__b">
                {r.sectors.map((c, i) => (
                  <span key={i}>
                    S{i + 1} <TimingValue ms={c.ms} kind="sector" status={c.status} context="table" />
                  </span>
                ))}
              </div>
            )}
          </div>
        </ListView.Item>
      )}
    </ListView>
  );
}

export const LapsTile = memo(function LapsTile({ v }: { v: LapsTileView }) {
  const narrow = useMediaQuery("(max-width: 599px)");
  return (
    <Tile
      span={5}
      title="Laps"
      aside={v.sub}
      className="pww-laps pww-wide"
      foot={
        v.noSectors ? (
          <span className="pww-laps__foot">
            <TimingLegend tier={v.tier} />
            <span className="text-muted">{v.noSectors}</span>
          </span>
        ) : (
          <TimingLegend tier={v.tier} />
        )
      }
    >
      <div className="pww-scroll">
        {v.empty ? (
          <p className="m-0 py-3 text-sm text-muted">{v.empty}</p>
        ) : narrow ? (
          <LapRowsNarrow rows={v.rows} sectors={v.sectors} />
        ) : (
          <DataGrid
            aria-label="Laps, newest first"
            data={v.rows}
            columns={v.sectors ? ALL_COLUMNS : NO_SECTOR_COLUMNS}
            getRowId={(r) => r.id}
            variant="secondary"
            rowHeight={44}
          />
        )}
      </div>
    </Tile>
  );
}, sameProps);

// -------------------------------------------------------------------------------------------------- coaching

export const CoachingTile = memo(function CoachingTile({ v }: { v: CoachingTileView }) {
  return (
    <Tile span={3} title={v.title} className="pww-coaching pww-wide">
      <div className="pww-scroll">
        {v.empty ? (
          <p className="m-0 py-3 text-sm text-muted">{v.empty}</p>
        ) : (
          <ListView
            aria-label="Coaching points of the last lap"
            items={v.items}
            variant="secondary"
            className="pww-points pww-readonly"
          >
            {(it) => (
              <ListView.Item id={it.id} textValue={`${it.chip}: ${it.text}`}>
                <div className="pww-point">
                  <div className="pww-point__head">
                    <Chip size="sm" variant="soft" color={it.good ? "success" : "warning"}>
                      <Chip.Label>{it.chip}</Chip.Label>
                    </Chip>
                    {it.impact && (
                      <span className="pww-impact" data-tone={it.impactTone ?? undefined}>
                        {it.impact}
                      </span>
                    )}
                  </div>
                  <p className="pww-point__text">{it.text}</p>
                </div>
              </ListView.Item>
            )}
          </ListView>
        )}
      </div>
    </Tile>
  );
}, sameProps);
