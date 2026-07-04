"use client";

import { motion } from "framer-motion";
import type { FlightMDReport } from "@/lib/types";
import { ScoreCircle } from "@/components/shared/ScoreCircle";
import { formatDuration, formatFileSize, gradeColour } from "@/lib/utils";

export function ReportHeader({ report }: { report: FlightMDReport }) {
  const m = report.metadata;
  const criticals = report.findings.filter((f) => f.severity === "critical").length;
  const warnings  = report.findings.filter((f) => f.severity === "warning").length;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      className="rounded-xl border p-6 sm:p-8"
      style={{ background: "#0E1428", borderColor: "rgba(255,255,255,0.08)" }}
    >
      <div className="flex flex-col sm:flex-row gap-6 items-start">
        {/* Score circle */}
        <div className="flex-shrink-0">
          <ScoreCircle score={report.overall_score} label={report.score_label} size={130} />
        </div>

        {/* Meta + summary */}
        <div className="flex-1 min-w-0">
          {/* File name */}
          <div className="text-xs text-white/40 mono mb-1">
            {report.file_name} · {formatFileSize(report.file_size_bytes)}
          </div>

          {/* Executive summary */}
          <p className="text-white/85 text-sm sm:text-base leading-relaxed mb-4">
            {report.executive_summary}
          </p>

          {/* Severity counts */}
          <div className="flex flex-wrap gap-3 mb-4">
            <span className="text-xs font-bold px-3 py-1 rounded-full"
              style={{
                color: gradeColour(report.letter_grade),
                background: `${gradeColour(report.letter_grade)}22`,
                border: `1px solid ${gradeColour(report.letter_grade)}55`,
              }}>
              GRADE {report.letter_grade}
            </span>
            {criticals > 0 && (
              <span className="text-xs font-bold px-3 py-1 rounded-full"
                style={{ color: "#FF3D3D", background: "#FF3D3D22", border: "1px solid #FF3D3D55" }}>
                {criticals} CRITICAL
              </span>
            )}
            {warnings > 0 && (
              <span className="text-xs font-bold px-3 py-1 rounded-full"
                style={{ color: "#FF7A2F", background: "#FF7A2F22", border: "1px solid #FF7A2F55" }}>
                {warnings} WARNING
              </span>
            )}
            {criticals === 0 && warnings === 0 && (
              <span className="text-xs font-bold px-3 py-1 rounded-full"
                style={{ color: "#0DD97C", background: "#0DD97C22", border: "1px solid #0DD97C55" }}>
                ✓ No critical issues
              </span>
            )}
          </div>

          {/* Flight metadata grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
            <MetaItem label="Duration"   value={formatDuration(m.duration_seconds)} />
            <MetaItem label="Arm Events" value={String(m.arm_count)} />
            {m.max_altitude_m && (
              <MetaItem label="Max Altitude" value={`${m.max_altitude_m} m`} />
            )}
            {m.max_speed_ms && (
              <MetaItem label="Max Speed"    value={`${m.max_speed_ms} m/s`} />
            )}
            {m.firmware_version && (
              <MetaItem label="Firmware"  value={m.firmware_version} mono />
            )}
            {m.hardware_id && (
              <MetaItem label="Hardware"  value={m.hardware_id} mono />
            )}
            {m.weather && m.weather.description && (
              <MetaItem label="Weather" value={m.weather.description} />
            )}
            <MetaItem
              label="Flight Modes"
              value={m.flight_modes_used.join(", ") || "—"}
            />
            <MetaItem
              label="Processed in"
              value={`${(report.processing_time_ms / 1000).toFixed(1)}s`}
            />
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function MetaItem({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div
      className="rounded-lg p-2.5"
      style={{ background: "#141C35", border: "1px solid rgba(255,255,255,0.05)" }}
    >
      <div className="text-white/35 uppercase tracking-wider text-[10px] mb-0.5">
        {label}
      </div>
      <div
        className={`text-white/80 font-medium truncate ${mono ? "font-mono text-[10px]" : ""}`}
      >
        {value}
      </div>
    </div>
  );
}
