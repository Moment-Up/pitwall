// Setup › Validation (lane validate, spec 12): live tests on the rig, with evidence. Used parked in the seat at about
// 70 cm, like the rig walkthrough: instructions large, glove-size actions. Drive is not changed.
//   #/setup/validation                       the checklist of the active run (or the empty state and Start)
//   #/setup/validation/reports               every run, newest first
//   #/setup/validation/reports/<run id>      one run's report
// Data: GET /api/validation/catalog (cached 1 min), /active (every 5 s while the checklist shows), the active run's
// compact state (every 2 s while visible, like Connect), its full detail only for the transcripts and the input check,
// /runs and /runs/{id}/report for Reports. Every mutation answers with the new Run, which replaces the cached one.
// The kit never changes a capability status; nothing here talks to the AI engineer.

import { Alert, Button, Skeleton } from "@heroui/react";
import { Segment } from "@heroui-pro/react";
import { useCallback, useMemo, useState, type Key, type ReactNode } from "react";
import { ScrollRow } from "../../components/ScrollRow";
import { useRadio } from "../../components/radio";
import { useActiveDriver, useDrivers } from "../../hooks/stores";
import { useApi } from "../../hooks/useApi";
import { cache } from "../../lib/cache";
import type { Driver } from "../../lib/drivers";
import {
  VALIDATION_KEYS,
  VALIDATION_POLL_MS,
  ValidationError,
  startBody,
  validationApi,
  validationErrorText,
  verdictBody,
  type Run,
} from "../../lib/endpoints/validation";
import { router } from "../../lib/router";
import { pokeValidationReporter } from "../../lib/validation/browser";
import { parseValidationParam, validationPath, type ValidationView } from "../../lib/validation/view";
import type { PageProps } from "../../routes";
import { useWide } from "./shared/useMediaQuery";
import { ChecklistView, type ChecklistActions } from "./validation/ChecklistView";
import { FinishSheet } from "./validation/FinishSheet";
import { PttSheet } from "./validation/PttTranscripts";
import { ReportDetail } from "./validation/ReportDetail";
import { ReportsView } from "./validation/ReportsView";
import { StartSheet } from "./validation/StartSheet";

const EMPTY_DRIVERS: Driver[] = [];
const CATALOG_MAX_AGE_MS = 60_000;
const ACTIVE_POLL_MS = 5_000;

const VIEWS: { id: ValidationView; label: string }[] = [
  { id: "checklist", label: "Checklist" },
  { id: "reports", label: "Reports" },
];

function Failed({ title, error, onRetry }: { title: string; error: unknown; onRetry: () => void }) {
  return (
    <Alert status="danger">
      <Alert.Indicator />
      <Alert.Content>
        <Alert.Title>{title}</Alert.Title>
        <Alert.Description>{validationErrorText(error)}</Alert.Description>
      </Alert.Content>
      <Button variant="secondary" className="min-h-11" onPress={onRetry}>
        Try again
      </Button>
    </Alert>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label={label}>
      <Skeleton className="h-20 rounded-3xl" />
      <div className="grid gap-4 md:grid-cols-[300px_minmax(0,1fr)]">
        <Skeleton className="h-[420px] rounded-3xl" />
        <Skeleton className="h-[420px] rounded-3xl" />
      </div>
    </div>
  );
}

