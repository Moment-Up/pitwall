// The rest of Setup › Connect (spec 7.1): the telemetry status at the top, live senders (Pro ListView, a Live / Stale
// chip per device), radio devices, and "Open Pitwall on another device" (CopyFields for the Tailscale HTTPS URL and
// the LAN token URL, with why the radio needs HTTPS). Behaviour reference: web/src/views/ConnectView.svelte.

import { Alert, Card, Chip } from "@heroui/react";
import { ListView } from "@heroui-pro/react";
import { BADGE_CLASS, StatusDot } from "../../../components/StatusPill";
import { CopyField, EvidenceChips } from "../../../components/ui";
import type { ConnectInfo } from "../../../lib/endpoints/connect";
import { grouped } from "../../../lib/format";
import type { LiveBadge } from "../../../lib/live";
import {
  ago,
  captureName,
  decodedPackets,
  lastDecodeError,
  senderRows,
  statusDetail,
  statusLine,
} from "../../../lib/setup/connect";

const BADGE: Record<ConnectInfo["telemetry"]["status"], LiveBadge> = { live: "LIVE", stale: "STALE", no_data: "IDLE" };
const BADGE_WORD: Record<LiveBadge, string> = { LIVE: "Live", STALE: "Stale", IDLE: "No data", OFFLINE: "Offline" };

export function TelemetryStatusCard({ info }: { info: ConnectInfo }) {
  const t = info.telemetry;
  const badge = BADGE[t.status];
  const detail = statusDetail(info);
  return (
    <Card className="gap-3 p-5" aria-label="Telemetry status">
      <div className="flex flex-wrap items-center gap-4">
        <StatusDot badge={badge} className={`size-4 ${badge === "LIVE" ? "text-status-live" : badge === "STALE" ? "text-status-stale" : "text-status-idle"}`} />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <p className="m-0 text-lg leading-snug font-semibold">{statusLine(info)}</p>
          {detail ? <p className="m-0 text-sm text-muted">{detail}</p> : null}
        </div>
        <EvidenceChips synthetic={t.synthetic} source={t.source ?? null} size="md" />
        <Chip size="md" variant="soft" className={BADGE_CLASS[badge]}>
          <Chip.Label>{BADGE_WORD[badge]}</Chip.Label>
        </Chip>
      </div>
      {t.hint ? (
        <Alert status="warning">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Title>Check the game's telemetry settings</Alert.Title>
            <Alert.Description>{t.hint}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}
    </Card>
  );
}

export function LiveSendersCard({ info }: { info: ConnectInfo }) {
  const rows = senderRows(info);
  const t = info.telemetry;
  const err = lastDecodeError(t);
  const capture = captureName(info.udp.capture);
  return (
    <Card className="gap-4 p-5">
      <Card.Header>
        <Card.Title className="text-base font-semibold">Live senders</Card.Title>
        <Card.Description className="text-sm text-muted">Devices sending telemetry to this Mac</Card.Description>
      </Card.Header>
      <ListView
        aria-label="Live senders"
        items={rows}
        className="rounded-2xl"
        renderEmptyState={() => <p className="m-0 px-4 py-3 text-sm text-muted">No device has sent telemetry since Pitwall started.</p>}
      >
        {(r) => (
          <ListView.Item id={r.id} textValue={r.ip} className="min-h-14">
            <ListView.ItemContent>
              {/* Stacked, so the address never truncates and the details wrap in a narrow column (iPad landscape). */}
              <div className="grid min-w-0">
                <ListView.Title className="font-mono text-sm">{r.ip}</ListView.Title>
                <ListView.Description className="text-xs whitespace-normal text-muted">
                  {r.input} · {grouped(r.packets)} packets · {ago(r.lastSeenS)}
                </ListView.Description>
              </div>
            </ListView.ItemContent>
            <ListView.ItemAction className="flex items-center gap-3">
              <span className="pw-num text-lg">{Math.round(r.packetsPerS)}/s</span>
              <Chip size="sm" variant="soft" className={BADGE_CLASS[r.live ? "LIVE" : "STALE"]}>
                <Chip.Label>{r.live ? "Live" : "Stale"}</Chip.Label>
              </Chip>
            </ListView.ItemAction>
          </ListView.Item>
        )}
      </ListView>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-muted">Decoded / rejected</dt>
        <dd className="m-0">
          <span className="pw-num text-base">{grouped(decodedPackets(t))}</span> /{" "}
          <span className={`pw-num text-base ${t.rejected > 0 ? "text-danger" : ""}`}>{grouped(t.rejected)}</span>
          {t.unrecognised ? <span className="text-muted"> · {grouped(t.unrecognised)} unrecognised</span> : null}
        </dd>
        {err ? (
          <>
            <dt className="text-muted">Last error</dt>
            <dd className="m-0 text-danger">{err}</dd>
          </>
        ) : null}
        <dt className="text-muted">Recording</dt>
        <dd className="m-0 font-mono text-xs break-all text-muted">{capture ?? "starts with the first packet"}</dd>
      </dl>
    </Card>
  );
}

export function RadioDevicesCard({ info }: { info: ConnectInfo }) {
  return (
    <Card className="gap-3 p-5">
      <Card.Header>
        <Card.Title className="text-base font-semibold">Radio and dashboards</Card.Title>
      </Card.Header>
      {!info.radio_enabled ? (
        <p className="m-0 text-sm text-muted">Voice radio is switched off on this Mac.</p>
      ) : info.radio.length ? (
        <ul className="m-0 grid list-none gap-2 p-0">
          {info.radio.map((r, i) => (
            <li key={`${r.name}-${i}`} className="flex min-h-11 flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-secondary px-3 py-2">
              <span className="font-medium">{r.name}</span>
              <span className="text-sm text-muted">
                {r.mic_live ? "Mic live" : "Mic off"} · {r.device_tts ? "device voice" : "Mac voice"}
                {r.dropped ? ` · ${r.dropped} dropped` : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 text-sm text-muted">No radio connected. On the iPad open Drive › Radio and tap Go live.</p>
      )}
      <p className="m-0 text-sm text-muted">
        Dashboards open: <span className="pw-num text-base text-foreground">{info.dashboards}</span>
      </p>
    </Card>
  );
}

export function OtherDevicesCard({ info }: { info: ConnectInfo }) {
  return (
    <Card className="gap-4 p-5">
      <Card.Header>
        <Card.Title className="text-base font-semibold">Open Pitwall on another device</Card.Title>
        <Card.Description className="text-sm text-muted">
          The radio's microphone only works over HTTPS, so open the Tailscale address on the iPad and the phone.
        </Card.Description>
      </Card.Header>
      <div className="grid gap-3">
        {info.urls.tailscale_https ? (
          <CopyField value={info.urls.tailscale_https} label="iPad or iPhone (Tailscale, HTTPS, radio works)" />
        ) : (
          <p className="m-0 rounded-xl bg-surface-secondary px-3 py-2 text-sm text-muted">
            No Tailscale HTTPS address: the radio's microphone will not work from other devices until Tailscale serve is set
            up (docs/radio-setup.md).
          </p>
        )}
        <CopyField value={info.urls.lan_with_token} label="Any browser on your network (no microphone over plain HTTP)" />
      </div>
      <p className="m-0 text-xs text-faint">
        This Mac: {info.mac.hostname}
        {info.mac.lan_addresses.length ? ` · ${info.mac.lan_addresses.map((a) => `${a.ip} (${a.interface})`).join(", ")}` : ""}
      </p>
    </Card>
  );
}
