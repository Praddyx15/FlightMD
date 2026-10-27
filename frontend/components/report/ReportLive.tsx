"use client";

import { useEffect } from "react";
import { Clock, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useReport, type ReportState } from "@/lib/useReport";
import { useErrorText } from "@/lib/errors";
import { fmtDuration } from "@/lib/format";
import { UploadProgress } from "@/components/upload/UploadProgress";
import { ReportDone } from "./ReportDone";
import { FailedProblem, Problem } from "./Problem";

function Waiting({ state }: { state: Extract<ReportState, { phase: "queued" | "processing" }> }) {
  const t = useTranslations("report");
  return (
    <div className="mx-auto max-w-xl px-4 py-20">
      <h1 className="mb-1 flex items-center gap-2 text-value font-semibold">
        <Loader2 aria-hidden className="h-5 w-5 animate-spin text-accent reduce-motion:animate-none" />
        {t("analysing")}
      </h1>
      <p className="mb-4 text-sm text-fg-muted" aria-live="polite">
        {state.phase === "queued" ? t("queued") : state.message || t("working")}
      </p>
      <UploadProgress progress={state.progress} label={t("analysis")} />
      <p className="mt-4 text-xs text-fg-muted">
        {state.eta !== null ? t("eta", { eta: fmtDuration(state.eta) }) : t("usually")}
      </p>
    </div>
  );
}

// Client island for a report that isn't finished yet when the page is rendered.
export function ReportLive({ id }: { id: string }) {
  const t = useTranslations("report");
  const errText = useErrorText();
  const { state, retry } = useReport(id);

  useEffect(() => {
    if (state.phase === "done") document.title = `${state.report.file_name} · FlightMD`;
  }, [state]);

  switch (state.phase) {
    case "queued":
    case "processing":
      return <Waiting state={state} />;
    case "expired":
      return (
        <Problem title={t("expiredTitle")}>
          <p className="flex items-center justify-center gap-1">
            <Clock aria-hidden className="h-4 w-4" />
            {t("expiredBody")}
          </p>
        </Problem>
      );
    case "failed":
      return <FailedProblem error={state.error} />;
    case "error":
      return <Problem title={t("unreachableTitle")} retry={retry}>{errText(state.error, "network")}</Problem>;
    case "stopped":
      return <Problem title={t("stoppedTitle")} retry={retry}>{t("stoppedBody")}</Problem>;
    case "done":
      return <ReportDone report={state.report} />;
  }
}
