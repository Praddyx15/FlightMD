"use client";

import { useState } from "react";
import { Check, CheckCircle2, ClipboardList, Link2, Printer } from "lucide-react";
import { useTranslations } from "next-intl";
import type { FlightMDReport } from "@/lib/types";
import { ScoreCircle } from "@/components/shared/ScoreCircle";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { FlightTime } from "@/components/shared/FlightTime";
import { CopyText } from "@/components/shared/CopyText";
import { fmtBytes, fmtDuration, fmtNum, isNum, parseIsoDate } from "@/lib/format";
import { TONE_CLASSES, copyToClipboard, gradeTone, isAssessed, isReportAssessed } from "@/lib/utils";

const num = (chunks: React.ReactNode) => <span className="num">{chunks}</span>;

export function ReportHeader({ report }: { report: FlightMDReport }) {
  const t = useTranslations("header");
  const m = report.metadata;
  const [copied, setCopied] = useState(false);
  const criticals = report.findings.filter((f) => f.severity === "critical").length;
  const warnings = report.findings.filter((f) => f.severity === "warning").length;
  const assessed = isReportAssessed(report);
  const flown = parseIsoDate(m.log_start_utc);
  const vehicle = [m.vehicle_type, m.airframe_name, m.firmware_version].filter(Boolean).join(" · ");
  const warningsCount = m.parse_warnings?.length ?? 0;

  const modules = report.analyser_results;
  const assessedCount = modules.filter(isAssessed).length;
  const fraction = isNum(report.assessed_fraction) ? report.assessed_fraction : null;

  async function share() {
    try {
      await copyToClipboard(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // nothing useful to show; the address bar still has the link
    }
  }

  return (
    <header className="space-y-4">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-value font-semibold" title={report.file_name}>{report.file_name}</h1>
          <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-fg-muted">
            <div>
              <dt className="sr-only">{t("flown")}</dt>
              <dd>{flown ? <FlightTime iso={flown.toISOString()} /> : t("dateMissing")}</dd>
            </div>
            {vehicle && (
              <div>
                <dt className="sr-only">{t("vehicle")}</dt>
                <dd>{vehicle}</dd>
              </div>
            )}
            <div>
              <dt className="sr-only">{t("duration")}</dt>
              <dd className="num">{fmtDuration(m.duration_seconds)}</dd>
            </div>
            <div>
              <dt className="sr-only">{t("fileSize")}</dt>
              <dd className="num">{fmtBytes(report.file_size_bytes)}</dd>
            </div>
            {m.planning_brief_sha256 && (
              <div className="flex items-center gap-1">
                <dt className="flex items-center gap-1">
                  <ClipboardList aria-hidden className="h-3.5 w-3.5" />
                  {t("planningBrief")}
                </dt>
                <dd><CopyText text={m.planning_brief_sha256} label={t("planningBrief")} /></dd>
              </div>
            )}
          </dl>
        </div>
        <div className="no-print flex gap-2">
          <button type="button" onClick={() => window.print()} className="btn">
            <Printer aria-hidden className="h-4 w-4" />
            {t("print")}
          </button>
          <button type="button" onClick={share} className="btn" aria-live="polite">
            {copied ? <Check aria-hidden className="h-4 w-4 text-ok" /> : <Link2 aria-hidden className="h-4 w-4" />}
            {copied ? t("linkCopied") : t("copyLink")}
          </button>
        </div>
      </div>

      <div className="panel flex flex-col gap-5 p-4 sm:flex-row sm:items-center sm:p-6">
        <ScoreCircle score={report.overall_score} label={report.score_label} notAssessed={!assessed} />

        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {assessed && (
              <span className={`rounded-sm border px-1.5 py-px text-xs font-semibold ${TONE_CLASSES[gradeTone(report.letter_grade)]}`}>
                {t("grade", { grade: report.letter_grade })}
              </span>
            )}
            {criticals > 0 && (
              <a href="#findings" className="no-underline">
                <SeverityBadge severity="critical" count={criticals} />
              </a>
            )}
            {warnings > 0 && (
              <a href="#findings" className="no-underline">
                <SeverityBadge severity="warning" count={warnings} />
              </a>
            )}
            {assessed && criticals === 0 && warnings === 0 && (
              <span className={`inline-flex items-center gap-1 rounded-sm border px-1.5 py-px text-xs font-semibold ${TONE_CLASSES.ok}`}>
                <CheckCircle2 aria-hidden className="h-3.5 w-3.5" />
                {t("allClear")}
              </span>
            )}
          </div>

          <p className="text-sm sm:text-base">{report.executive_summary}</p>

          <p className="text-xs text-fg-muted">
            {assessed ? (
              <>
                {t.rich("assessed", { num, done: assessedCount, total: modules.length })}
                {fraction !== null && fraction < 1 && <> {t.rich("assessedFraction", { num, pct: fmtNum(fraction * 100, 0) })}</>}
                {" "}
                {t("notAssessedNote")}
              </>
            ) : (
              t("noneAssessed")
            )}
            {warningsCount > 0 && (
              <>
                {" "}
                <a href="#details">{t("parserWarnings", { count: warningsCount })}</a>
              </>
            )}
          </p>
        </div>
      </div>
    </header>
  );
}