/** Save text as a file (Download JSON). */
function saveFile(name: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function ValidationPage({ route }: PageProps) {
  const { view, runId } = parseValidationParam(route.param);
  const wide = useWide();
  const radioBar = useRadio((s) => s.phase === "live");
  const drivers = useDrivers((s) => s.drivers) ?? EMPTY_DRIVERS;
  const seated = useActiveDriver();
  const names = useMemo(() => new Map(drivers.map((d) => [d.id, d.name])), [drivers]);

  const catalog = useApi(VALIDATION_KEYS.catalog, validationApi.catalog, { maxAgeMs: CATALOG_MAX_AGE_MS });
  const active = useApi(view === "checklist" ? VALIDATION_KEYS.active : null, validationApi.active, { intervalMs: ACTIVE_POLL_MS, maxAgeMs: 0 });
  const activeId = active.data?.run?.status === "active" ? active.data.run.id : null;
  const run = useApi(activeId && view === "checklist" ? VALIDATION_KEYS.run(activeId) : null, () => validationApi.run(activeId!), {
    intervalMs: VALIDATION_POLL_MS,
    maxAgeMs: 0,
  });
  const runs = useApi(view === "reports" && !runId ? VALIDATION_KEYS.runs : null, validationApi.runs, { maxAgeMs: 0 });
  const report = useApi(runId ? VALIDATION_KEYS.report(runId) : null, () => validationApi.report(runId!), { maxAgeMs: 0 });

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [startOpen, setStartOpen] = useState(false);
  const [finishOpen, setFinishOpen] = useState(false);
  const [pttOpen, setPttOpen] = useState(false);
  const [inputOpen, setInputOpen] = useState(false);

  const current = run.data && run.data.id === activeId ? run.data : null;
  // The full detail (every evidence record, up to ~2 MB) only while the transcripts or an input check are open.
  const needFull = !!current && (pttOpen || inputOpen);
  const full = useApi(needFull && current ? VALIDATION_KEYS.full(current.id) : null, () => validationApi.run(current!.id, "full"), {
    maxAgeMs: 0,
  });

  /** Run a mutation: the answer replaces the cached run; the lists and the reporter catch up. */
  const act = useCallback(async (fn: () => Promise<Run>): Promise<Run | null> => {
    setBusy(true);
    setActionError(null);
    try {
      const r = await fn();
      cache.set(VALIDATION_KEYS.run(r.id), r);
      cache.invalidate(VALIDATION_KEYS.active);
      cache.invalidate(VALIDATION_KEYS.runs);
      cache.invalidate(VALIDATION_KEYS.full(r.id));
      pokeValidationReporter();
      return r;
    } catch (e) {
      setActionError(validationErrorText(e));
      if (e instanceof ValidationError && (e.status === 404 || e.status === 409)) cache.invalidate(VALIDATION_KEYS.active);
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const go = (v: ValidationView, id: string | null = null) => router.navigate(validationPath(v, id));
  const id = current?.id ?? null;

  const actions: ChecklistActions = {
    openStart: () => {
      setActionError(null);
      setStartOpen(true);
    },
    openFinish: () => {
      setActionError(null);
      setFinishOpen(true);
    },
    pick: (item) => {
      if (id && item !== current?.current_item) void act(() => validationApi.setCurrent(id, item));
    },
    next: () => {
      if (id) void act(() => validationApi.next(id));
    },
    skip: (item) => {
      if (!id) return;
      void (async () => {
        const r = await act(() => validationApi.skip(id, item, null));
        if (r && r.current_item === item) await act(() => validationApi.next(id));
      })();
    },
    verdict: (item, v, d) => {
      if (id) void act(() => validationApi.verdict(id, item, verdictBody(v, d.notes, d.attestations, d.extra)));
    },
    openTranscripts: () => setPttOpen(true),
    inputPhase: async (item, phase, rot) => {
      if (!id) return false;
      try {
        const r = await validationApi.inputCheck(id, item, { phase, rotation_deg: rot });
        cache.set(VALIDATION_KEYS.run(r.id), r);
        return true;
      } catch (e) {
        setActionError(validationErrorText(e));
        return false;
      }
    },
    inputDone: () => {
      if (id) cache.invalidate(VALIDATION_KEYS.full(id));
    },
    inputOpen: setInputOpen,
    showReports: () => go("reports"),
    openDrive: () => router.navigate("/drive/coach"),
  };

  const segment = (
    <ScrollRow className="-mx-4 px-4 pb-1 md:mx-0 md:px-0">
      <Segment aria-label="Validation views" size="lg" selectedKey={view} onSelectionChange={(k: Key) => go(String(k) as ValidationView)} className="w-max">
        {VIEWS.map((v) => (
          <Segment.Item key={v.id} id={v.id} className="h-11 px-4">
            {v.label}
          </Segment.Item>
        ))}
      </Segment>
    </ScrollRow>
  );
  const frame = (body: ReactNode) => (
    <div className="grid min-w-0 gap-4 [&>*]:min-w-0">
      {segment}
      {body}
    </div>
  );

  // ---------------------------------------------------------------------------------------------- reports
  if (view === "reports") {
    if (runId) {
      if (!report.data) {
        return frame(
          report.error ? <Failed title="The report did not load" error={report.error} onRetry={() => void report.refresh()} /> : <Loading label="Loading the report" />,
        );
      }
      return frame(
        <ReportDetail
          report={report.data}
          names={names}
          error={actionError}
          onBack={() => go("reports")}
          onOpenMarkdown={(redact) => {
            // Opened synchronously (a popup blocker allows it), then filled with the report fetched with this tab's
            // credentials, as plain text so every browser shows it instead of downloading it.
            const w = window.open("", "_blank");
            validationApi
              .reportMarkdown(runId, redact)
              .then((text) => {
                const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
                if (w) w.location.href = url;
                else saveFile(`pitwall-validation-${runId}.md`, text, "text/markdown");
                setTimeout(() => URL.revokeObjectURL(url), 60_000);
              })
              .catch((e: unknown) => {
                w?.close();
                setActionError(validationErrorText(e));
              });
          }}
          onDownloadJson={(redact) => {
            validationApi
              .report(runId, redact)
              .then((r) => saveFile(`pitwall-validation-${runId}.json`, JSON.stringify(r, null, 2), "application/json"))
              .catch((e: unknown) => setActionError(validationErrorText(e)));
          }}
        />,
      );
    }
    return frame(
      <ReportsView
        runs={runs.data}
        error={runs.error ? validationErrorText(runs.error) : null}
        onOpen={(rid) => go("reports", rid)}
        onRetry={() => void runs.refresh()}
      />,
    );
  }

  // ---------------------------------------------------------------------------------------------- checklist
  if (!catalog.data || !active.data) {
    const err = catalog.error ?? active.error;
    return frame(
      err ? (
        <Failed
          title="The validation kit did not load"
          error={err}
          onRetry={() => {
            void catalog.refresh();
            void active.refresh();
          }}
        />
      ) : (
        <Loading label="Loading the validation kit" />
      ),
    );
  }
  if (activeId && !current) {
    return frame(run.error ? <Failed title="The run did not load" error={run.error} onRetry={() => void run.refresh()} /> : <Loading label="Loading the run" />);
  }

  const refreshError = (current ? run.error : active.error) ?? null;
  return frame(
    <>
      <ChecklistView
        catalog={catalog.data}
        run={current}
        driver={seated}
        driverId={seated?.id ?? null}
        names={names}
        busy={busy}
        wide={wide}
        radioBar={radioBar}
        actionError={startOpen || finishOpen ? null : actionError}
        refreshError={refreshError ? validationErrorText(refreshError) : null}
        inputRecords={full.data?.evidence?.input_phases}
        actions={actions}
      />
      <StartSheet
        isOpen={startOpen}
        catalog={catalog.data}
        wide={wide}
        busy={busy}
        error={startOpen ? actionError : null}
        onClose={() => setStartOpen(false)}
        onStart={(items, label, prompts) => {
          void (async () => {
            const r = await act(() => validationApi.start(startBody(items, label, prompts)));
            if (r) setStartOpen(false);
          })();
        }}
      />
      {current ? (
        <>
          <FinishSheet
            isOpen={finishOpen}
            run={current}
            wide={wide}
            busy={busy}
            error={finishOpen ? actionError : null}
            onClose={() => setFinishOpen(false)}
            onFinish={(notes) => {
              void (async () => {
                const r = await act(() => validationApi.finish(current.id, notes));
                if (r) {
                  setFinishOpen(false);
                  go("reports", r.id);
                }
              })();
            }}
            onAbort={() => {
              void (async () => {
                const r = await act(() => validationApi.abort(current.id));
                if (r) {
                  setFinishOpen(false);
                  go("reports", r.id);
                }
              })();
            }}
          />
          <PttSheet
            isOpen={pttOpen}
            wide={wide}
            records={full.data?.evidence?.ptt}
            error={full.error ? validationErrorText(full.error) : null}
            busy={busy}
            onClose={() => setPttOpen(false)}
            onMark={(record, heard) => {
              // The answer invalidates the full detail, which reloads while the sheet is open.
              void act(() => validationApi.markPtt(current.id, record, heard));
            }}
          />
        </>
      ) : null}
    </>,
  );
}
