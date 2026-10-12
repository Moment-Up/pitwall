// Setup › Controls (controls design 4): which button does what, for any wheel and any game.
//   #/setup/controls[?driver=&game=&platform=&wheel=&preset=]   Layout (default): the wheel diagram and the list
//   #/setup/controls/map[/<n>]                                  Map it: one glance step at a time, from the seat
//   #/setup/controls/test                                       Test (F1 25 only) and Identify
//   #/setup/controls/wheel[/<wheel id>]                         My wheel: describe any wheel, rim, hub or button box
// Data: GET /api/controls/catalog (10 min), /state?driver_id=, /templates/{id} (an unsaved wheel), /recommendation;
// writes POST/PUT /layouts, POST/PUT /wheels, PUT /drivers/{id}. Header: "Controls for James · F1 25 · PS5 · GT DD Pro
// wheel · Advanced [Change]". The banner says it plainly: research only; only F1 25 buttons can be checked here.

import { Alert, Button, Card, Skeleton } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import { useMemo, useState, type Key, type ReactNode } from "react";
import { ScrollRow } from "../../components/ScrollRow";
import { useActiveDriver, useDrivers } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import { useSelectedEntry } from "../../hooks/useGame";
import { cache } from "../../lib/cache";
import type { Driver } from "../../lib/drivers";
import {
  CAPS,
  CATALOG_MAX_AGE_MS,
  CONTROLS_KEYS,
  controlsApi,
  controlsErrorText,
  isConflict,
  type Assignment,
  type ControlsCatalog,
  type RecommendationQuery,
} from "../../lib/endpoints/controls";
import { parseControlsParam, router } from "../../lib/router";
import {
  controlsPath,
  fitToWheel,
  gameById,
  isSavedWheel,
  parseControlsQuery,
  plainAssignments,
  resolveChoice,
  type ControlsQuery,
  type ControlsView as ViewId,
} from "../../lib/setup/controls";
import type { PageProps } from "../../routes";
import { ChoiceSheet } from "./controls/ChoiceSheet";
import { LayoutView } from "./controls/LayoutView";
import { MapView } from "./controls/MapView";
import { buildView, type ControlsActions } from "./controls/model";
import { ResearchBanner } from "./controls/parts";
import { TestView } from "./controls/TestView";
import { WheelEditor } from "./controls/WheelEditor";

const EMPTY_DRIVERS: Driver[] = [];

const VIEWS: { id: ViewId; label: string }[] = [
  { id: "layout", label: "Layout" },
  { id: "map", label: "Map it" },
  { id: "test", label: "Test" },
  { id: "wheel", label: "My wheel" },
];

function Loading({ label }: { label: string }) {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label={label} data-testid="controls-loading">
      <Skeleton className="h-20 rounded-3xl" />
      <div className="grid gap-4 lg:grid-cols-2">
        <Skeleton className="h-[360px] rounded-3xl" />
        <Skeleton className="h-[360px] rounded-3xl" />
      </div>
    </div>
  );
}

function Failed({ title, error, onRetry }: { title: string; error: Error; onRetry: () => void }) {
  return (
    <Alert status="danger">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>{title}</Alert.Title>
        <Alert.Description>{controlsErrorText(error)}</Alert.Description>
      </Alert.Content>
      <Button variant="secondary" className="min-h-11" onPress={onRetry}>
        Try again
      </Button>
    </Alert>
  );
}

