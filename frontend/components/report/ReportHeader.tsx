"use client";

import { useState } from "react";
import { Check, CheckCircle2, Link2, Printer } from "lucide-react";
import type { FlightMDReport } from "@/lib/types";
import { ScoreCircle } from "@/components/shared/ScoreCircle";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { fmtBytes, fmtDateTime, fmtDuration, fmtNum, fmtUtc, isNum, parseIsoDate } from "@/lib/format";
import { TONE_CLASSES, copyToClipboard, gradeTone, isAssessed, isReportAssessed } from "@/lib/utils";

export function ReportHeader({ report }: { report: FlightMDReport }) {
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
              <dt className="sr-only">Flown</dt>
              <dd>
                {flown ? (
                  <time dateTime={flown.toISOString()}>
                    {fmtDateTime(flown)} <span className="num">({fmtUtc(flown)})</span>
                  </time>
                ) : (
                  "Flight date not in log"
                )}
              </dd>
            </div>
            {vehicle && (
              <div>
                <dt className="sr-only">Vehicle</dt>
                <dd>{vehicle}</dd>
              </div>
            )}
            <div>
              <dt className="sr-only">Duration</dt>
              <dd className="num">{fmtDuration(m.duration_seconds)}</dd>
            </div>
            <div>
              <dt className="sr-only">File size</dt>
              <dd className="num">{fmtBytes(report.file_size_bytes)}</dd>
            </div>
          </dl>
        </div>
        <div className="no-print flex gap-2">
          <button type="button" onClick={() => window.print()} className="btn">
            <Printer aria-hidden className="h-4 w-4" />
            Print
          </button>
          <button type="button" onClick={share} className="btn" aria-live="polite">
            {copied ? <Check aria-hidden className="h-4 w-4 text-ok" /> : <Link2 aria-hidden className="h-4 w-4" />}
            {copied ? "Link copied" : "Copy link"}
          </button>
        </div>
      </div>

      <div className="panel flex flex-col gap-5 p-4 sm:flex-row sm:items-center sm:p-6">
        <ScoreCircle score={report.overall_score} label={report.score_label} notAssessed={!assessed} />

        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            {assessed && (
              <span className={`rounded-sm border px-1.5 py-px text-xs font-semibold ${TONE_CLASSES[gradeTone(report.letter_grade)]}`}>
                Grade {report.letter_grade}
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
                No critical or warning findings
              </span>
            )}
          </div>

          <p className="text-sm sm:text-base">{report.executive_summary}</p>

          <p className="text-xs text-fg-muted">
            {assessed ? (
              <>
                Assessed <span className="num">{assessedCount}</span> of <span className="num">{modules.length}</span> checks
                {fraction !== null && fraction < 1 && <> (<span className="num">{fmtNum(fraction * 100, 0)} %</span> of the weighted score)</>}
                . Modules the log had no data for are listed as Not assessed below.
              </>
            ) : (
              "None of the checks could run on this log, so there is no score. See flight details for what was missing."
            )}
            {warningsCount > 0 && (
              <>
                {" "}
                <a href="#details">{warningsCount} parser {warningsCount === 1 ? "warning" : "warnings"}</a>.
              </>
            )}
          </p>
        </div>
      </div>
    </header>
  );
}
