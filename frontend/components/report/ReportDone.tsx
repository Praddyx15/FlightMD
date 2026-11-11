"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import type { FlightMDReport } from "@/lib/types";
import { updateRecentReport } from "@/lib/storage";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { ReportView } from "./ReportView";
import { Problem } from "./Problem";

// A finished report, whether the server rendered it or the polling island fetched it.
export function ReportDone({ report }: { report: FlightMDReport }) {
  const t = useTranslations("report");

  useEffect(() => {
    updateRecentReport(report.report_id, {
      score: report.overall_score,
      grade: report.letter_grade,
      scoreLabel: report.score_label,
      flightStart: report.metadata.log_start_utc,
      vehicle: report.metadata.vehicle_type,
      firmware: report.metadata.firmware_version,
    });
  }, [report]);

  return (
    <ErrorBoundary fallback={<Problem title={t("displayTitle")}>{t("displayBody")}</Problem>}>
      <ReportView report={report} />
    </ErrorBoundary>
  );
}
