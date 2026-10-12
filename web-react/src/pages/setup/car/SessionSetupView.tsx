// One session's setup vs the recommendation (spec 7.3, `#/setup/car/session/<id>?format=&session=&conditions=&style=`).
// Data: GET /api/carsetup/sessions/{sid}. What the game reported (track, car format, session, weather) is shown with
// its reason; a field Pitwall cannot tell (`needs`, e.g. the car format of a generic car) is asked with a Segment, and
// the answer is kept in the route query. F2 support: the car format is never asked for a car that is not an F1 car,
// the choices and alternatives are the session's car family's only, and an override of another family (refused with
// 422) offers the car the game reported. A field Pitwall cannot tell is asked with a Select (spec 7.3). Then the comparison as a Pro DataGrid (changed rows first), the backend's
// suggested change to test, and this session's experiments. Behaviour reference: web/src/views/CarSetupView.svelte.

import { Alert, Button, Card, Chip, Label, ListBox, Select, Skeleton } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import { ArrowLeft } from "@gravity-ui/icons";
import { useMemo, useRef, useState, type Key } from "react";
import { EvidenceChips } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import {
  CARSETUP_KEYS,
  carsetupApi,
  CONDITIONS,
  errorText,
  SESSION_KINDS,
  STYLES,
  type CarFormat,
  type CarSetupCatalog,
  type Combination,
  type NeedField,
  type SessionSetupQuery,
  type SessionSetupResponse,
  type SetupStyle,
} from "../../../lib/endpoints/carsetup";
import { pathOf, router, withQuery } from "../../../lib/router";
import {
  alreadyTesting,
  changedFirst,
  classCarText,
  CONDITIONS_LABEL,
  defaultStyle,
  familyAlternatives,
  formatChoices,
  formatLabel,
  formatShortLabel,
  gameSessionText,
  isChanged,
  listText,
  NEED_LABEL,
  paramValue,
  parseSetupQuery,
  refusedOverride,
  SESSION_LABEL,
  sessionLabel,
  setupFamily,
  setupHeading,
  setupQueryValues,
  sortAlternatives,
  sortExperiments,
  STYLE_LABEL,
  type SetupRequestQuery,
} from "../../../lib/setup/carsetup";
import { carText } from "../../../lib/carclass";
import type { Route } from "../../../lib/route-parse";
import { ExperimentCard } from "./ExperimentCard";
import { DiffGrid } from "./DiffGrid";
import { HandlingBalanceCard } from "./HandlingBalanceCard"; // feat/technique
import { NewExperimentModal } from "./NewExperimentModal";
import { Caveat } from "./RecommendationSummary";
import { Alternatives } from "./UnavailableCard";

const QUERY_FIELD: Record<NeedField, "format" | "session" | "conditions"> = { car_format: "format", session: "session", conditions: "conditions" };

function ContextItem({ label, value, chip, reasons }: { label: string; value: string; chip?: { text: string; tone: "default" | "warning" | "success" } | null; reasons: (string | null | undefined)[] }) {
  return (
    <div className="grid content-start gap-1">
      <span className="text-sm text-muted">{label}</span>
      <span className="flex flex-wrap items-center gap-2 text-[17px] font-semibold">
        {value}
        {chip ? (
          <Chip size="sm" variant="soft" color={chip.tone}>
            <Chip.Label>{chip.text}</Chip.Label>
          </Chip>
        ) : null}
      </span>
      {reasons.filter(Boolean).map((r) => (
        <span key={r} className="text-sm text-muted">
          {r}
        </span>
      ))}
    </div>
  );
}

