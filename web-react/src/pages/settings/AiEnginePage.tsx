// Settings › AI engineer (spec 8; port of web/src/views/SettingsView.svelte): which model explains the facts (Off /
// Local / Cloud), its server, keys (never shown), the privacy acknowledgement, a daily budget, Test, usage today and
// the exact last request. Coaching never depends on it: cues and corner analysis are deterministic and the engineer
// answers from the facts alone whenever no model is available (CLAUDE.md, P10).
//
// The server (src/pitwall/api/routes_llm.py) validates everything. The page keeps a draft (ai/draft.ts) so switching
// between Local and Cloud never loses what was typed for the other side; Save sends it, Revert drops it.

import { Alert, Button, Card, Skeleton } from "@heroui/react";
import { CellSwitch, Segment } from "@heroui-pro/react";
import { useCallback, useEffect, useMemo, useRef, useState, type Key } from "react";
import { useApi } from "../../hooks/useApi";
import { cache } from "../../lib/cache";
import { EndpointError, SETTINGS_KEYS, llmApi, messageOf, type Overview } from "../../lib/endpoints/settings";
import type { PageProps } from "../../routes";
import { BudgetFields, PrivacyNotice } from "./ai/CloudExtras";
import {
  MODES,
  buildConfig,
  cloudInUse,
  configKey,
  draftFromOverview,
  otherSide,
  pricedModels,
  primarySide,
  saveState,
  setMode,
  showCloud,
  showLocal,
  type AiDraft,
  type Mode,
} from "./ai/draft";
import { ProviderEditor } from "./ai/ProviderEditor";
import { LastRequestCard, ProviderStatus, TestCard, UsageCard } from "./ai/StatusCards";

