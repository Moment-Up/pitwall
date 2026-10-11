// The no-telemetry card (design spec 4.7 #2, 4.9; mockup bigCard "nodata"): spans the hero, coach and delta areas
// while no packet has arrived. Pro EmptyState + a vertical Pro Stepper whose values come from GET /api/connect
// (polled every 2 s while the card is on screen, spec 12.3), and two ways on:
//
//   Waiting for telemetry                                   [ Open Setup › Connect ]     64 px, primary
//   No packet has arrived yet. Check these three things.    [ Try a demo replay (synthetic) ]
//   ① Turn on UDP telemetry in the game                      The demo is labelled SYNTHETIC on every screen.
//   ② IP 192.168.1.20 · port 20777
//   ③ Drive out of the garage · Last sender seen: none
//
// The demo writes the synthetic coaching demo (POST /api/simulate, as Settings › System does) and replays it at
// real time (POST /api/replay); it is SYNTHETIC everywhere and never pollutes real track models.

import { EmptyState, Stepper } from "@heroui-pro/react";
import { Button, Card } from "@heroui/react";
import { useState } from "react";
import { EvidenceChips } from "../../../components/ui";
import { useApi } from "../../../hooks/useApi";
import { api } from "../../../lib/api";
import { authFetch } from "../../../lib/auth";
import { router } from "../../../lib/router";
import { noTelemetryView, type ConnectInfo } from "./view";

/** GET /api/connect (shared cache key with Setup › Connect). */
export async function fetchConnect(): Promise<ConnectInfo> {
  const r = await authFetch("/api/connect");
  if (!r.ok) throw new Error(`${r.status}: ${r.statusText}`);
  return (await r.json()) as ConnectInfo;
}

/** /api/connect while the no-telemetry card or the status slot needs it (one request every 2 s, shared). */
export function useConnectInfo(enabled: boolean): ConnectInfo | undefined {
  return useApi("connect", fetchConnect, { intervalMs: 2000, enabled }).data;
}

type DemoState = { kind: "idle" } | { kind: "starting" } | { kind: "running"; file: string } | { kind: "error"; message: string };

function DemoButton() {
  const [demo, setDemo] = useState<DemoState>({ kind: "idle" });
  async function start() {
    setDemo({ kind: "starting" });
    try {
      const r = (await api.simulate("coaching-demo")) as { path?: unknown };
      const path = typeof r.path === "string" ? r.path : null;
      if (!path) throw new Error("the demo capture was not written");
      await api.replay(path, 1);
      setDemo({ kind: "running", file: path.slice(path.lastIndexOf("/") + 1) });
    } catch (e) {
      setDemo({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }
  return (
    <>
      <Button
        variant="tertiary"
        size="lg"
        className="pwc-xl"
        isPending={demo.kind === "starting"}
        isDisabled={demo.kind === "running"}
        onPress={() => void start()}
      >
        Try a demo replay (synthetic)
      </Button>
      <span className="flex flex-wrap items-center gap-2 text-sm text-muted" role="status">
        {demo.kind === "running" ? (
          <>Demo started ({demo.file}). Every screen labels it</>
        ) : demo.kind === "error" ? (
          <span className="text-bad">The demo could not start: {demo.message}</span>
        ) : (
          <>The demo is labelled</>
        )}
        {demo.kind !== "error" && <EvidenceChips synthetic size="sm" />}
        {demo.kind === "idle" || demo.kind === "starting" ? <>on every screen.</> : null}
      </span>
    </>
  );
}

export function NoTelemetryCard() {
  const view = noTelemetryView(useConnectInfo(true));
  return (
    <Card className="pwc-nodata pwc-span3">
      <EmptyState size="lg">
        <EmptyState.Header>
          <EmptyState.Title>Waiting for telemetry</EmptyState.Title>
          <EmptyState.Description>No packet has arrived yet. Check these three things.</EmptyState.Description>
        </EmptyState.Header>
        <EmptyState.Content>
          <Stepper orientation="vertical" size="lg" currentStep={view.current}>
            {view.steps.map((s) => (
              <Stepper.Step key={s.title}>
                <Stepper.Indicator />
                <Stepper.Content>
                  <Stepper.Title>
                    {s.mono ? <span className="font-[family-name:var(--pw-font-mono)]">{s.title}</span> : s.title}
                  </Stepper.Title>
                  <Stepper.Description>{s.description}</Stepper.Description>
                </Stepper.Content>
                <Stepper.Separator />
              </Stepper.Step>
            ))}
          </Stepper>
          {view.hint && <p className="m-0 text-[15px] text-warning">{view.hint}</p>}
        </EmptyState.Content>
      </EmptyState>
      <div className="pwc-nodata__actions">
        <Button variant="primary" size="lg" className="pwc-glove" onPress={() => router.navigate("/setup/connect")}>
          Open Setup › Connect
        </Button>
        <DemoButton />
      </div>
    </Card>
  );
}