export function SessionSetupView({ sid, route, catalog }: { sid: string; route: Route; catalog: CarSetupCatalog }) {
  const q = parseSetupQuery(route.query);
  const sq: SessionSetupQuery = { car_format: q.format, session: q.session, conditions: q.conditions, style: q.style };
  const key = CARSETUP_KEYS.session(sid, sq);
  const res = useApi(key, () => carsetupApi.session(sid, sq));
  const sessions = useApi(CARSETUP_KEYS.sessions, carsetupApi.sessions);
  const exps = useApi(CARSETUP_KEYS.experiments({ session_id: sid }), () => carsetupApi.experiments({ session_id: sid }));
  const [mode, setMode] = useState<"diff" | "all">("diff");
  const [modal, setModal] = useState<{ open: boolean; initial: { key: string; to: number; hypothesis?: string } | null; n: number }>({
    open: false,
    initial: null,
    n: 0,
  });
  const [proposing, setProposing] = useState(false);
  const [proposeError, setProposeError] = useState<string | null>(null);
  const params = useMemo(() => new Map(catalog.parameters.map((p) => [p.key, p])), [catalog]);

  // Keep the last answer for this session on screen (dimmed) while a changed choice loads.
  const last = useRef<SessionSetupResponse | null>(null);
  if (res.data && res.data.session.id === sid) last.current = res.data;
  const s = res.data ?? (last.current?.session.id === sid ? last.current : null);
  const loading = res.data === undefined && !res.error;

  const go = (next: Partial<SetupRequestQuery>) =>
    router.replace(withQuery(pathOf("setup", "car", "session", sid), setupQueryValues({ ...q, ...next, track: null, driver: null })));

  if (!s) {
    if (res.error && refusedOverride(res.error, q)) {
      // F2 support: a car format of another family than the session's class (an F1 format for an F2 session)
      return (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>That car format does not fit this session's car</Alert.Title>
            <Alert.Description>{errorText(res.error)}</Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={() => go({ format: null })}>
            Use the car the game reported
          </Button>
        </Alert>
      );
    }
    if (res.error) {
      return (
        <Alert status="danger">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Cannot load this session's setup</Alert.Title>
            <Alert.Description>{errorText(res.error)}</Alert.Description>
          </Alert.Content>
          <Button variant="secondary" className="min-h-11" onPress={() => router.navigate("/setup/car")}>
            Back to car setup
          </Button>
        </Alert>
      );
    }
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-28 rounded-3xl" />
        <Skeleton className="h-96 rounded-3xl" />
      </div>
    );
  }

  const ctx = s.context;
  const chosen = s.chosen;
  const rr = s.recommendation;
  const d = s.diff;
  const allSessions = sessions.data ?? [];
  const choosable = (["car_format", "session", "conditions"] as NeedField[]).filter((f) => s.needs.includes(f) || q[QUERY_FIELD[f]] !== null);
  const unknown = choosable.filter((f) => ctx[f] === null);
  const driverSkill = s.session.driver?.skill_level ?? null;
  const autoStyle = defaultStyle(driverSkill);
  const rows = d ? changedFirst(mode === "diff" ? d.rows.filter(isChanged) : d.rows) : [];
  const expList = sortExperiments(exps.data ?? []);
  const x = d?.experiment ?? null;
  const testing = x ? alreadyTesting(expList, x, sid) : false;
  const fmtLabel = rr ? formatLabel(catalog, rr.car_format) : "";
  const family = setupFamily(s);
  // F2 support: only the session's car family's formats (an F2 car is never offered an F1 format, nor the reverse)
  const formats = formatChoices(catalog, s);
  const optionsFor = (f: NeedField): { id: string; label: string }[] =>
    f === "car_format"
      ? formats.map((x) => ({ id: x.id, label: formatShortLabel(x.id, catalog) }))
      : f === "session"
        ? SESSION_KINDS.map((k) => ({ id: k, label: SESSION_LABEL[k] }))
        : CONDITIONS.map((c) => ({ id: c, label: CONDITIONS_LABEL[c] }));

  async function testChange() {
    if (!x) return;
    setProposing(true);
    setProposeError(null);
    try {
      await carsetupApi.propose({ before_session_id: sid, parameter: x.key, to_value: x.to_value, car_format: chosen.car_format });
      void exps.refresh();
    } catch (e) {
      setProposeError(errorText(e));
    } finally {
      setProposing(false);
    }
  }

  function showAbove() {
    if (!rr || ctx.track_id === null) return;
    router.navigate(
      withQuery(
        "/setup/car",
        setupQueryValues({
          format: rr.car_format,
          track: ctx.track_id,
          session: rr.requested_session,
          conditions: rr.conditions,
          style: q.style,
          driver: s?.session.driver?.id ?? null,
        }),
      ),
    );
  }

  return (
    <div className={`grid gap-4 ${loading ? "opacity-70" : ""}`} aria-busy={loading}>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" className="min-h-11" onPress={() => router.navigate("/setup/car")}>
          <ArrowLeft aria-hidden="true" />
          Car setup
        </Button>
      </div>

      <Card className="gap-4 p-5">
        <Card.Header className="flex-row flex-wrap items-start justify-between gap-3">
          <div className="grid gap-1">
            <Card.Title className="text-xl font-semibold">Your setup vs recommended</Card.Title>
            <Card.Description className="text-[15px] text-muted">
              {sessionLabel({ ...s.session, started_unix: allSessions.find((x) => x.id === sid)?.started_unix ?? 0, driver_name: s.session.driver?.name ?? null })}
            </Card.Description>
          </div>
          <EvidenceChips synthetic={s.session.synthetic} size="md" />
        </Card.Header>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <ContextItem label="Track" value={s.session.track_name ?? ctx.track_name ?? "Unknown track"} reasons={[ctx.reasons.track_id, ctx.reasons.game]} />
          <ContextItem
            label="Car"
            value={chosen.car_format ? formatShortLabel(chosen.car_format, catalog) : (classCarText(ctx.car_class ?? s.session.car_class) ?? "Unknown")}
            chip={
              q.format
                ? { text: "your choice", tone: "default" }
                : ctx.car_format
                  ? { text: ctx.car_format_certain ? "certain" : "not certain", tone: ctx.car_format_certain ? "success" : "warning" }
                  : null
            }
            reasons={[ctx.reasons.car_format, carText(s.session) ? `Game car: ${carText(s.session)}` : null]}
          />
          <ContextItem
            label="Session"
            value={chosen.session ? SESSION_LABEL[chosen.session] : "Unknown"}
            chip={q.session ? { text: "your choice", tone: "default" } : null}
            reasons={[`Game: ${gameSessionText(s.session)}`, ctx.reasons.session]}
          />
          <ContextItem
            label="Conditions"
            value={chosen.conditions ? CONDITIONS_LABEL[chosen.conditions] : "Unknown"}
            chip={q.conditions ? { text: "your choice", tone: "default" } : null}
            reasons={[s.session.weather.condition ? `Weather: ${s.session.weather.condition.replace(/_/g, " ")}` : null, ctx.reasons.conditions]}
          />
          <ContextItem label="Driver" value={s.session.driver?.name ?? "Unknown"} reasons={[driverSkill ? driverSkill : null]} />
        </div>
        {ctx.notes.length ? (
          <ul className="m-0 grid list-disc gap-1 pl-5 text-sm text-muted">
            {ctx.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        ) : null}

        {choosable.length ? (
          <div className="grid gap-3 rounded-2xl border border-separator p-4">
            <p className="m-0 text-[15px]">
              {unknown.length
                ? `Pitwall cannot tell the ${listText(unknown.map((f) => NEED_LABEL[f].toLowerCase()))} from the game for this session, so choose:`
                : "You changed what the game reported for this session:"}
            </p>
            {choosable.map((f) => (
              <div key={f} className="flex flex-wrap items-end gap-3">
                <Select
                  className="w-56"
                  placeholder="Choose"
                  selectedKey={chosen[f] ?? null}
                  onSelectionChange={(k) => {
                    if (k !== null) go({ [QUERY_FIELD[f]]: String(k) } as Partial<SetupRequestQuery>);
                  }}
                >
                  <Label>{NEED_LABEL[f]}</Label>
                  <Select.Trigger className="min-h-12">
                    <Select.Value />
                    <Select.Indicator />
                  </Select.Trigger>
                  <Select.Popover>
                    <ListBox>
                      {optionsFor(f).map((o) => (
                        <ListBox.Item key={o.id} id={o.id} textValue={o.label} className="min-h-12">
                          {o.label}
                          <ListBox.ItemIndicator />
                        </ListBox.Item>
                      ))}
                    </ListBox>
                  </Select.Popover>
                </Select>
                {q[QUERY_FIELD[f]] !== null && ctx[f] !== null ? (
                  <Button variant="ghost" className="min-h-11" onPress={() => go({ [QUERY_FIELD[f]]: null } as Partial<SetupRequestQuery>)}>
                    Use what the game reported
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
        <Caveat text={s.caveat} />
      </Card>

      {s.unavailable ? (
        <Card className="gap-3 p-5" role="status">
          <Card.Title className="text-base font-semibold">No recommendation yet</Card.Title>
          <p className="m-0 text-[15px]">{s.unavailable.reason}</p>
          {(() => {
            const alts = familyAlternatives(s.unavailable.alternatives, family).filter((a) => a.track_id === ctx.track_id);
            if (!alts.length) return null;
            const sorted = sortAlternatives(alts, { car_format: chosen.car_format, track_id: ctx.track_id, session: chosen.session, conditions: chosen.conditions, style: chosen.style });
            return (
              <>
                <span className="text-sm font-semibold text-muted">Setups that exist for this track</span>
                <Alternatives
                  alts={sorted}
                  catalog={catalog}
                  current={{ car_format: chosen.car_format, track_id: ctx.track_id }}
                  onPick={(a: Combination) => go({ format: a.car_format, session: a.session, conditions: a.conditions, style: a.style })}
                />
              </>
            );
          })()}
        </Card>
      ) : rr ? (
        <Card className="gap-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="grid gap-0.5">
              <span className="text-sm text-muted">Compared with</span>
              <span className="text-base font-semibold">{setupHeading(rr, catalog)}</span>
            </div>
            <Button variant="secondary" className="min-h-11" onPress={showAbove}>
              Show this setup
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <span className="w-28 text-sm text-muted">Style</span>
            <Segment aria-label="Style" size="lg" selectedKey={q.style ?? rr.requested_style} onSelectionChange={(k: Key) => go({ style: String(k) as SetupStyle })}>
              {STYLES.map((st) => (
                <Segment.Item key={st} id={st} className="h-11 px-5">
                  {STYLE_LABEL[st]}
                </Segment.Item>
              ))}
            </Segment>
            {q.style ? (
              <Button variant="ghost" className="min-h-11" onPress={() => go({ style: null })}>
                Use {s.session.driver ? `${s.session.driver.name}'s` : "the"} default ({STYLE_LABEL[autoStyle]})
              </Button>
            ) : null}
          </div>
          {rr.notes.map((n) => (
            <p key={n} className="m-0 text-sm text-warning">
              {n}
            </p>
          ))}

          {!s.setup ? (
            <p className="m-0 text-[15px] text-muted">
              Pitwall has not received your car setup for this session. The game sends it while you drive with UDP telemetry on.
            </p>
          ) : d ? (
            <>
              <p className="m-0 text-base">{d.summary}</p>
              {d.out_of_range.length ? (
                <Alert status="danger">
                  <Alert.Indicator />
                  <Alert.Content>
                    <Alert.Title>Some of your values are outside the {fmtLabel} range</Alert.Title>
                    <Alert.Description>
                      {formats.some((f) => f.id !== rr.car_format)
                        ? "This usually means the car format is wrong, so the differences below are not meaningful yet."
                        : "They are outside the range Pitwall has for this car, so the differences below may not be meaningful yet."}
                    </Alert.Description>
                  </Alert.Content>
                  <div className="flex flex-wrap gap-2">
                    {formats
                      .filter((f) => f.id !== rr.car_format)
                      .map((f) => (
                        <Button key={f.id} variant="secondary" className="min-h-11" onPress={() => go({ format: f.id as CarFormat })}>
                          Compare with the {formatShortLabel(f.id, catalog)}
                        </Button>
                      ))}
                  </div>
                </Alert>
              ) : null}
              <Segment aria-label="Rows to show" selectedKey={mode} onSelectionChange={(k: Key) => setMode(String(k) === "all" ? "all" : "diff")} className="w-fit self-start">
                <Segment.Item id="diff" className="h-11 px-4">
                  Differences ({d.differing})
                </Segment.Item>
                <Segment.Item id="all" className="h-11 px-4">
                  All ({d.rows.length})
                </Segment.Item>
              </Segment>
              <div className="overflow-x-auto">
                <DiffGrid rows={rows} decimals={(k) => params.get(k)?.decimals ?? 0} formatLabel={fmtLabel} />
              </div>
              {d.not_compared.length ? (
                <p className="m-0 text-sm text-faint">Not on the setup sheet, so not compared: {d.not_compared.join(", ")}</p>
              ) : null}
              {x ? (
                <div className="grid gap-2 rounded-2xl bg-surface-secondary p-4">
                  <span className="text-sm font-semibold text-muted">Something to test</span>
                  <p className="m-0 text-[15px]">{x.text}</p>
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="pw-num text-2xl">
                      {paramValue(params.get(x.key), x.from_value)} → {paramValue(params.get(x.key), x.to_value)}
                    </span>
                    <Button className="min-h-11" isDisabled={testing || proposing || loading} isPending={proposing} onPress={() => void testChange()}>
                      {testing ? "Already in your experiments" : "Test this change"}
                    </Button>
                  </div>
                  {proposeError ? (
                    <p role="alert" className="m-0 text-sm text-danger">
                      {proposeError}
                    </p>
                  ) : null}
                </div>
              ) : null}
            </>
          ) : null}
        </Card>
      ) : null}

      {/* feat/technique */}
      <HandlingBalanceCard sid={sid} carFormat={chosen.car_format} session={s.session} catalog={catalog} experiments={expList} onTry={(initial) => setModal((m) => ({ open: true, initial, n: m.n + 1 }))} />

      <Card className="gap-3 p-5">
        <Card.Header className="flex-row flex-wrap items-center justify-between gap-3">
          <div>
            <Card.Title className="text-base font-semibold">Experiments from this session</Card.Title>
            <Card.Description className="text-sm text-muted">
              One change at a time: drive a session with the change, link it here, then compare it with this one.
            </Card.Description>
          </div>
          <Button
            variant="secondary"
            className="min-h-11"
            isDisabled={!s.setup}
            onPress={() => setModal((m) => ({ open: true, initial: null, n: m.n + 1 }))}
          >
            Start an experiment
          </Button>
        </Card.Header>
        {exps.error ? (
          <p role="alert" className="m-0 text-sm text-danger">
            {errorText(exps.error)}
          </p>
        ) : null}
        {expList.length ? (
          <div className="grid gap-3">
            {expList.map((e) => (
              <ExperimentCard key={e.id} exp={e} param={params.get(e.parameter)} sessions={allSessions} />
            ))}
          </div>
        ) : exps.data ? (
          <p className="m-0 text-sm text-muted">
            No experiments from this session yet.{x ? " Use Test this change above to start one." : ""}
          </p>
        ) : (
          <Skeleton className="h-16 rounded-2xl" />
        )}
      </Card>

      <NewExperimentModal
        key={modal.n}
        isOpen={modal.open}
        onOpenChange={(open) => setModal((m) => ({ ...m, open }))}
        sessionId={sid}
        carFormat={chosen.car_format}
        parameters={catalog.parameters}
        params={s.setup?.params ?? null}
        initial={modal.initial}
      />
    </div>
  );
}