export function AiEnginePage(_props: PageProps) {
  const [ov, setOv] = useState<Overview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<AiDraft | null>(null);
  const [savedKey, setSavedKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedNote, setSavedNote] = useState<string | null>(null);
  const usage = useApi(SETTINGS_KEYS.llmUsage, llmApi.usage);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true; // StrictMode mounts twice: the first cleanup must not leave the page "unmounted"
    return () => {
      alive.current = false;
    };
  }, []);

  /** Take a fresh overview. `resetDraft` false keeps what is being typed (after a key change or a 409). */
  const apply = useCallback((o: Overview, resetDraft: boolean) => {
    setOv((prev) => ({ ...o, health: o.health ?? prev?.health }));
    if (resetDraft) {
      const d = draftFromOverview(o);
      setDraft(d);
      setSavedKey(configKey(o, d));
    }
  }, []);

  /** Health is a live check of each provider (slow when one is down): fetched after the page is on screen. */
  const loadHealth = useCallback(async () => {
    try {
      const h = await llmApi.overview(true);
      if (alive.current) setOv((prev) => (prev ? { ...prev, health: h.health } : prev));
    } catch {
      /* health is optional */
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const o = await llmApi.overview();
      if (!alive.current) return;
      apply(o, true);
      setLoadError(null);
    } catch (e) {
      if (alive.current) setLoadError(messageOf(e));
      return;
    }
    void loadHealth();
  }, [apply, loadHealth]);

  useEffect(() => {
    void load();
  }, [load]);

  const presets = ov?.presets ?? [];
  const dirty = ov != null && draft != null && configKey(ov, draft) !== savedKey;
  const needsAck = draft != null && !draft.ack && cloudInUse(presets, draft);
  const state = saveState({ error: saveError, needsAck, savedNote, dirty });
  const priced = useMemo(() => (draft ? pricedModels(presets, draft) : []), [presets, draft]);

  const patch = (p: Partial<AiDraft>) => {
    setDraft((d) => (d ? { ...d, ...p } : d));
    setSavedNote(null);
  };

  async function save() {
    if (!ov || !draft || saving) return;
    setSaving(true);
    setSaveError(null);
    setSavedNote(null);
    try {
      const o = await llmApi.saveConfig(buildConfig(ov, draft));
      apply(o, true);
      setSavedNote("Saved: the engineer uses the new settings now.");
      cache.invalidate(SETTINGS_KEYS.llmUsage);
      cache.invalidate(SETTINGS_KEYS.llmHealth);
      void loadHealth();
    } catch (e) {
      setSaveError(messageOf(e));
      if (e instanceof EndpointError && e.status === 409) {
        // The privacy notice changed since this page loaded: show the new text (keeping the draft) and ask for a
        // fresh tick before cloud settings can be saved.
        setDraft((d) => (d ? { ...d, ack: false } : d));
        try {
          apply(await llmApi.overview(), false);
        } catch {
          /* the error above is already shown */
        }
      }
    } finally {
      setSaving(false);
    }
  }

  function revert() {
    if (ov) apply(ov, true);
    setSaveError(null);
    setSavedNote(null);
  }

  const reloadKeys = async () => {
    try {
      apply(await llmApi.overview(), false);
    } catch {
      /* the key's own note says what happened */
    }
  };

  if (!ov || !draft) {
    return (
      <div className="grid grid-cols-1 gap-4">
        {loadError ? (
          <Alert status="danger">
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Title>Couldn&apos;t load the AI settings</Alert.Title>
              <Alert.Description>{loadError}</Alert.Description>
            </Alert.Content>
            <Button className="min-h-11" size="lg" variant="secondary" onPress={() => void load()}>
              Retry
            </Button>
          </Alert>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2" aria-busy="true" aria-label="Loading the AI settings">
            <Skeleton className="h-64 rounded-3xl" />
            <Skeleton className="h-64 rounded-3xl" />
          </div>
        )}
      </div>
    );
  }

  const primary = primarySide(draft);
  const other = otherSide(draft);

  return (
    <div className="grid grid-cols-1 gap-4">
      <p className="m-0 max-w-[75ch] text-muted">
        Coaching cues and corner analysis never use a language model. The AI engineer only explains facts Pitwall has
        already checked, and answers straight from those facts whenever no model is available.
      </p>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="grid min-w-0 grid-cols-1 gap-4">
          <Card>
            <Card.Header>
              <Card.Title className="text-base font-semibold">Engine</Card.Title>
            </Card.Header>
            <Card.Content className="grid grid-cols-1 gap-4">
              {ov.status.error && <p className="m-0 text-sm text-warning">{ov.status.error}</p>}
              <Segment
                aria-label="AI engineer model"
                size="lg"
                className="w-full"
                selectedKey={draft.mode}
                onSelectionChange={(k: Key) => {
                  setDraft((d) => (d ? setMode(d, String(k) as Mode) : d));
                  setSavedNote(null);
                }}
              >
                {MODES.map((m) => (
                  <Segment.Item key={m.id} id={m.id} className="h-auto min-h-14 min-w-0 flex-1 flex-col gap-0.5 py-2">
                    <span className="font-semibold">{m.label}</span>
                    <span className="hidden text-xs font-normal text-muted sm:block">{m.hint}</span>
                  </Segment.Item>
                ))}
              </Segment>
              <p className="m-0 text-sm text-muted sm:hidden">{MODES.find((m) => m.id === draft.mode)?.hint}</p>
              <ProviderStatus ov={ov} />
              <p className="m-0 text-sm text-muted">
                <span className="font-medium text-foreground">Privacy:</span> a model gets your question and a fact sheet
                from the session, never raw telemetry or audio.{" "}
                {cloudInUse(presets, draft)
                  ? "With a cloud model it goes to the provider you pick (see the notice below)."
                  : "With Local or Off nothing goes to the internet."}
              </p>
            </Card.Content>
          </Card>

          {showCloud(draft) && (
            <Card>
              <Card.Header>
                <Card.Title className="text-base font-semibold">Cloud model{draft.mode === "local" ? " (fallback)" : ""}</Card.Title>
              </Card.Header>
              <Card.Content className="grid grid-cols-1 gap-5">
                <PrivacyNotice ov={ov} draft={draft} onChange={patch} />
                {draft.ack && (
                  <>
                    <ProviderEditor
                      ov={ov}
                      side="cloud"
                      draft={draft.cloud}
                      onChange={(c) => patch({ cloud: c })}
                      onKeysChanged={reloadKeys}
                    />
                    <BudgetFields draft={draft} priced={priced} onChange={patch} />
                  </>
                )}
              </Card.Content>
            </Card>
          )}

          {showLocal(draft) && (
            <Card>
              <Card.Header>
                <Card.Title className="text-base font-semibold">Local model{draft.mode === "cloud" ? " (fallback)" : ""}</Card.Title>
              </Card.Header>
              <Card.Content>
                <ProviderEditor
                  ov={ov}
                  side="local"
                  draft={draft.local}
                  onChange={(l) => patch({ local: l })}
                  onKeysChanged={reloadKeys}
                />
              </Card.Content>
            </Card>
          )}

          {draft.mode !== "off" && (
            <CellSwitch isSelected={draft.useFallback} onChange={(v) => patch({ useFallback: v })}>
              <CellSwitch.Trigger className="h-auto min-h-16 rounded-3xl py-3">
                <span className="grid min-w-0 flex-1 gap-0.5">
                  <CellSwitch.Label className="whitespace-normal">Fallback</CellSwitch.Label>
                  <span className="text-sm whitespace-normal text-muted">
                    If the {primary} model is unavailable{primary === "cloud" ? " or over budget" : ""}, try the {other}{" "}
                    model before answering from the facts alone.
                  </span>
                </span>
                <CellSwitch.Control />
              </CellSwitch.Trigger>
            </CellSwitch>
          )}

          <div
            className={`sticky bottom-3 z-10 flex flex-wrap items-center gap-3 rounded-3xl border bg-overlay px-4 py-3 shadow-overlay ${
              dirty ? "border-accent" : "border-transparent"
            }`}
            role="region"
            aria-label="Save AI settings"
          >
            <span role="status" className="min-w-0 flex-1 text-sm">
              {state.kind === "error" ? (
                <span className="text-bad">{state.text}</span>
              ) : state.kind === "needs-ack" ? (
                <span className="text-warning">
                  This setup sends data off this network: tick the privacy acknowledgement under Cloud model first.
                </span>
              ) : state.kind === "saved" ? (
                <span className="text-success">{state.text}</span>
              ) : state.kind === "dirty" ? (
                <span className="text-muted">Unsaved changes</span>
              ) : (
                <span className="text-faint">All changes saved</span>
              )}
            </span>
            <Button className="min-h-11" size="lg" variant="secondary" isDisabled={!dirty || saving} onPress={revert}>
              Revert
            </Button>
            <Button className="min-h-11" size="lg" variant="primary" isDisabled={!dirty || needsAck} isPending={saving} onPress={() => void save()}>
              Save
            </Button>
          </div>
        </div>

        <div className="grid min-w-0 grid-cols-1 gap-4">
          <TestCard ov={ov} dirty={dirty} onTested={() => cache.invalidate(SETTINGS_KEYS.llmUsage)} />
          <UsageCard usage={usage.data} error={usage.error} />
          <LastRequestCard />
        </div>
      </div>
    </div>
  );
}
