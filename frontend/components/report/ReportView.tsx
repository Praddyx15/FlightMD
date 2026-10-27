"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FlightMDReport } from "@/lib/types";
import { collectCharts } from "@/lib/chartData";
import { defaultFormat, guessAutopilot } from "@/lib/paramFile";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { ReportHeader } from "./ReportHeader";
import { FindingsList } from "./FindingsList";
import { ParamSheet } from "./ParamSheet";
import { ChartsSection } from "./ChartsSection";
import { FlightDetails } from "./FlightDetails";
import { ExportBar } from "./ExportBar";
import PathPlotter from "./PathPlotter";
import QAAssistant from "./QAAssistant";

function scrollToId(id: string) {
  const el = document.getElementById(id);
  if (!el) return;
  const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
  el.focus({ preventScroll: true });
}

// Order: verdict -> what to fix -> parameter sheet -> evidence -> details. Same order on paper.
export function ReportView({ report }: { report: FlightMDReport }) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [printedAt, setPrintedAt] = useState("");
  const charts = useMemo(() => collectCharts(report.findings), [report.findings]);
  const chartable = useMemo(() => new Set(charts.chartOf.keys()), [charts]);
  const armed = report.metadata.armed_windows ?? null;
  const autopilot = guessAutopilot(report);

  useEffect(() => {
    setPrintedAt(`${window.location.href} · printed ${new Date().toLocaleString()}`);
  }, []);

  const showOnChart = useCallback(
    (id: string) => {
      const key = charts.chartOf.get(id);
      if (!key) return;
      setActiveId(id);
      requestAnimationFrame(() => scrollToId(`chart-${key}`));
    },
    [charts]
  );

  const selectFinding = useCallback((id: string) => {
    setActiveId(id);
    // two frames: let the card open befor scrolling to it
    requestAnimationFrame(() => requestAnimationFrame(() => scrollToId(`finding-${id}`)));
  }, []);

  return (
    <div className="mx-auto max-w-5xl space-y-10 px-4 py-6">
      <p className="print-only text-xs">FlightMD report · {printedAt}</p>

      <ReportHeader report={report} />

      <FindingsList
        findings={report.findings}
        duration={report.metadata.duration_seconds}
        armed={armed}
        activeId={activeId}
        chartable={chartable}
        onShowChart={showOnChart}
        onSelect={selectFinding}
      />

      {report.param_change_sheet.length > 0 && (
        <ParamSheet
          params={report.param_change_sheet}
          defaultFormat={defaultFormat(report)}
          autopilotGuess={autopilot === "px4" ? "PX4" : autopilot === "ardupilot" ? "ArduPilot" : null}
        />
      )}

      <ErrorBoundary what="Charts">
        <ChartsSection charts={charts} activeId={activeId} armed={armed} />
      </ErrorBoundary>

      <FlightDetails report={report} />

      <ErrorBoundary what="Flight path">
        <PathPlotter report={report} />
      </ErrorBoundary>

      <QAAssistant report={report} />

      <ExportBar
        reportId={report.report_id}
        fileName={report.file_name}
        hasGpsPath={!!report.metadata.gps_path && report.metadata.gps_path.length > 0}
      />
    </div>
  );
}
