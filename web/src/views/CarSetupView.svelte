<script lang="ts">
  // Car setup: per-track F1 25 setup recommendations (2025 cars and 2026 Season Pack cars, never mixed), the
  // driver's own setup vs the recommendation for a session, and single-variable setup experiments.
  // iPad-first: 44px+ tap targets, values large and in the game's menu order with copy buttons, no hover-only
  // affordances. Provenance stays visible: every value shows its confidence, a value pitwall derived is marked with
  // its rule (also in copied text), and the cited setups are listed with author, date and game patch. A setup is a
  // starting point, never a guaranteed fix: the caveat is always on screen next to the setup and the comparison.
  //
  // Every answer is kept with the request it answers, so a slow answer for an earlier pick never shows for the
  // current one, and a "no setup" reason or an error never outlives its combination.
  //
  // Props (as SetupView): driverId (the driver in the seat; picks the default style: beginner -> stable), drivers
  // (the family list for the picker; fetched from /api/drivers when not given) and onDriverChange (optional).
  import { untrack } from "svelte";
  import { copyText } from "../lib/copy";
  import { lapTime, signed } from "../lib/format";
  import { rig, type DriverOption } from "../lib/rig";
  import {
    carsetup,
    CarSetupError,
    CONDITIONS,
    CONDITIONS_LABEL,
    DIRECTION_ARROW,
    SELECTION_LABEL,
    SESSION_KINDS,
    SESSION_LABEL,
    STATUS_LABEL,
    STYLES,
    STYLE_LABEL,
    VERDICT_LABEL,
    comboKey,
    comboLabel,
    conditionsOf,
    defaultStyle,
    errorText,
    f1TrackId,
    formatLabel,
    groupRows,
    paramValue,
    predatesPatch,
    sectionCopyText,
    servedNote,
    sessionKindOf,
    sessionLabel,
    sessionTypeLabel,
    setupCopyText,
    setupHeading,
    sortAlternatives,
    stepsText,
    trackHasSetup,
    valueText,
    when,
    type CarFormat,
    type CarSetupCatalog,
    type Combination,
    type Conditions,
    type DiffRow,
    type Direction,
    type FormatInfo,
    type NeedField,
    type ParameterInfo,
    type RecommendationQuery,
    type RecommendationResponse,
    type SessionKind,
    type SessionOption,
    type SessionSetupQuery,
    type SessionSetupResponse,
    type SetupExperiment,
    type SetupResult,
    type SetupRow,
    type SetupStyle,
    type SuggestedExperiment,
    type Unavailable,
  } from "../lib/carsetup";

  interface Props {
    driverId?: number | null;
    drivers?: DriverOption[];
    onDriverChange?: (id: number) => void;
  }
  let { driverId = null, drivers: driversProp, onDriverChange }: Props = $props();

  const FORMAT_KEY = "pitwall-carsetup-format";
  const ALT_PREVIEW = 8;

  function storedFormat(options: CarFormat[]): CarFormat | null {
    try {
      const v = localStorage.getItem(FORMAT_KEY);
      return options.find((o) => o === v) ?? null;
    } catch {
      return null;
    }
  }
  function rememberFormat(v: CarFormat) {
    try {
      localStorage.setItem(FORMAT_KEY, v);
    } catch {
      /* storage unavailable */
    }
  }

  // ------------------------------------------------------------------ state
  let catalog = $state<CarSetupCatalog | null>(null);
  let catalogError = $state<string | null>(null);
  let catalogLoading = $state(false);
  let sessions = $state<SessionOption[]>([]);
  let sessionsLoaded = $state(false);
  let sessionsLoading = $state(false);
  let sessionsError = $state<string | null>(null);
  let fetchedDrivers = $state<DriverOption[]>([]);
  let fetchedActive = $state<number | null>(null);

  // pickers (seeded once from the catalogue and the most recent real F1 session)
  let pickedDriver = $state<number | null | undefined>(undefined);
  let fmt = $state<CarFormat | null>(null);
  let trackId = $state<number | null>(null);
  let kind = $state<SessionKind>("race");
  let cond = $state<Conditions>("dry");
  // an explicit style belongs to the driver it was picked for; null = the driver's skill picks it
  let styleState = $state<{ driver: number | null; style: SetupStyle | null }>({ driver: null, style: null });
  let seeded = false;

  // recommendation: the last setup received, and the request key the latest answer (setup, reason, error) is for
  let rec = $state<RecommendationResponse | null>(null);
  let recFor = $state<string | null>(null);
  let recUnavailable = $state<Unavailable | null>(null);
  let recError = $state<string | null>(null);
  let recRetry = $state(0);
  let showAllAlts = $state(false);
  let expanded = $state<string | null>(null);
  let copied = $state<{ key: string; ok: boolean } | null>(null);
  let copyTick = 0;

  // your setup vs recommended
  type Overrides = { sid: string | null } & SessionSetupQuery;
  let pickedSession = $state<string | null>(null);
  let overrides = $state<Overrides>({ sid: null });
  let sess = $state<SessionSetupResponse | null>(null);
  let sessFor = $state<string | null>(null);
  let sessError = $state<string | null>(null);
  let sessReload = $state(0);
  let diffMode = $state<"diff" | "all">("diff");
  let proposing = $state(false);
  let proposeError = $state<{ sid: string; text: string } | null>(null);

  // experiments (the list is kept with the session it is for)
  let experiments = $state<SetupExperiment[]>([]);
  let expFor = $state<string | null>(null);
  let expLoading = $state(false);
  let expError = $state<string | null>(null);
  let expReload = $state(0);
  let busy = $state<Record<number, "start" | "conclude" | "abandon">>({});
  let expErrors = $state<Record<number, string>>({});
  let afterPick = $state<Record<number, string>>({});
  let abandoning = $state<number | null>(null);
  let abandonReason = $state("");

  // ------------------------------------------------------------------ derived
  const drivers = $derived(driversProp ?? fetchedDrivers);
  // explicit pick > the parent's driver > (when the list was fetched here) the driver in the seat
  const currentDriver = $derived(pickedDriver !== undefined ? pickedDriver : (driverId ?? fetchedActive));
  const driver = $derived(drivers.find((d) => d.id === currentDriver) ?? null);
  const styleChoice = $derived(styleState.driver === currentDriver ? styleState.style : null);
  const autoStyle = $derived(defaultStyle(driver?.skill_level));
  const format = $derived(catalog?.formats.find((f) => f.id === fmt) ?? null);
  const av = $derived(catalog?.available ?? []);
  const params = $derived(new Map((catalog?.parameters ?? []).map((p) => [p.key, p])));
  const sourcesById = $derived(new Map((catalog?.sources ?? []).map((s) => [s.id, s])));
  const rulesById = $derived(new Map((catalog?.rules ?? []).map((r) => [r.id, r])));

  const recKey = $derived(
    fmt !== null && trackId !== null ? [fmt, trackId, kind, cond, styleChoice ?? "auto", currentDriver ?? "none"].join("|") : null,
  );
  const recLoading = $derived(recKey !== null && recFor !== recKey);
  const unavailableNow = $derived(recFor !== null && recFor === recKey ? recUnavailable : null);
  const recErrorNow = $derived(recFor !== null && recFor === recKey ? recError : null);
  // only a recommendation for exactly the picked car format, track, session and conditions is ever shown (dimmed
  // while a new style or driver loads)
  const recCurrent = $derived(
    rec && rec.car_format === fmt && rec.track_id === trackId && rec.conditions === cond && rec.requested_session === kind ? rec : null,
  );
  const shownStyle = $derived<SetupStyle>(styleChoice ?? (recCurrent && !recLoading ? recCurrent.requested_style : autoStyle));
  const recGroups = $derived(recCurrent ? groupRows(recCurrent.rows, recCurrent.groups) : []);
  const alternatives = $derived(
    unavailableNow ? sortAlternatives(unavailableNow.alternatives, { car_format: fmt, track_id: trackId, session: kind, conditions: cond, style: shownStyle }) : [],
  );

  const sessionId = $derived(
    pickedSession !== null && sessions.some((s) => s.id === pickedSession) ? pickedSession : (sessions[0]?.id ?? null),
  );
  const sessionDriver = $derived(sessions.find((s) => s.id === sessionId)?.driver_id ?? null);
  const sessOverrides = $derived<SessionSetupQuery>(overrides.sid === sessionId ? overrides : {});
  // a style picked above is for the picked driver: it applies to that driver's sessions only (others keep their
  // own driver's default)
  const sessStyle = $derived(sessOverrides.style ?? (styleChoice !== null && sessionDriver === currentDriver ? styleChoice : null));
  const sessKey = $derived(
    sessionId !== null
      ? [sessionId, sessOverrides.car_format ?? "", sessOverrides.session ?? "", sessOverrides.conditions ?? "", sessStyle ?? "auto"].join("|")
      : null,
  );
  const sessLoading = $derived(sessKey !== null && sessFor !== sessKey);
  const sessErrorNow = $derived(sessFor !== null && sessFor === sessKey ? sessError : null);
  const sessCurrent = $derived(sess && sess.session.id === sessionId ? sess : null);
  const choosable = $derived<NeedField[]>(
    sessCurrent
      ? (["car_format", "session", "conditions"] as NeedField[]).filter((f) => sessCurrent.needs.includes(f) || sessOverrides[f] != null)
      : [],
  );
  const diffRows = $derived.by<DiffRow[]>(() => {
    const d = sessCurrent?.diff;
    if (!d) return [];
    if (diffMode === "all") return d.rows;
    return d.rows.filter((r) => r.direction === "higher" || r.direction === "lower" || r.in_range === false);
  });
  const diffGroups = $derived(groupRows(diffRows, sessCurrent?.recommendation?.groups ?? []));
  const expList = $derived(expFor !== null && expFor === sessionId ? experiments : []);
  const openExperiments = $derived(expList.filter((e) => e.status === "proposed" || e.status === "running"));

  // ------------------------------------------------------------------ loading
  $effect(() => {
    untrack(() => void loadBase());
  });

  async function loadBase() {
    const tasks = [loadCatalog(), reloadSessions()];
    if (!driversProp) {
      tasks.push(
        rig
          .drivers()
          .then((r) => {
            fetchedDrivers = r.drivers;
            fetchedActive = r.activeId;
          })
          .catch(() => {
            fetchedDrivers = []; // driver profiles unavailable: setups still work for "any driver"
          }),
      );
    }
    await Promise.all(tasks);
  }

  async function loadCatalog() {
    catalogLoading = true;
    try {
      catalog = await carsetup.catalog();
      catalogError = null;
    } catch (e) {
      const t = errorText(e); // a broken catalogue is a 503 that already says so
      catalogError = /catalogue/i.test(t) ? t : `Car setup catalogue unavailable: ${t}`;
    } finally {
      catalogLoading = false;
    }
  }

  async function retryCatalog() {
    await loadCatalog();
    if (catalog) {
      sessFor = null; // the comparison needs the catalogue too
      sessReload++;
    }
  }

  // Reloads the session list (new sessions to compare or to link to an experiment), then the comparison and the
  // experiments for the session shown.
  let sessionsSeq = 0;
  async function reloadSessions() {
    const seq = ++sessionsSeq;
    sessionsLoading = true;
    try {
      const list = await carsetup.sessions();
      if (seq !== sessionsSeq) return;
      sessions = list;
      sessionsError = null;
    } catch (e) {
      if (seq === sessionsSeq) sessionsError = errorText(e);
    } finally {
      if (seq === sessionsSeq) {
        sessionsLoading = false;
        sessionsLoaded = true;
        sessFor = null;
        sessReload++;
        expReload++;
      }
    }
  }

  function firstTrack(f: FormatInfo): number | null {
    return f.tracks.find((t) => trackHasSetup(av, f.id, t.id))?.id ?? f.tracks[0]?.id ?? null;
  }

  // Seed the pickers once: the remembered car format, and the track / session / weather of the latest real (not
  // synthetic) F1 session when that track is drivable with that format.
  $effect(() => {
    if (!catalog || !sessionsLoaded || seeded) return;
    untrack(() => {
      const cat = catalog;
      if (!cat || !cat.formats.length) return;
      seeded = true;
      const ids = cat.formats.map((f) => f.id);
      const f = cat.formats.find((x) => x.id === (storedFormat(ids) ?? ids[0])) ?? cat.formats[0];
      fmt = f.id;
      const latest = sessions.find((s) => !s.synthetic && f1TrackId(s.track_id) !== null);
      const lt = latest ? f1TrackId(latest.track_id) : null;
      if (latest && lt !== null && f.tracks.some((t) => t.id === lt)) {
        trackId = lt;
        kind = sessionKindOf(latest.session_type) ?? "race";
        cond = conditionsOf(latest.weather) ?? "dry";
      } else {
        trackId = firstTrack(f);
      }
    });
  });

  let recSeq = 0;
  $effect(() => {
    const key = recKey;
    void recRetry;
    if (key === null || fmt === null || trackId === null) return;
    const q: RecommendationQuery = { car_format: fmt, track_id: trackId, session: kind, conditions: cond, style: styleChoice, driver_id: currentDriver };
    untrack(() => void loadRec(key, q));
  });

  async function loadRec(key: string, q: RecommendationQuery) {
    const seq = ++recSeq;
    try {
      const r = await carsetup.recommendation(q);
      if (seq !== recSeq) return;
      rec = r;
      recUnavailable = null;
      recError = null;
    } catch (e) {
      if (seq !== recSeq) return;
      rec = null; // never leave another combination's setup on screen
      recUnavailable = e instanceof CarSetupError ? e.unavailable : null;
      recError = recUnavailable ? null : errorText(e);
      showAllAlts = false;
    }
    recFor = key;
  }

  function retryRec() {
    recFor = null;
    recRetry++;
  }

  let sessSeq = 0;
  $effect(() => {
    const key = sessKey;
    const sid = sessionId;
    const o = sessOverrides;
    const q: SessionSetupQuery = { car_format: o.car_format, session: o.session, conditions: o.conditions, style: sessStyle };
    void sessReload;
    if (key === null || sid === null) return;
    untrack(() => void loadSession(key, sid, q));
  });

  async function loadSession(key: string, sid: string, q: SessionSetupQuery) {
    const seq = ++sessSeq;
    try {
      const r = await carsetup.session(sid, q);
      if (seq !== sessSeq) return;
      sess = r;
      sessError = null;
    } catch (e) {
      if (seq !== sessSeq) return;
      sess = null;
      sessError = errorText(e);
    }
    sessFor = key;
  }

  let expSeq = 0;
  $effect(() => {
    const sid = sessionId;
    void expReload;
    untrack(() => void loadExperiments(sid));
  });

  async function loadExperiments(sid: string | null) {
    const seq = ++expSeq;
    if (sid === null) {
      experiments = [];
      expFor = null;
      expError = null;
      expLoading = false;
      return;
    }
    expLoading = true;
    try {
      const r = await carsetup.experiments({ session_id: sid });
      if (seq !== expSeq) return;
      experiments = r;
      expFor = sid;
      expError = null;
    } catch (e) {
      if (seq !== expSeq) return;
      expError = errorText(e);
      if (expFor !== sid) {
        experiments = []; // never show another session's experiments under this one
        expFor = sid;
      }
    } finally {
      if (seq === expSeq) expLoading = false;
    }
  }

  // ------------------------------------------------------------------ actions
  function pickDriver(id: number) {
    pickedDriver = id;
    onDriverChange?.(id);
  }

  function pickFormat(id: CarFormat) {
    const f = catalog?.formats.find((x) => x.id === id);
    if (!f) return;
    fmt = id;
    rememberFormat(id);
    if (trackId === null || !f.tracks.some((t) => t.id === trackId)) trackId = firstTrack(f);
  }

  function pickStyle(s: SetupStyle | null) {
    styleState = { driver: currentDriver, style: s };
  }

  function pickAlternative(a: Combination) {
    if (a.car_format !== fmt) {
      fmt = a.car_format;
      rememberFormat(a.car_format);
    }
    trackId = a.track_id;
    kind = a.session;
    cond = a.conditions;
    pickStyle(a.style);
  }

  function setOverride<K extends keyof SessionSetupQuery>(field: K, value: SessionSetupQuery[K] | null) {
    const next: SessionSetupQuery = { ...sessOverrides };
    if (value === null || value === undefined) delete next[field];
    else next[field] = value;
    overrides = { ...next, sid: sessionId };
  }

  function pickSessionAlternative(a: Combination) {
    overrides = { sid: sessionId, car_format: a.car_format, session: a.session, conditions: a.conditions, style: a.style };
  }

  /** The same setup the comparison uses, in the pickers above (its style may come from the session's driver). */
  function showAbove(s: SessionSetupResponse, rr: SetupResult) {
    const c = s.chosen;
    if (!c.car_format || !c.session || !c.conditions || s.context.track_id === null) return;
    fmt = c.car_format;
    rememberFormat(c.car_format);
    trackId = s.context.track_id;
    kind = c.session;
    cond = c.conditions;
    if (rr.requested_style !== (styleChoice ?? autoStyle)) pickStyle(rr.requested_style);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function copy(key: string, text: string) {
    const ok = await copyText(text);
    const tick = ++copyTick;
    copied = { key, ok };
    setTimeout(() => {
      if (tick === copyTick) copied = null;
    }, ok ? 1500 : 4000);
  }

  function copyLabel(key: string, idle: string): string {
    if (copied?.key !== key) return idle;
    return copied.ok ? "Copied ✓" : "Copy failed";
  }

  function toggleRow(id: string) {
    expanded = expanded === id ? null : id;
  }

  function alreadyTesting(x: SuggestedExperiment, sid: string): boolean {
    return openExperiments.some((e) => e.before_session_id === sid && e.parameter === x.key && e.to_value !== null && Math.abs(e.to_value - x.to_value) < 1e-6);
  }

  async function testChange(s: SessionSetupResponse, x: SuggestedExperiment) {
    const sid = s.session.id;
    proposing = true;
    proposeError = null;
    try {
      await carsetup.propose({ before_session_id: sid, parameter: x.key, to_value: x.to_value, car_format: s.chosen.car_format });
      expReload++;
    } catch (e) {
      proposeError = { sid, text: errorText(e) };
    } finally {
      proposing = false;
    }
  }

  /** Sessions the backend accepts as the after session: same game, track and (when both are known) car, driven later. */
  function afterCandidates(exp: SetupExperiment): SessionOption[] {
    const before = sessions.find((s) => s.id === exp.before_session_id);
    return sessions.filter(
      (s) =>
        s.id !== exp.before_session_id &&
        s.game === exp.game &&
        s.track_id === exp.track_id &&
        (!exp.car_id || !s.car_id || s.car_id === exp.car_id) &&
        (before === undefined || s.started_unix > before.started_unix),
    );
  }

  function afterFor(exp: SetupExperiment): string | null {
    const cands = afterCandidates(exp);
    const picked = afterPick[exp.id];
    if (picked && cands.some((c) => c.id === picked)) return picked;
    return exp.after_session_id ?? cands[0]?.id ?? null;
  }

  function dropKey<T>(rec: Record<number, T>, id: number): Record<number, T> {
    const next = { ...rec };
    delete next[id];
    return next;
  }

  async function act(exp: SetupExperiment, action: "start" | "conclude" | "abandon") {
    busy = { ...busy, [exp.id]: action };
    expErrors = dropKey(expErrors, exp.id);
    try {
      let updated: SetupExperiment;
      if (action === "start") {
        const after = afterFor(exp);
        if (!after) throw new Error("Pick the session you drove with the change first.");
        updated = await carsetup.start(exp.id, after);
      } else if (action === "conclude") {
        updated = await carsetup.conclude(exp.id);
      } else {
        updated = await carsetup.abandon(exp.id, abandonReason);
        if (abandoning === exp.id) {
          abandoning = null;
          abandonReason = "";
        }
      }
      experiments = experiments.map((e) => (e.id === updated.id ? updated : e));
      expReload++; // a list request already in flight was read before this change: fetch a fresh one
    } catch (e) {
      expErrors = { ...expErrors, [exp.id]: errorText(e) };
    } finally {
      busy = dropKey(busy, exp.id);
    }
  }

  // ------------------------------------------------------------------ display helpers
  function sessionName(id: string | null): string {
    if (!id) return "not linked yet";
    const s = sessions.find((x) => x.id === id);
    return s ? sessionLabel(s) : id;
  }

  function avg(xs: number[] | null | undefined): number | null {
    return xs && xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
  }

  function pct(v: number | null): string {
    return v === null ? "—" : `${v.toFixed(2)} %`;
  }

  function deltaCls(v: number | null | undefined): string {
    if (v === null || v === undefined) return "muted";
    return v < -0.0005 ? "gain" : v > 0.0005 ? "loss" : "muted";
  }

  /** A number in the parameter's menu format, without its unit (for ranges that name the unit once). */
  function fixed(p: ParameterInfo | undefined, v: number | null): string {
    if (v === null || !Number.isFinite(v)) return "?";
    return p ? v.toFixed(p.decimals) : String(v);
  }

  function dirText(d: Direction): string {
    return d === "same" ? "same as yours" : d === "unknown" ? "cannot compare" : `recommended is ${d}`;
  }

  function refsFor(r: SetupResult, ids: string[]) {
    return ids.map((id) => r.setups[id]).filter((x) => x !== undefined);
  }

  function citedSites(r: SetupResult) {
    const ids = [...new Set(Object.values(r.setups).map((s) => s.source))];
    return ids.map((id) => sourcesById.get(id)).filter((x) => x !== undefined);
  }

  function sortedSetups(r: SetupResult) {
    // newest first; a setup without a date last
    return Object.values(r.setups).sort((a, b) => (b.published ?? "").localeCompare(a.published ?? ""));
  }

  function styleSub(s: SetupStyle): string {
    if (fmt === null || trackId === null) return "";
    const note = servedNote(av, { car_format: fmt, track_id: trackId, session: kind, conditions: cond, style: s });
    const auto = styleChoice === null && s === autoStyle ? "default" : "";
    return [auto, note].filter(Boolean).join(" · ");
  }

  function sessionSub(k: SessionKind): string {
    if (fmt === null || trackId === null) return "";
    return servedNote(av, { car_format: fmt, track_id: trackId, session: k, conditions: cond, style: shownStyle });
  }

  function condSub(c: Conditions): string {
    if (fmt === null || trackId === null) return "";
    return servedNote(av, { car_format: fmt, track_id: trackId, session: kind, conditions: c, style: shownStyle });
  }

  function fieldLabel(f: NeedField): string {
    return f === "car_format" ? "Car format" : f === "session" ? "Session" : "Conditions";
  }

  function fieldOptions(f: NeedField): { id: CarFormat | SessionKind | Conditions; label: string }[] {
    if (f === "car_format") return (catalog?.formats ?? []).map((x) => ({ id: x.id, label: x.label }));
    if (f === "session") return SESSION_KINDS.map((k) => ({ id: k, label: SESSION_LABEL[k] }));
    return CONDITIONS.map((c) => ({ id: c, label: CONDITIONS_LABEL[c] }));
  }

  function listText(xs: string[]): string {
    return xs.length <= 1 ? (xs[0] ?? "") : `${xs.slice(0, -1).join(", ")} or ${xs[xs.length - 1]}`;
  }
</script>

{#snippet conf(c: string)}
  <span class="conf conf-{c}" title="confidence {c}">{c}</span>
{/snippet}

{#snippet derivedMark(rule: string | null)}
  <span class="derived-badge" title={rule ? (rulesById.get(rule)?.description ?? rule) : "derived by pitwall"}>derived{rule ? ` · ${rule}` : ""}</span>
{/snippet}

{#snippet caveat(text: string)}
  <div class="caveat" role="note"><span class="caveat-icon" aria-hidden="true">i</span><p>{text}</p></div>
{/snippet}

{#snippet altButtons(alts: Combination[], current: { car_format?: CarFormat | null; track_id?: number | null }, onpick: (a: Combination) => void, showAll: boolean)}
  <div class="alts">
    {#each showAll ? alts : alts.slice(0, ALT_PREVIEW) as a (comboKey(a))}
      <button class="alt" onclick={() => onpick(a)}>
        {comboLabel(a, catalog, current)}{#if a.derived}<small> · derived</small>{/if}
      </button>
    {/each}
  </div>
{/snippet}

<div class="carsetup">
  <div class="sr-only" aria-live="polite">{copied ? (copied.ok ? "Copied to the clipboard" : "Copy failed") : ""}</div>
  {#if catalogError}
    <div class="panel bad errbar" role="alert">
      <span>{catalogError}</span>
      <button class="tool" onclick={retryCatalog} disabled={catalogLoading}>{catalogLoading ? "Loading…" : "Try again"}</button>
    </div>
  {/if}

  <!-- ============================================================ pickers -->
  <section class="panel pickers" aria-label="Choose the setup">
    {#if drivers.length}
      <div class="pick full">
        <div class="sub">Driver</div>
        <div class="chips" role="radiogroup" aria-label="Driver">
          {#each drivers as d (d.id)}
            <button role="radio" aria-checked={d.id === currentDriver} class="chip" class:on={d.id === currentDriver} onclick={() => pickDriver(d.id)}>
              <span class="swatch" style:background={d.colour ?? "var(--faint)"}></span>{d.name}
              {#if d.skill_level}<small>{d.skill_level}</small>{/if}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    {#if catalog}
      <div class="pick full">
        <div class="sub">Cars</div>
        <div class="seg" style:grid-template-columns="repeat({catalog.formats.length}, 1fr)" role="radiogroup" aria-label="Car format">
          {#each catalog.formats as f (f.id)}
            <button role="radio" aria-checked={fmt === f.id} class:on={fmt === f.id} onclick={() => pickFormat(f.id)}>
              {f.label}<small>{f.description}</small>
            </button>
          {/each}
        </div>
      </div>

      <div class="pick">
        <label class="sub" for="cs-track">Track</label>
        <select id="cs-track" class="big-select" value={trackId ?? ""} onchange={(e) => (trackId = Number(e.currentTarget.value))} disabled={!format}>
          {#each format?.tracks ?? [] as t (t.id)}
            <option value={t.id}>{t.name}{fmt && !trackHasSetup(av, fmt, t.id) ? " (no setup yet)" : ""}</option>
          {/each}
        </select>
      </div>

      <div class="pick">
        <div class="sub">Session</div>
        <div class="seg two" role="radiogroup" aria-label="Session">
          {#each SESSION_KINDS as k (k)}
            {@const sub = sessionSub(k)}
            <button role="radio" aria-checked={kind === k} class:on={kind === k} class:none={sub === "no setup"} onclick={() => (kind = k)}>
              {SESSION_LABEL[k]}{#if sub}<small>{sub}</small>{/if}
            </button>
          {/each}
        </div>
      </div>

      <div class="pick">
        <div class="sub">Conditions</div>
        <div class="seg two" role="radiogroup" aria-label="Conditions">
          {#each CONDITIONS as c (c)}
            {@const sub = condSub(c)}
            <button role="radio" aria-checked={cond === c} class:on={cond === c} class:none={sub === "no setup"} onclick={() => (cond = c)}>
              {CONDITIONS_LABEL[c]}{#if sub}<small>{sub}</small>{/if}
            </button>
          {/each}
        </div>
      </div>

      <div class="pick style-pick">
        <div class="sub">Style{driver ? ` for ${driver.name}` : ""}{driver?.skill_level ? ` (${driver.skill_level})` : ""}</div>
        <div class="seg three" role="radiogroup" aria-label="Style">
          {#each STYLES as s (s)}
            {@const sub = styleSub(s)}
            <button role="radio" aria-checked={shownStyle === s} class:on={shownStyle === s} class:none={sub.endsWith("no setup")} onclick={() => pickStyle(s)}>
              {STYLE_LABEL[s]}{#if sub}<small>{sub}</small>{/if}
            </button>
          {/each}
        </div>
        {#if styleChoice !== null}
          <button class="link" onclick={() => pickStyle(null)}>
            Use {driver ? `${driver.name}'s` : "the"} default ({STYLE_LABEL[autoStyle]}{driver?.skill_level ? `, ${driver.skill_level}` : ""})
          </button>
        {/if}
      </div>
    {:else}
      <div class="empty full">{catalogError ? "The track, session and style pickers appear once the catalogue loads." : "Loading the setup catalogue…"}</div>
    {/if}
  </section>

  <!-- ============================================================ recommendation -->
  {#if unavailableNow}
    <section class="panel unavailable" role="status">
      <h3>No recommendation for this combination</h3>
      <p class="lead">{unavailableNow.reason}</p>
      {#if alternatives.length}
        <div class="sub">Setups that do exist</div>
        {@render altButtons(alternatives, { car_format: fmt, track_id: trackId }, pickAlternative, showAllAlts)}
        {#if alternatives.length > ALT_PREVIEW}
          <button class="more" onclick={() => (showAllAlts = !showAllAlts)}>{showAllAlts ? "Show fewer" : `Show all ${alternatives.length}`}</button>
        {/if}
      {:else}
        <p class="muted">The catalogue has no setup for this track and car format yet.</p>
      {/if}
    </section>
  {:else if recErrorNow}
    <div class="panel bad errbar" role="alert">
      <span>{recErrorNow}</span>
      <button class="tool" onclick={retryRec}>Try again</button>
    </div>
  {:else if recCurrent}
    {@const r = recCurrent}
    <div class="top" class:stale={recLoading} aria-busy={recLoading}>
      <section class="panel summary">
        <div class="sum-head">
          <div>
            <div class="title">{r.track_name}</div>
            <div class="muted">{formatLabel(catalog, r.car_format)}</div>
          </div>
          <button class="copy primary-copy" onclick={() => copy("all", setupCopyText(r, catalog))} disabled={recLoading}>{copyLabel("all", "Copy whole setup")}</button>
        </div>
        <div class="tags">
          <span class="badge">{SESSION_LABEL[r.session]}</span>
          <span class="badge" class:wet={r.conditions === "wet"}>{CONDITIONS_LABEL[r.conditions]}</span>
          <span class="badge">{STYLE_LABEL[r.style]}</span>
          {#if r.selection === "derived"}<span class="badge derived">derived by pitwall</span>{/if}
        </div>
        <div class="kv">
          <span class="muted">Built from</span><span>{SELECTION_LABEL[r.selection]}</span>
          <span class="muted">Style</span>
          <span>{r.style_reason === "requested" ? "your choice" : `${r.style_reason}${r.skill_source === "driver" && driver ? ` (${driver.name})` : ""}`}</span>
          {#if format}
            <span class="muted">Handling patch</span>
            <span>{format.latest_handling_patch.version} ({format.latest_handling_patch.date}): <span class="muted">{format.latest_handling_patch.note}</span></span>
          {/if}
        </div>
        {#each r.notes as n, i (i)}<div class="warnline">⚠ {n}</div>{/each}
        {@render caveat(r.caveat)}
      </section>

      <section class="panel sources">
        <h3>Sources ({Object.keys(r.setups).length})</h3>
        {#each sortedSetups(r) as s (s.id)}
          {@const old = predatesPatch(s, format?.latest_handling_patch)}
          <div class="source">
            <a href={s.url} target="_blank" rel="noopener noreferrer">{s.source_name}{s.author ? ` · ${s.author}` : ""}</a>
            <div class="small muted">
              {s.published ? `Published ${s.published}` : "Date not stated"} · {s.patch ? `game v${s.patch}` : "game version not stated"}
              {#if old === "yes"}<span class="badge warn">before handling patch {format?.latest_handling_patch.version}</span>
              {:else if old === "maybe"}<span class="badge warn">may predate handling patch {format?.latest_handling_patch.version}</span>{/if}
            </div>
            <div class="small faint">
              {s.session} · {s.conditions}{s.style ? ` · ${s.style}` : ""}{s.input ? ` · ${s.input}` : ""} · values checked {s.verified}
            </div>
          </div>
        {:else}
          <p class="muted small">No published setup is cited for this recommendation.</p>
        {/each}
        {#if r.disagreements.length}
          <div class="sub gap">Where sources disagree</div>
          <ul class="list">{#each r.disagreements as d, i (i)}<li>{d}</li>{/each}</ul>
        {/if}
        {#if citedSites(r).length}
          <details class="terms">
            <summary>About these sources and their terms</summary>
            {#each citedSites(r) as site (site.id)}
              <div class="small site">
                <a href={site.url} target="_blank" rel="noopener noreferrer">{site.name}</a>
                <span class="faint">({site.kind.replace(/_/g, " ")}, accessed {site.accessed})</span>
                {#if site.terms_url}<a href={site.terms_url} target="_blank" rel="noopener noreferrer">terms</a>{/if}
                <div class="muted">{site.terms}</div>
              </div>
            {/each}
          </details>
        {/if}
      </section>
    </div>

    {#each recGroups as g (g.group)}
      <section class="panel" class:stale={recLoading}>
        <div class="sec-head">
          <h3>{g.group}</h3>
          <button class="copy" onclick={() => copy(`sec:${g.group}`, sectionCopyText(g.group, g.rows, setupHeading(r, catalog)))} disabled={recLoading}>
            {copyLabel(`sec:${g.group}`, "Copy section")}
          </button>
        </div>
        <table class="rows">
          <tbody>
            {#each g.rows as row (row.key)}
              {@const id = `rec:${row.key}`}
              {@const open = expanded === id}
              <tr class:derived={row.derived} class:open>
                <td class="label-cell">
                  <button class="rowbtn" aria-expanded={open} onclick={() => toggleRow(id)}>
                    <span class="chev" aria-hidden="true">{open ? "▾" : "▸"}</span>
                    <span>{row.label}</span>
                  </button>
                </td>
                <td class="value"><span class="num big">{row.value === null ? "unknown" : row.display}</span>{#if row.unit && row.value !== null}<span class="unit">{row.unit}</span>{/if}</td>
                <td class="badges-cell">
                  {@render conf(row.confidence)}
                  {#if row.derived}{@render derivedMark(row.rule)}{/if}
                </td>
              </tr>
              {#if open}
                {@render rowDetail(r, row)}
              {/if}
            {/each}
          </tbody>
        </table>
      </section>
    {/each}
  {:else if catalog}
    <div class="panel empty">{recKey !== null ? "Loading the setup…" : "Pick a track to see its setup."}</div>
  {/if}

  {#snippet rowDetail(r: SetupResult, row: SetupRow)}
    {@const p = params.get(row.key)}
    {@const from = row.from_setup ? r.setups[row.from_setup] : undefined}
    {@const agree = refsFor(r, row.sources)}
    {@const rng = p?.ranges[r.car_format]}
    {@const open_ends = [rng?.min_confirmed === false ? "low" : null, rng?.max_confirmed === false ? "high" : null].filter((x) => x !== null)}
    <tr class="detail">
      <td colspan="3">
        {#if row.derived}
          <div class="derived-box">
            <strong>Derived by pitwall</strong>{row.rule ? ` (rule ${row.rule})` : ""}: {row.rule ? (rulesById.get(row.rule)?.description ?? "") : "computed from the cited setups"}
          </div>
        {/if}
        {#if from}
          <div><span class="muted">{row.derived ? "Based on" : "From"}</span> <a class="tap" href={from.url} target="_blank" rel="noopener noreferrer">{from.source_name}{from.author ? ` · ${from.author}` : ""}</a> <span class="small faint">({from.published ?? "date not stated"}{from.patch ? `, v${from.patch}` : ""})</span></div>
        {:else if row.value === null}
          <div class="muted">No cited setup gives this value, so it stays unknown.</div>
        {/if}
        {#if agree.length}
          <div class="small"><span class="muted">Agreeing setups ({agree.length}):</span> {agree.map((a) => `${a.source_name}${a.author ? ` (${a.author})` : ""}`).join(", ")}</div>
        {/if}
        {#if row.spread}
          <div class="small"><span class="muted">Published values range</span> <span class="num">{fixed(p, row.spread[0])} – {fixed(p, row.spread[1])}{row.unit ? ` ${row.unit}` : ""}</span></div>
        {/if}
        {#if row.patches.length}
          <div class="small"><span class="muted">Game versions</span> {row.patches.map((x) => `v${x}`).join(", ")}</div>
        {/if}
        {#if row.min !== null && row.max !== null}
          <div class="small faint">
            {open_ends.length ? "Range" : "Game range"} {fixed(p, row.min)} – {fixed(p, row.max)}{row.unit ? ` ${row.unit}` : ""}{row.step !== null ? `, step ${row.step}` : ""}
            {#if open_ends.length}
              (the {open_ends.join(" and ")} {open_ends.length > 1 ? "ends are" : "end is"} only what published setups use; the game's own limit is not confirmed)
            {/if}
          </div>
          {#if rng?.note}<div class="small faint">{rng.note}</div>{/if}
        {/if}
        {#if p}
          <div class="effects small">
            <div><strong>Higher:</strong> {p.higher}</div>
            <div><strong>Lower:</strong> {p.lower}</div>
          </div>
        {/if}
      </td>
    </tr>
  {/snippet}

  <!-- ============================================================ your setup vs recommended -->
  <section class="panel compare">
    <div class="sec-head">
      <h3>Your setup vs recommended</h3>
      <div class="tools">
        <label class="session-pick">
          <span class="sr-only">Session to compare</span>
          <select class="big-select" value={sessionId ?? ""} onchange={(e) => (pickedSession = e.currentTarget.value)} disabled={!sessions.length}>
            {#each sessions as s (s.id)}<option value={s.id}>{sessionLabel(s)}</option>{/each}
          </select>
        </label>
        <button class="tool" onclick={reloadSessions} disabled={sessionsLoading || sessLoading}>{sessionsLoading || sessLoading ? "Loading…" : "Refresh"}</button>
      </div>
    </div>

    {#if sessionsError}<div class="bad" role="alert">{sessionsError}</div>{/if}
    {#if !sessions.length}
      {#if !sessionsLoaded}
        <p class="muted">Loading…</p>
      {:else if !sessionsError}
        <p class="muted">No sessions yet. Drive with UDP telemetry on and your setup will be compared here.</p>
      {/if}
    {:else if sessErrorNow}
      <div class="bad" role="alert">{sessErrorNow}</div>
    {:else if sessCurrent}
      {@const s = sessCurrent}
      <div class="sess-body" class:stale={sessLoading} aria-busy={sessLoading}>
        <div class="context">
          <div>
            <div class="sub">Track</div>
            <div class="ctx-val">{s.session.track_name ?? s.context.track_name ?? "Unknown track"}</div>
            {#if s.context.reasons.track_id}<div class="small muted">{s.context.reasons.track_id}</div>{/if}
            {#if s.context.reasons.game}<div class="small muted">{s.context.reasons.game}</div>{/if}
          </div>
          <div>
            <div class="sub">Cars</div>
            <div class="ctx-val">
              {s.chosen.car_format ? formatLabel(catalog, s.chosen.car_format) : "Unknown"}
              {#if sessOverrides.car_format}<span class="badge">your choice</span>
              {:else if s.context.car_format}<span class="badge" class:live={s.context.car_format_certain} class:warn={!s.context.car_format_certain}>{s.context.car_format_certain ? "certain" : "not certain"}</span>{/if}
            </div>
            {#if s.context.reasons.car_format}<div class="small muted">{s.context.reasons.car_format}</div>{/if}
            {#if s.session.car_name}<div class="small faint">Game car: {s.session.car_name}</div>{/if}
          </div>
          <div>
            <div class="sub">Session</div>
            <div class="ctx-val">
              {s.chosen.session ? SESSION_LABEL[s.chosen.session] : "Unknown"}
              {#if sessOverrides.session}<span class="badge">your choice</span>{/if}
            </div>
            <div class="small muted">Game: {sessionTypeLabel(s.session.session_type_raw ?? s.session.session_type)}</div>
            {#if s.context.reasons.session}<div class="small muted">{s.context.reasons.session}</div>{/if}
          </div>
          <div>
            <div class="sub">Conditions</div>
            <div class="ctx-val">
              {s.chosen.conditions ? CONDITIONS_LABEL[s.chosen.conditions] : "Unknown"}
              {#if sessOverrides.conditions}<span class="badge">your choice</span>{/if}
            </div>
            {#if s.session.weather.condition}<div class="small muted">Weather: {s.session.weather.condition.replace(/_/g, " ")}</div>{/if}
            {#if s.context.reasons.conditions}<div class="small muted">{s.context.reasons.conditions}</div>{/if}
          </div>
          {#if s.session.driver || s.session.synthetic}
            <div>
              <div class="sub">Driver</div>
              <div class="ctx-val">
                {s.session.driver?.name ?? "Unknown"}
                {#if s.session.synthetic}<span class="badge synthetic">synthetic</span>{/if}
              </div>
              {#if s.session.driver?.skill_level}<div class="small muted">{s.session.driver.skill_level}</div>{/if}
            </div>
          {/if}
        </div>
        {#each s.context.notes as n, i (i)}<div class="note small muted">• {n}</div>{/each}

        {#if choosable.length}
          {@const unknown = choosable.filter((f) => s.context[f] == null)}
          <div class="choose">
            <p class="small">
              {#if unknown.length}
                Pitwall cannot tell the {listText(unknown.map((f) => fieldLabel(f).toLowerCase()))} from the game for this session, so choose{unknown.length < choosable.length ? " (you also changed what the game reported)" : ""}:
              {:else}
                You changed what the game reported for this session:
              {/if}
            </p>
            {#each choosable as f (f)}
              {@const opts = fieldOptions(f)}
              <div class="pick">
                <div class="sub">{fieldLabel(f)}</div>
                <div class="seg" style:grid-template-columns="repeat({opts.length}, 1fr)" role="radiogroup" aria-label={fieldLabel(f)}>
                  {#each opts as o (o.id)}
                    <button role="radio" aria-checked={s.chosen[f] === o.id} class:on={s.chosen[f] === o.id} onclick={() => setOverride(f, o.id)}>{o.label}</button>
                  {/each}
                </div>
                {#if sessOverrides[f] != null && s.context[f] != null}
                  <button class="link" onclick={() => setOverride(f, null)}>Use what the game reported</button>
                {/if}
              </div>
            {/each}
          </div>
        {/if}

        {@render caveat(s.caveat)}

        {#if s.unavailable}
          {@const alts = s.unavailable.alternatives.filter((a) => a.track_id === s.context.track_id)}
          <div class="unavail-inline">
            <p class="lead">{s.unavailable.reason}</p>
            {#if alts.length}
              <div class="sub">Setups that do exist for this track</div>
              {@render altButtons(
                sortAlternatives(alts, { car_format: s.chosen.car_format, track_id: s.context.track_id, session: s.chosen.session, conditions: s.chosen.conditions, style: s.chosen.style }),
                { car_format: s.chosen.car_format, track_id: s.context.track_id },
                pickSessionAlternative,
                true,
              )}
            {/if}
          </div>
        {:else if s.recommendation}
          {@const rr = s.recommendation}
          <div class="against">
            <span class="muted">Compared with</span> <strong>{setupHeading(rr, catalog)}</strong>
            {#if sessOverrides.style}<span class="badge">your choice</span>{/if}
            <button class="link" onclick={() => showAbove(s, rr)}>Show this setup above</button>
            {#if sessOverrides.style}<button class="link" onclick={() => setOverride("style", null)}>Use the default style</button>{/if}
          </div>
          {#each rr.notes as n, i (i)}<div class="warnline">⚠ {n}</div>{/each}

          {#if !s.setup}
            <p class="muted">Pitwall has not received your car setup for this session yet. The game sends it while you drive with UDP telemetry on.</p>
          {:else if s.diff}
            {@const d = s.diff}
            <p class="lead summary-line">{d.summary}</p>
            {#if d.out_of_range.length}
              <div class="range-warn" role="alert">
                <strong>Some of your values are outside the {formatLabel(catalog, rr.car_format)} range.</strong>
                This usually means the car format is wrong, so the differences below are not meaningful yet.
                <div class="alts">
                  {#each (catalog?.formats ?? []).filter((f) => f.id !== rr.car_format) as f (f.id)}
                    <button class="alt" onclick={() => setOverride("car_format", f.id)}>Compare with {f.label}</button>
                  {/each}
                </div>
              </div>
            {/if}

            <div class="diff-tools">
              <div class="seg two small-seg" role="radiogroup" aria-label="Rows to show">
                <button role="radio" aria-checked={diffMode === "diff"} class:on={diffMode === "diff"} onclick={() => (diffMode = "diff")}>Differences ({d.differing})</button>
                <button role="radio" aria-checked={diffMode === "all"} class:on={diffMode === "all"} onclick={() => (diffMode = "all")}>All ({d.rows.length})</button>
              </div>
            </div>

            {#each diffGroups as g (g.group)}
              <div class="sub gap">{g.group}</div>
              <table class="diff">
                <thead>
                  <tr><th>Setting</th><th class="right">Yours</th><th class="arrow-col"><span class="sr-only">Direction</span></th><th>Recommended</th><th class="mag-col">Change</th></tr>
                </thead>
                <tbody>
                  {#each g.rows as row (row.key)}
                    <tr class="diff-row" class:out={row.in_range === false}>
                      <td class="dlabel">
                        {row.label}
                        {#if row.derived}{@render derivedMark(null)}{/if}
                      </td>
                      <td class="right num yours">{valueText({ display: row.yours_display, unit: row.unit, value: row.yours })}</td>
                      <td class="arrow dir-{row.direction}"><span aria-hidden="true">{DIRECTION_ARROW[row.direction]}</span><span class="sr-only">{dirText(row.direction)}</span></td>
                      <td class="num rec">{valueText({ display: row.recommended_display, unit: row.unit, value: row.recommended })} {@render conf(row.confidence)}</td>
                      <td class="mag-col"><span class="mag mag-{row.magnitude}">{row.magnitude}</span>{#if row.steps !== null && row.direction !== "same"}<div class="small faint num">{stepsText(row.steps)}</div>{/if}</td>
                    </tr>
                    {#if row.in_range === false || row.direction !== "same"}
                      <tr class="explain" class:out={row.in_range === false}>
                        <td colspan="5">
                          {#if row.in_range === false}<span class="badge warn">outside the {formatLabel(catalog, rr.car_format)} range</span>{/if}
                          {row.explanation}
                        </td>
                      </tr>
                    {/if}
                  {/each}
                </tbody>
              </table>
            {:else}
              <p class="muted">{diffMode === "diff" ? "No differences to show." : "Nothing to compare."}</p>
            {/each}
            {#if d.not_compared.length}
              <div class="small faint gap">Not on the setup sheet, so not compared: {d.not_compared.join(", ")}</div>
            {/if}

            {#if d.experiment}
              {@const x = d.experiment}
              {@const testing = alreadyTesting(x, s.session.id)}
              <div class="suggest">
                <div class="sub">Something to test</div>
                <p>{x.text}</p>
                <div class="suggest-row">
                  <span class="num big">{paramValue(params.get(x.key), x.from_value)} → {paramValue(params.get(x.key), x.to_value)}</span>
                  <button class="primary" onclick={() => testChange(s, x)} disabled={proposing || testing || sessLoading}>
                    {testing ? "Already in your experiments" : proposing ? "Saving…" : "Test this change"}
                  </button>
                </div>
                {#if proposeError && proposeError.sid === s.session.id}<div class="bad small" role="alert">{proposeError.text}</div>{/if}
              </div>
            {/if}
          {/if}
        {/if}
      </div>
    {:else}
      <p class="muted">Loading…</p>
    {/if}
  </section>

  <!-- ============================================================ experiments -->
  <section class="panel experiments">
    <div class="sec-head">
      <h3>Setup experiments{sessionId ? " for this session" : ""}</h3>
      <button class="tool" onclick={reloadSessions} disabled={sessionsLoading || expLoading}>{sessionsLoading || expLoading ? "Loading…" : "Refresh"}</button>
    </div>
    <p class="small muted">One change at a time: drive a session with the change, link it here, then compare it with the session before.</p>
    {#if expError}<div class="bad" role="alert">{expError}</div>{/if}
    {#each expList as exp (exp.id)}
      {@const p = params.get(exp.parameter)}
      {@const cmp = exp.after_metrics?.comparison}
      {@const b = exp.before_metrics}
      {@const a = exp.after_metrics}
      {@const cands = afterCandidates(exp)}
      {@const after = afterFor(exp)}
      {@const working = busy[exp.id]}
      <article class="exp exp-{exp.status}">
        <div class="exp-head">
          <span class="pill st-{exp.status}">{STATUS_LABEL[exp.status]}</span>
          <strong class="exp-title">{p?.label ?? exp.parameter}</strong>
          <span class="num big">{paramValue(p, exp.from_value)} → {paramValue(p, exp.to_value)}</span>
          <span class="small faint">{when(exp.created_unix)}</span>
        </div>
        <p class="hyp">{exp.hypothesis}</p>
        <div class="kv small">
          <span class="muted">Before</span><span>{sessionName(exp.before_session_id)}</span>
          <span class="muted">After</span><span>{sessionName(exp.after_session_id)}</span>
        </div>

        {#if exp.status === "proposed" || exp.status === "running"}
          <div class="exp-actions">
            {#if cands.length}
              <label class="after-pick">
                <span class="sub">Session driven with the change</span>
                <select class="big-select" value={after ?? ""} onchange={(e) => (afterPick = { ...afterPick, [exp.id]: e.currentTarget.value })}>
                  {#each cands as c (c.id)}<option value={c.id}>{sessionLabel(c)}</option>{/each}
                </select>
              </label>
              <button onclick={() => act(exp, "start")} disabled={!!working || !after || after === exp.after_session_id}>
                {working === "start" ? "Linking…" : exp.after_session_id ? "Change session" : "Link session"}
              </button>
            {:else}
              <p class="small muted">Drive a session on this track with only this change, then tap Refresh to link it.</p>
            {/if}
            {#if exp.status === "running"}
              <button class="primary" onclick={() => act(exp, "conclude")} disabled={!!working}>{working === "conclude" ? "Comparing…" : "Compare and conclude"}</button>
            {/if}
            {#if abandoning === exp.id}
              <div class="abandon">
                <input type="text" bind:value={abandonReason} maxlength="500" placeholder="Reason (optional)" aria-label="Reason for abandoning (optional)" />
                <button onclick={() => act(exp, "abandon")} disabled={!!working}>{working === "abandon" ? "Saving…" : "Abandon experiment"}</button>
                <button onclick={() => ((abandoning = null), (abandonReason = ""))}>Keep it</button>
              </div>
            {:else}
              <button class="quiet" onclick={() => ((abandoning = exp.id), (abandonReason = ""))} disabled={!!working}>Abandon…</button>
            {/if}
          </div>
        {/if}
        {#if expErrors[exp.id]}<div class="bad small" role="alert">{expErrors[exp.id]}</div>{/if}

        {#if cmp}
          <div class="verdict">
            <span class="pill v-{cmp.verdict}">{VERDICT_LABEL[cmp.verdict]}</span>
            <span class="small">{cmp.reason}</span>
          </div>
          <table class="metrics">
            <thead><tr><th></th><th class="right">Before</th><th class="right">After</th><th class="right">Change</th></tr></thead>
            <tbody>
              <tr><td class="muted">Median clean lap</td><td class="right num">{lapTime(b?.median_clean_ms)}</td><td class="right num">{lapTime(a?.median_clean_ms)}</td><td class="right num {deltaCls(cmp.median_delta_s)}">{signed(cmp.median_delta_s, 3, " s")}</td></tr>
              <tr><td class="muted">Best clean lap</td><td class="right num">{lapTime(b?.best_clean_ms)}</td><td class="right num">{lapTime(a?.best_clean_ms)}</td><td class="right num {deltaCls(cmp.best_delta_s)}">{signed(cmp.best_delta_s, 3, " s")}</td></tr>
              <tr><td class="muted">Theoretical best</td><td class="right num">{lapTime(b?.theoretical_best_ms)}</td><td class="right num">{lapTime(a?.theoretical_best_ms)}</td><td class="right num {deltaCls(cmp.theoretical_delta_s)}">{signed(cmp.theoretical_delta_s, 3, " s")}</td></tr>
              <tr><td class="muted">Clean laps</td><td class="right num">{b?.clean_laps ?? "—"}</td><td class="right num">{a?.clean_laps ?? "—"}</td><td class="right small faint">{cmp.noise_s !== null ? `noise ±${cmp.noise_s.toFixed(3)} s` : ""}</td></tr>
              {#if avg(b?.wear_rate_pct_per_lap) !== null || avg(a?.wear_rate_pct_per_lap) !== null}
                <tr><td class="muted">Tyre wear / lap</td><td class="right num">{pct(avg(b?.wear_rate_pct_per_lap))}</td><td class="right num">{pct(avg(a?.wear_rate_pct_per_lap))}</td><td></td></tr>
              {/if}
            </tbody>
          </table>
          {@const check = cmp.setup_check}
          <div class="check small">
            <span class="muted">Setup check:</span>
            {#if check.applied === true}<span class="gain">the change was applied</span>
            {:else if check.applied === false}<span class="loss">the after session does not have the experiment's value</span>
            {:else}<span class="muted">{check.note ?? "unknown"}</span>{/if}
            {#if check.applied !== null && check.note}<span class="muted"> · {check.note}</span>{/if}
          </div>
          {#if check.other_changes.length}
            <div class="range-warn small">
              <strong>Other settings changed too</strong>, so the effect cannot be put down to this one change:
              {check.other_changes.map((o) => `${o.label} ${paramValue(params.get(o.key), o.before)} → ${paramValue(params.get(o.key), o.after)}`).join(", ")}
            </div>
          {/if}
          {#if cmp.corners.length}
            <details class="corners">
              <summary>Corner by corner ({cmp.corners.length})</summary>
              <table class="metrics">
                <thead><tr><th>Corner</th><th class="right">Laps</th><th class="right">Time</th><th class="right">Min speed</th><th class="right">Exit speed</th></tr></thead>
                <tbody>
                  {#each cmp.corners as c (c.corner)}
                    <tr>
                      <td>{c.label}</td>
                      <td class="right num">{c.laps}</td>
                      <td class="right num {deltaCls(c.mean_time_delta_s)}">{signed(c.mean_time_delta_s, 3, " s")}</td>
                      <td class="right num">{signed(c.mean_min_speed_delta_kph, 1, " km/h")}</td>
                      <td class="right num">{signed(c.mean_exit_speed_delta_kph, 1, " km/h")}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </details>
          {/if}
        {/if}
        {#if exp.conclusion}<p class="conclusion">{exp.conclusion}</p>{/if}
      </article>
    {:else}
      {#if !sessionsLoaded || (sessionId !== null && expFor !== sessionId)}
        {#if !expError}<p class="muted">Loading…</p>{/if}
      {:else if sessionId === null}
        <p class="muted">Experiments start from a session pitwall has recorded: drive one with UDP telemetry on.</p>
      {:else if !expError}
        <p class="muted">No experiments for this session yet.{sessCurrent?.diff?.experiment ? " Use “Test this change” above to start one." : ""}</p>
      {/if}
    {/each}
  </section>

  <!-- ============================================================ legend -->
  {#if catalog}
    <section class="panel legend">
      <h3>How to read the badges</h3>
      <div class="legend-grid">
        <div>{@render conf("high")} <span class="small muted">three or more current published setups, at least two thirds agree</span></div>
        <div>{@render conf("medium")} <span class="small muted">at least two current published setups agree</span></div>
        <div>{@render conf("low")} <span class="small muted">one setup, setups that disagree, or setups from before the latest handling patch</span></div>
        <div>{@render derivedMark(null)} <span class="small muted">pitwall computed the value with a catalogue rule (named on the badge); every other value is exactly as a source published it</span></div>
      </div>
      <p class="small faint">Catalogue updated {catalog.updated} · research: {catalog.research_doc}</p>
    </section>
  {/if}
</div>

<style>
  .carsetup { display: grid; gap: 12px; max-width: 1200px; margin: 0 auto; }
  .sub { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 6px; display: block; }
  .sub.gap, .gap { margin-top: 12px; }
  .small { font-size: 12px; }
  .big { font-size: 20px; font-weight: 700; }
  .title { font-weight: 700; font-size: 20px; }
  .lead { margin: 8px 0; font-size: 15px; line-height: 1.45; }
  .stale { opacity: 0.55; transition: opacity 0.15s; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
  .errbar { display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; }

  /* pickers */
  .pickers { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1.5fr); gap: 16px; align-items: start; }
  .pick { min-width: 0; }
  .pick.full, .empty.full { grid-column: 1 / -1; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 8px 14px; border-radius: 999px; font-weight: 600; }
  .chip small { color: var(--muted); font-weight: 400; }
  .chip.on { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 16%, transparent); }
  .swatch { width: 12px; height: 12px; border-radius: 50%; }
  .seg { display: grid; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .seg.two { grid-template-columns: repeat(2, 1fr); }
  .seg.three { grid-template-columns: repeat(3, 1fr); }
  .seg button { border: none; border-radius: 0; background: transparent; min-height: 52px; padding: 8px 10px; font-weight: 600; font-size: 15px; display: grid; gap: 2px; align-content: center; text-align: center; }
  .seg button + button { border-left: 1px solid var(--border); }
  .seg button small { font-size: 11px; font-weight: 400; color: var(--muted); line-height: 1.25; }
  .seg button.on { background: var(--accent); color: #fff; }
  .seg button.on small { color: color-mix(in srgb, #fff 82%, transparent); }
  .seg button.none:not(.on) { color: var(--faint); }
  .small-seg button { min-height: 44px; font-size: 13px; }
  .big-select { width: 100%; min-height: 52px; font-size: 16px; font-weight: 600; }
  .link { background: none; border: none; padding: 0; min-height: 44px; color: var(--ref); text-decoration: underline; text-align: left; }

  /* recommendation */
  .top { display: grid; grid-template-columns: 1.2fr 1fr; gap: 12px; }
  .sum-head { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; align-items: flex-start; }
  .tags { display: flex; gap: 6px; flex-wrap: wrap; margin: 10px 0; }
  .badge.wet { color: var(--ref); border-color: color-mix(in srgb, var(--ref) 45%, transparent); }
  .badge.derived { color: var(--best); border-color: color-mix(in srgb, var(--best) 45%, transparent); }
  .kv { display: grid; grid-template-columns: auto 1fr; gap: 6px 12px; margin: 8px 0; }
  .warnline { color: var(--loss); margin: 6px 0; font-weight: 600; }
  .caveat { display: flex; gap: 12px; align-items: flex-start; margin-top: 12px; padding: 12px 14px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--ref) 35%, transparent); background: color-mix(in srgb, var(--ref) 8%, transparent); }
  .caveat p { margin: 0; font-size: 15px; line-height: 1.45; }
  .caveat-icon { flex: none; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; font-family: var(--sans); color: var(--ref); border: 1.5px solid var(--ref); }
  .source { padding: 8px 0; border-bottom: 1px solid color-mix(in srgb, var(--border) 60%, transparent); display: grid; gap: 3px; }
  .source a, .site a, td a { color: var(--ref); }
  .source a { font-weight: 600; min-height: 44px; display: inline-flex; align-items: center; }
  .site a, a.tap { min-height: 44px; display: inline-flex; align-items: center; }
  .list { margin: 0; padding-left: 18px; display: grid; gap: 4px; }
  .terms { margin-top: 10px; }
  .terms summary, .corners summary { cursor: pointer; color: var(--muted); min-height: 44px; display: flex; align-items: center; }
  .site { margin: 6px 0; }
  .copy { min-height: 44px; min-width: 64px; padding: 6px 14px; font-size: 13px; }
  .primary-copy { font-weight: 600; }
  .sec-head { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 8px; }
  .sec-head h3 { margin: 0; }

  .rows td { padding: 6px 8px; vertical-align: middle; }
  .label-cell { width: 45%; }
  .rowbtn { width: 100%; min-height: 48px; display: flex; align-items: center; gap: 10px; background: transparent; border: none; padding: 4px 0; text-align: left; font-size: 15px; font-weight: 600; }
  .chev { color: var(--muted); width: 14px; flex: none; }
  .value { white-space: nowrap; }
  .unit { margin-left: 6px; color: var(--muted); font-size: 13px; }
  .badges-cell { text-align: right; }
  tr.open td { background: color-mix(in srgb, var(--accent) 8%, transparent); }
  tr.derived .value .big { color: var(--best); }
  tr.detail td { background: var(--panel-2); padding: 12px 14px; }
  tr.detail td > div { margin: 4px 0; }
  .derived-box { border-left: 3px solid var(--best); padding: 6px 10px; background: color-mix(in srgb, var(--best) 8%, transparent); border-radius: 4px; }
  .effects { display: grid; gap: 3px; margin-top: 8px; }

  .conf, .derived-badge { display: inline-block; font-size: 10px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; padding: 3px 7px; border-radius: 6px; border: 1px solid currentColor; white-space: nowrap; vertical-align: middle; margin-left: 4px; }
  .conf-high { color: var(--gain); }
  .conf-medium { color: var(--ref); }
  .conf-low { color: var(--loss); }
  .derived-badge { color: var(--best); }

  .unavailable { border-color: color-mix(in srgb, var(--loss) 45%, transparent); }
  .alts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
  .alt { min-height: 44px; padding: 8px 14px; font-weight: 600; border-radius: 10px; }
  .alt small { font-weight: 400; color: var(--best); }
  .more { margin-top: 8px; min-height: 44px; }

  /* compare */
  .tools { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; flex: 1 1 320px; justify-content: flex-end; }
  .session-pick { flex: 1 1 260px; max-width: 560px; }
  .session-pick .big-select { font-size: 14px; }
  .tool { min-height: 44px; }
  .context { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 6px 0 10px; }
  .ctx-val { font-size: 16px; font-weight: 700; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .note { margin: 4px 0; }
  .choose { margin: 10px 0; padding: 12px; border: 1px dashed var(--border); border-radius: 10px; display: grid; gap: 10px; }
  .choose p { margin: 0; }
  .unavail-inline { margin-top: 10px; }
  .against { margin-top: 12px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .summary-line { font-weight: 600; }
  .range-warn { margin: 10px 0; padding: 10px 12px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--loss) 50%, transparent); background: color-mix(in srgb, var(--loss) 9%, transparent); line-height: 1.45; }
  .diff-tools { display: flex; justify-content: flex-end; margin: 8px 0; }
  .diff-tools .seg { min-width: 280px; }
  .diff td { padding: 10px 8px; vertical-align: middle; font-size: 15px; }
  .diff .dlabel { font-weight: 600; }
  .diff .yours { color: var(--muted); }
  .diff .rec { font-weight: 700; white-space: nowrap; }
  .arrow-col { width: 36px; }
  .arrow { font-size: 22px; font-weight: 700; text-align: center; width: 36px; }
  .dir-higher, .dir-lower { color: var(--accent); }
  .dir-same { color: var(--gain); }
  .dir-unknown { color: var(--faint); }
  tr.diff-row td { border-bottom: none; }
  tr.explain td { padding: 0 8px 12px; font-size: 13px; color: var(--muted); line-height: 1.45; }
  tr.out td { background: color-mix(in srgb, var(--loss) 6%, transparent); }
  .mag { display: inline-block; margin-bottom: 2px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 3px 8px; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
  .mag-same { color: var(--gain); }
  .mag-small { color: var(--muted); }
  .mag-moderate { color: var(--ref); }
  .mag-large { color: var(--loss); }
  .mag-unknown { color: var(--faint); }
  .suggest { margin-top: 14px; padding: 12px 14px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--accent) 40%, transparent); background: color-mix(in srgb, var(--accent) 7%, transparent); }
  .suggest p { margin: 4px 0 10px; line-height: 1.45; font-size: 15px; }
  .suggest-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; justify-content: space-between; }
  .suggest-row button { min-height: 48px; padding: 8px 18px; }

  /* experiments */
  .exp { border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; background: var(--panel-2); display: grid; gap: 8px; margin-top: 10px; }
  .exp-running { border-color: color-mix(in srgb, var(--accent) 50%, transparent); }
  .exp-abandoned { opacity: 0.8; }
  .exp-head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .exp-title { font-size: 16px; }
  .hyp { margin: 0; line-height: 1.45; }
  .exp-actions { display: flex; gap: 8px; align-items: flex-end; flex-wrap: wrap; }
  .exp-actions button { min-height: 48px; padding: 8px 16px; }
  .after-pick { flex: 1 1 280px; }
  .after-pick .big-select { font-size: 14px; }
  .abandon { display: flex; gap: 8px; flex-wrap: wrap; flex: 1 1 100%; }
  .abandon input { flex: 1 1 220px; min-height: 48px; }
  .quiet { background: transparent; }
  .pill { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; padding: 4px 9px; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
  .st-proposed { color: var(--ref); }
  .st-running { color: var(--accent); }
  .st-concluded { color: var(--gain); }
  .st-abandoned { color: var(--faint); }
  .v-faster { color: var(--gain); }
  .v-slower { color: var(--loss); }
  .v-no_clear_difference { color: var(--muted); }
  .v-inconclusive { color: var(--faint); }
  .verdict { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .metrics td { font-size: 14px; }
  .check { line-height: 1.5; }
  .conclusion { margin: 0; padding: 10px 12px; border-radius: 8px; background: var(--panel); border: 1px solid var(--border); line-height: 1.5; }
  .legend-grid { display: grid; gap: 8px; }

  @media (max-width: 1000px) {
    .pickers { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-width: 900px) {
    .top { grid-template-columns: 1fr; }
  }
  @media (max-width: 600px) {
    .pickers { grid-template-columns: minmax(0, 1fr); }
    .seg button small { font-size: 10px; }
    .mag-col { display: none; }
    .diff td { font-size: 14px; padding: 8px 4px; }
    .label-cell { width: auto; }
    .rowbtn { font-size: 14px; }
    .big { font-size: 17px; }
    .diff-tools .seg { min-width: 0; width: 100%; }
  }
</style>
