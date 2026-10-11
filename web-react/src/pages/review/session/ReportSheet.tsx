// Session report (spec 6.2): the existing markdown report (core/report.py, GET /api/sessions/{id}/report) in a Pro
// Sheet (right on iPad and Mac, bottom on phones, spec 3.4) rendered by Pro Markdown. Loaded when opened.

import { Button, Skeleton } from "@heroui/react";
import { Sheet } from "@heroui-pro/react";
import { LazyMarkdown } from "./LazyMarkdown";
import { useApi } from "../../../hooks/useApi";
import { reviewApi, reviewKeys } from "../../../lib/endpoints/review";
import { useWideScreen } from "../useMedia";

export function ReportSheet({
  sessionId,
  title,
  isOpen,
  onClose,
}: {
  sessionId: string;
  title: string;
  isOpen: boolean;
  onClose: () => void;
}) {
  const wide = useWideScreen();
  const { data, error, refresh } = useApi(isOpen ? reviewKeys.report(sessionId) : null, () => reviewApi.report(sessionId));

  return (
    <Sheet isOpen={isOpen} onOpenChange={(o) => !o && onClose()} placement={wide ? "right" : "bottom"}>
      <Sheet.Backdrop>
        <Sheet.Content className={wide ? "w-[min(720px,96vw)]" : "max-h-[90dvh]"}>
          <Sheet.Dialog aria-label={`Session report: ${title}`}>
            {!wide && <Sheet.Handle />}
            <Sheet.Header className="flex-row items-center justify-between gap-3 pt-5">
              <div className="grid gap-0.5">
                <Sheet.Heading className="text-xl">Session report</Sheet.Heading>
                <p className="m-0 text-sm text-muted">{title}</p>
              </div>
              <Sheet.CloseTrigger />
            </Sheet.Header>
            <Sheet.Body className="overflow-y-auto pb-8">
              {data ? (
                <LazyMarkdown className="pw-report text-[15px] leading-relaxed" text={data.markdown} />
              ) : error ? (
                <div className="grid justify-items-start gap-3">
                  <p role="alert" className="m-0 text-sm text-bad">
                    The report could not be built: {error.message}
                  </p>
                  <Button variant="secondary" className="min-h-11" onPress={() => void refresh()}>
                    Try again
                  </Button>
                </div>
              ) : (
                <div aria-busy="true" aria-label="Loading the report" className="grid gap-3">
                  <Skeleton className="h-6 w-1/2 rounded-lg" />
                  <Skeleton className="h-4 w-3/4 rounded-lg" />
                  <Skeleton className="h-40 w-full rounded-2xl" />
                </div>
              )}
            </Sheet.Body>
          </Sheet.Dialog>
        </Sheet.Content>
      </Sheet.Backdrop>
    </Sheet>
  );
}
