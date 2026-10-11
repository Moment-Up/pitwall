// "Lap 7 analysed · 2 coaching points" with an Open action (spec 2.6), top right, only when not on track: Drive never
// shows toasts on track (App also unmounts the toast region then). A lap analysed while on track is not queued for
// later - it would be old news by the time the car stops.

import { toast } from "@heroui/react";
import { useEffect, useRef } from "react";
import { live } from "../../lib/live";
import { router, sessionPath } from "../../lib/router";
import { lapToastEvidence, lapToastTitle } from "./lapToast";

export function useLapToast(onTrack: boolean): void {
  const onTrackRef = useRef(onTrack);
  useEffect(() => {
    onTrackRef.current = onTrack;
  }, [onTrack]);

  useEffect(() => {
    let last = live.get().lastLapEvent;
    return live.subscribe(() => {
      const s = live.get();
      if (s.lastLapEvent === last) return;
      last = s.lastLapEvent;
      if (!last || onTrackRef.current) return;
      const sessionId = s.snap?.session_id ?? null;
      toast(lapToastTitle(last), {
        description: lapToastEvidence(s.snap?.connection) ?? undefined,
        actionProps: sessionId
          ? { children: "Open", onPress: () => router.navigate(sessionPath(sessionId)) }
          : undefined,
      });
    });
  }, []);
}