/** No wheel yet (design 2.5 step 4): pick a template or build one. */
export function NoWheelCard({ catalog, onPick, onChange, onBuild }: { catalog: ControlsCatalog; onPick: (template: string) => void; onChange: () => void; onBuild: () => void }) {
  const quick = ["fanatec_gt_dd_pro_wheel", "fanatec_csl_elite_mclaren_gt3_v2", "logitech_g923_ps", "logitech_g923_xbox", "thrustmaster_t248"]
    .map((id) => catalog.templates.find((t) => t.id === id))
    .filter((t) => t !== undefined);
  return (
    <Card className="gap-4 p-5" data-testid="no-wheel">
      <Card.Header className="gap-1">
        <Card.Title className="text-lg font-semibold">Pick your wheel</Card.Title>
        <Card.Description className="text-[15px] text-muted">
          Pitwall suggests which button does what once it knows your wheel. Any wheel, rim or button box works: pick one from the research, or describe
          your own.
        </Card.Description>
      </Card.Header>
      <Card.Content className="grid gap-3">
        <div className="grid gap-2 sm:grid-cols-2">
          {quick.map((t) => (
            <Button key={t.id} variant="secondary" className="h-auto min-h-14 justify-start px-4 py-2 text-left" onPress={() => onPick(t.id)}>
              <span className="grid">
                <span className="font-semibold">{t.brand}</span>
                <span className="text-sm font-normal text-muted">{t.name}</span>
              </span>
            </Button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button className="min-h-11" variant="secondary" onPress={onChange}>
            All {catalog.templates.length - 1} wheels…
          </Button>
          <Button className="min-h-11" variant="ghost" onPress={onBuild}>
            Build my own
          </Button>
        </div>
      </Card.Content>
    </Card>
  );
}

export function ControlsPage({ route }: PageProps) {
  const { view, n, wheelId: wheelParam } = parseControlsParam(route.param);
  const q = useMemo(() => parseControlsQuery(route.query), [route.query]);
  const drivers = useDrivers((s) => s.drivers) ?? EMPTY_DRIVERS;
  const driversLoaded = useDrivers((s) => s.loaded || s.error !== null);
  const seated = useActiveDriver();
  const driverId = q.driver ?? (driversLoaded ? (seated?.id ?? null) : undefined);
  const driver = driverId != null ? (drivers.find((d) => d.id === driverId) ?? null) : null;
  const selected = useSelectedEntry();
  const [sheet, setSheet] = useState(false);
  const [draft, setDraft] = useState<{ scope: string; assignments: Assignment[] } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const catalog = useApi(CONTROLS_KEYS.catalog, controlsApi.catalog, { maxAgeMs: CATALOG_MAX_AGE_MS });
  const state = useApi(driverId === undefined ? null : CONTROLS_KEYS.state(driverId), () => controlsApi.state(driverId ?? null));
  const base = useMemo(
    () =>
      resolveChoice({
        query: q,
        state: state.data,
        catalog: catalog.data,
        selected: selected ? { game_key: selected.game_key, platform: selected.platform, label: selected.text_name } : null,
        driverId: driverId ?? null,
        skill: driver?.preferences.skill_level ?? null,
      }),
    [q, state.data, catalog.data, selected, driverId, driver],
  );
  const savedWheel = base.wheel?.kind === "saved" ? (state.data?.wheels.find((w) => w.id === base.wheel!.id) ?? null) : null;
  const tplId = base.wheel?.kind === "template" ? base.wheel.id : null;
  const tpl = useApi(tplId ? CONTROLS_KEYS.template(tplId) : null, () => controlsApi.template(tplId!), { maxAgeMs: CATALOG_MAX_AGE_MS });
  const wheel = savedWheel ?? (tplId ? (tpl.data ?? null) : null);
  // A platform the wheel doesn't have (MOZA on PS5) becomes one it has, unless the URL asked for it.
  const choice = fitToWheel(base, gameById(catalog.data, base.game), wheel, q.platform !== null);
  const recQ: RecommendationQuery | null =
    wheel && state.data
      ? {
          game: choice.game,
          platform: choice.platform,
          wheel_id: isSavedWheel(wheel) ? wheel.id : null,
          template: isSavedWheel(wheel) ? null : (wheel.template ?? tplId),
          driver_id: choice.driverId,
          preset: choice.preset,
          game_name: choice.gameName,
          functions: choice.otherFns,
        }
      : null;
  const rec = useApi(recQ ? CONTROLS_KEYS.recommendation(recQ) : null, () => controlsApi.recommendation(recQ!));

  const keep: ControlsQuery = q;
  const apply = (patch: Partial<ControlsQuery>) => router.replace(controlsPath(view === "wheel" ? "layout" : view, { ...keep, ...patch }, view === "map" ? null : undefined));
  const go = (v: ViewId) => router.navigate(controlsPath(v, keep));
  const build = () => {
    setSheet(false);
    router.navigate(controlsPath("wheel", keep, "new"));
  };

  const scope = `${choice.game}:${choice.platform}:${wheel?.id || wheel?.template || "none"}:${choice.preset}:${choice.driverId ?? "none"}`;
  const local = draft && draft.scope === scope ? draft.assignments : null;
  const v =
    catalog.data && state.data && wheel && (rec.data || !rec.loading || rec.error)
      ? buildView({
          catalog: catalog.data,
          state: state.data,
          choice,
          query: keep,
          driverName: driver?.name ?? null,
          wheel,
          rec: rec.data,
          draft: local,
          names: new Map(drivers.map((d) => [d.id, d.name])),
        })
      : null;

  async function save(owner: "household" | number): Promise<boolean> {
    if (!v) return false;
    setSaving(true);
    setSaveError(null);
    try {
      let wheelId = v.wheel.id;
      if (!isSavedWheel(v.wheel)) {
        const w = await controlsApi.createWheel({
          name: v.wheel.name.slice(0, CAPS.name),
          template: v.wheel.template,
          shape: v.wheel.shape,
          platforms: v.wheel.platforms,
          parts: v.wheel.parts,
          controls: v.wheel.controls,
        });
        wheelId = w.id;
      }
      if (v.layout && v.layout.owner === owner) {
        await controlsApi.putLayout({ ...v.layout, preset: choice.preset, assignments: v.assignments });
      } else {
        await controlsApi.createLayout({
          game: choice.game,
          game_name: choice.gameName,
          platform: choice.platform,
          wheel_id: wheelId,
          owner,
          preset: choice.preset,
          other_functions: choice.game === "other" ? choice.otherFns : null,
          assignments: v.assignments,
        });
      }
      const dc = choice.driverId != null ? v.state.drivers[String(choice.driverId)] : undefined;
      if (choice.driverId != null && (dc?.wheel_id !== wheelId || (choice.presetFromUrl && dc?.preset !== choice.preset))) {
        await controlsApi.putDriver(choice.driverId, { wheel_id: wheelId, ...(choice.presetFromUrl ? { preset: choice.preset } : {}) });
      }
      for (const p of CONTROLS_KEYS.data) cache.invalidate(p);
      setDraft(null);
      if (wheelId !== v.wheel.id) router.replace(controlsPath(view, { ...keep, wheel: wheelId }));
      return true;
    } catch (e) {
      setSaveError(controlsErrorText(e));
      if (isConflict(e)) cache.invalidate("controls:state");
      return false;
    } finally {
      setSaving(false);
    }
  }

  const actions: ControlsActions = {
    setAssignments: (a) => setDraft({ scope, assignments: a }),
    useRecommended: () => setDraft({ scope, assignments: plainAssignments(rec.data) }),
    save,
    saving,
    saveError,
    change: () => setSheet(true),
  };

  const header = (
    <Card className="gap-2 px-4 py-3 md:px-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="m-0 min-w-0 text-[15px] font-semibold" data-testid="controls-header">
          {v ? v.header : wheel === null && catalog.data && state.data ? `Controls${driver ? ` for ${driver.name}` : ""} · No wheel yet` : "Controls"}
        </p>
        <Button variant="secondary" className="min-h-11" onPress={() => setSheet(true)} isDisabled={!catalog.data || !state.data}>
          Change
        </Button>
      </div>
      {wheel && !isSavedWheel(wheel) ? (
        <p className="m-0 text-sm text-muted">This wheel comes from the research and is saved with your layout. Change it in My wheel.</p>
      ) : null}
    </Card>
  );
  const segment = (
    <ScrollRow className="-mx-4 px-4 pb-1 md:mx-0 md:px-0">
      <Segment aria-label="Controls views" size="lg" selectedKey={view} onSelectionChange={(k: Key) => go(String(k) as ViewId)} className="w-max">
        {VIEWS.map((x) => (
          <Segment.Item key={x.id} id={x.id} className="h-11 px-4">
            {x.label}
          </Segment.Item>
        ))}
      </Segment>
    </ScrollRow>
  );
  const frame = (body: ReactNode) => (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0" data-testid="controls-page">
      {header}
      {segment}
      <ResearchBanner />
      {body}
      {catalog.data && state.data ? (
        <ChoiceSheet
          open={sheet}
          onClose={() => setSheet(false)}
          catalog={catalog.data}
          state={state.data}
          drivers={drivers}
          seatedId={seated?.id ?? null}
          choice={choice}
          wheel={wheel}
          onApply={apply}
          onBuild={build}
        />
      ) : null}
    </div>
  );

  if (!catalog.data || !state.data) {
    const err = catalog.error ?? state.error;
    return frame(
      err ? (
        <Failed
          title="Controls did not load"
          error={err}
          onRetry={() => {
            void catalog.refresh();
            void state.refresh();
          }}
        />
      ) : (
        <Loading label="Loading controls" />
      ),
    );
  }

  if (view === "wheel") {
    // "/wheel/new": a blank wheel ("Build my own"); "/wheel/<id>": that saved wheel; "/wheel": the page's wheel.
    const initial = wheelParam === "new" ? null : wheelParam ? (state.data.wheels.find((w) => w.id === wheelParam) ?? null) : wheel;
    return frame(<WheelEditor key={initial?.id || initial?.template || "blank"} catalog={catalog.data} state={state.data} initial={initial} query={keep} />);
  }

  if (!wheel) {
    if (tplId && tpl.error) return frame(<Failed title="That wheel's research did not load" error={tpl.error} onRetry={() => void tpl.refresh()} />);
    if (tplId && !tpl.data) return frame(<Loading label="Loading your wheel" />);
    return frame(<NoWheelCard catalog={catalog.data} onPick={(t) => apply({ wheel: t })} onChange={() => setSheet(true)} onBuild={build} />);
  }

  if (!v) {
    return frame(rec.error ? <Failed title="The recommendation did not load" error={rec.error} onRetry={() => void rec.refresh()} /> : <Loading label="Loading the recommendation" />);
  }

  const recProblem = rec.error && !v.layout ? <Failed title="The recommendation did not load" error={rec.error} onRetry={() => void rec.refresh()} /> : null;
  if (view === "map") return frame(recProblem ?? <MapView v={v} n={n} />);
  if (view === "test") return frame(<TestView v={v} />);
  return frame(
    <>
      {rec.error && v.layout ? (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>The recommendation did not load, so the reasons are missing: {controlsErrorText(rec.error)}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
      {recProblem ?? <LayoutView v={v} a={actions} />}
    </>,
  );
}
