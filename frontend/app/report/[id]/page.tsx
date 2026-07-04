"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { getStatus, getReport } from "@/lib/api";
import type { FlightMDReport, StatusResponse } from "@/lib/types";
import { ReportHeader } from "@/components/report/ReportHeader";
import { FindingsList } from "@/components/report/FindingsList";
import { ParamSheet } from "@/components/report/ParamSheet";
import { ExportBar } from "@/components/report/ExportBar";

const STATUS_MESSAGES: Record<number, string> = {
  0:  "Preparing analysis…",
  5:  "Parsing flight log…",
  20: "Analysing oscillation…",
  35: "Checking IMU vibration…",
  50: "Evaluating EKF health…",
  62: "Assessing battery…",
  72: "Reviewing GPS quality…",
  80: "Inspecting parameters & motors…",
  88: "Generating AI explanations…",
  96: "Assembling report…",
  100: "Complete!",
};

function progressMessage(progress: number, apiMessage?: string): string {
  if (apiMessage) return apiMessage;
  const thresholds = Object.keys(STATUS_MESSAGES)
    .map(Number)
    .sort((a, b) => b - a);
  for (const t of thresholds) {
    if (progress >= t) return STATUS_MESSAGES[t];
  }
  return "Processing…";
}

export default function ReportPage() {
  const params  = useParams();
  const id      = params?.id as string;
  const [report, setReport] = useState<FlightMDReport | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Poll status every 2s while processing
  const { data: status, error: statusError } = useSWR<StatusResponse>(
    report ? null : id ? `/status/${id}` : null,
    () => getStatus(id),
    {
      refreshInterval: (data) =>
        data?.status === "processing" ? 2000 : 0,
      onSuccess: async (data) => {
        if (data.status === "complete") {
          try {
            const r = await getReport(id);
            setReport(r);
          } catch (e: unknown) {
            setFetchError(e instanceof Error ? e.message : "Failed to load report.");
          }
        }
      },
    }
  );

  // ── Loading / error states ────────────────────────────────────────────────
  if (!id) return <div className="p-8 text-white/50">Invalid report URL.</div>;

  if (fetchError || statusError) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-20 text-center">
        <div className="text-red-400 text-xl mb-3">⚠️ Report Unavailable</div>
        <p className="text-white/50">
          {fetchError || "Could not load status. Reports expire after 1 hour."}
        </p>
        <a href="/" className="mt-6 inline-block text-sm underline" style={{ color: "#E8A020" }}>
          ← Analyse another log
        </a>
      </div>
    );
  }

  if (status?.status === "failed") {
    return (
      <div className="max-w-2xl mx-auto px-4 py-20 text-center">
        <div className="text-red-400 text-xl mb-3">❌ Analysis Failed</div>
        <p className="text-white/50">{status.error || "Unknown error. The log may be corrupted."}</p>
        <a href="/" className="mt-6 inline-block text-sm underline" style={{ color: "#E8A020" }}>
          ← Try again
        </a>
      </div>
    );
  }

  // ── Processing view ───────────────────────────────────────────────────────
  if (!report) {
    const progress = status?.progress ?? 0;
    const message  = progressMessage(progress, status?.message);

    return (
      <div className="max-w-xl mx-auto px-4 py-24 text-center">
        <div className="text-5xl mb-6">✈️</div>
        <h2 className="text-2xl font-bold mb-2" style={{ color: "#E8A020" }}>
          Analysing your flight log
        </h2>
        <p className="text-white/50 mb-8 text-sm">{message}</p>

        {/* Progress bar */}
        <div className="w-full h-2 rounded-full bg-white/10 overflow-hidden mb-3">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${progress}%`,
              background: "linear-gradient(90deg, #E8A020, #FFD080)",
            }}
          />
        </div>
        <div className="text-xs text-white/30 mono">{progress}%</div>

        {/* Animated steps */}
        <div className="mt-10 grid grid-cols-4 gap-2 text-xs text-white/30">
          {STEP_LABELS.map((label, i) => (
            <div
              key={label}
              className="flex flex-col items-center gap-1"
              style={{ opacity: progress > i * 12 ? 1 : 0.3, transition: "opacity 0.5s" }}
            >
              <span className="text-lg">{STEP_ICONS[i]}</span>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // ── Full report ───────────────────────────────────────────────────────────
  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
      <ReportHeader report={report} />
      <FindingsList findings={report.findings} />
      {report.param_change_sheet.length > 0 && (
        <ParamSheet params={report.param_change_sheet} />
      )}
      <ExportBar reportId={id} fileName={report.file_name} />

      {/* Back link */}
      <div className="pb-4">
        <a href="/" className="text-sm text-white/30 hover:text-white/60 transition-colors">
          ← Analyse another log
        </a>
      </div>
    </div>
  );
}

const STEP_LABELS = ["Parse", "Oscillation", "Vibration", "EKF", "Battery", "GPS", "Params", "AI"];
const STEP_ICONS  = ["📄", "〰️", "📳", "🔭", "🔋", "📡", "⚙️", "🤖"];
