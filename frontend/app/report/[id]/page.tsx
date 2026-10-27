"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect } from "react";
import { AlertTriangle, Clock, Loader2 } from "lucide-react";
import { useReport, type ReportState } from "@/lib/useReport";
import { updateRecentReport } from "@/lib/storage";
import { ReportView } from "@/components/report/ReportView";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { UploadProgress } from "@/components/upload/UploadProgress";

function Problem({ title, children, retry }: { title: string; children: React.ReactNode; retry?: () => void }) {
  return (
    <div className="mx-auto max-w-xl px-4 py-20 text-center" role="alert">
      <h1 className="mb-2 flex items-center justify-center gap-2 text-value font-semibold">
        <AlertTriangle aria-hidden className="h-5 w-5 text-caution" />
        {title}
      </h1>
      <div className="text-sm text-fg-muted">{children}</div>
      <div className="mt-6 flex justify-center gap-2">
        {retry && <button type="button" onClick={retry} className="btn-primary">Try again</button>}
        <Link href="/" className="btn">Analyse another log</Link>
      </div>
    </div>
  );
}

function Waiting({ state }: { state: Extract<ReportState, { phase: "queued" | "processing" }> }) {
  return (
    <div className="mx-auto max-w-xl px-4 py-20">
      <h1 className="mb-1 flex items-center gap-2 text-value font-semibold">
        <Loader2 aria-hidden className="h-5 w-5 animate-spin text-accent reduce-motion:animate-none" />
        Analysing your flight log
      </h1>
      <p className="mb-4 text-sm text-fg-muted" aria-live="polite">
        {state.phase === "queued" ? "Waiting for a free worker…" : state.message || "Working…"}
      </p>
      <UploadProgress progress={state.progress} label="Analysis" />
      <p className="mt-4 text-xs text-fg-muted">Usually about 20 seconds. You can leave this tab open; the page updates itself.</p>
    </div>
  );
}

export default function ReportPage() {
  const params = useParams();
  const raw = params?.id;
  const id = typeof raw === "string" ? raw : undefined;
  const { state, retry } = useReport(id);

  useEffect(() => {
    if (state.phase !== "done") return;
    const r = state.report;
    document.title = `${r.file_name} · FlightMD`;
    updateRecentReport(r.report_id, {
      score: r.overall_score,
      grade: r.letter_grade,
      scoreLabel: r.score_label,
      flightStart: r.metadata.log_start_utc,
      vehicle: r.metadata.vehicle_type,
      firmware: r.metadata.firmware_version,
    });
  }, [state]);

  if (!id) return <Problem title="Invalid report link">This address does not contain a report id.</Problem>;

  switch (state.phase) {
    case "queued":
    case "processing":
      return <Waiting state={state} />;
    case "expired":
      return (
        <Problem title="Report expired">
          <p className="flex items-center justify-center gap-1">
            <Clock aria-hidden className="h-4 w-4" />
            Untagged reports are deleted 1 hour after upload. Upload the log again to get a new one.
          </p>
        </Problem>
      );
    case "failed":
      return <Problem title="Analysis failed">{state.error}</Problem>;
    case "error":
      return <Problem title="Can't reach the server" retry={retry}>{state.error}</Problem>;
    case "stopped":
      return (
        <Problem title="Still not finished" retry={retry}>
          The analysis has run for over 10 minutes, so this page stopped checking. It may still finish.
        </Problem>
      );
    case "done":
      return (
        <ErrorBoundary
          fallback={
            <Problem title="This report could not be displayed">
              The report loaded but part of it could not be drawn. The JSON and PDF exports may still work.
            </Problem>
          }
        >
          <ReportView report={state.report} />
        </ErrorBoundary>
      );
  }
}
