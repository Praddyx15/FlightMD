"use client";

import { useState } from "react";
import type { Finding } from "@/lib/types";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { CategoryIcon } from "@/components/shared/CategoryIcon";
import { SEVERITY_COLOURS, formatMs } from "@/lib/utils";
import { OscillationChart } from "@/components/charts/OscillationChart";
import { VibrationChart }   from "@/components/charts/VibrationChart";
import { BatteryChart }     from "@/components/charts/BatteryChart";
import { GPSChart }         from "@/components/charts/GPSChart";
import { EKFChart }         from "@/components/charts/EKFChart";

export function FindingCard({ finding }: { finding: Finding }) {
  const [expanded, setExpanded] = useState(false);
  const colour = SEVERITY_COLOURS[finding.severity];

  return (
    <div
      className="rounded-xl border overflow-hidden transition-all duration-200"
      style={{
        borderColor: expanded ? `${colour}55` : "rgba(255,255,255,0.07)",
        background: "#0E1428",
      }}
    >
      {/* Header — always visible, click to toggle */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-4 py-4 flex items-start gap-3 hover:bg-white/2 transition-colors"
      >
        {/* Severity accent bar */}
        <div
          className="w-1 self-stretch rounded-full flex-shrink-0"
          style={{ background: colour, minHeight: 20 }}
        />

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <SeverityBadge severity={finding.severity} />
            <CategoryIcon category={finding.category} />
            <span className="text-white/80 font-semibold text-sm leading-tight">
              {finding.title}
            </span>
          </div>
          <p className="text-white/55 text-xs leading-relaxed line-clamp-2">
            {finding.plain_english}
          </p>
        </div>

        <div className="flex-shrink-0 flex flex-col items-end gap-1">
          {finding.timestamp_start_ms && (
            <span className="text-white/30 text-xs mono">
              t={formatMs(finding.timestamp_start_ms)}
            </span>
          )}
          <span className="text-white/20 text-xs">
            {Math.round(finding.confidence * 100)}% conf.
          </span>
          <span className="text-white/30 text-xs mt-1">
            {expanded ? "▲" : "▼"}
          </span>
        </div>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="px-4 pb-5 border-t border-white/5 pt-4 space-y-4">
          {/* Plain English */}
          <div>
            <h4 className="text-xs text-white/35 uppercase tracking-wider mb-1">Explanation</h4>
            <p className="text-white/80 text-sm leading-relaxed">{finding.plain_english}</p>
          </div>

          {/* Recommendation */}
          <div
            className="rounded-lg px-4 py-3"
            style={{ background: "#1A2540", borderLeft: `3px solid ${colour}` }}
          >
            <h4 className="text-xs text-white/35 uppercase tracking-wider mb-1">
              Recommended Action
            </h4>
            <p className="text-white/90 text-sm">{finding.recommendation}</p>
          </div>

          {/* Technical summary */}
          <div>
            <h4 className="text-xs text-white/35 uppercase tracking-wider mb-1">
              Technical Detail
            </h4>
            <p className="text-white/45 text-xs mono leading-relaxed">
              {finding.technical_summary}
            </p>
          </div>

          {/* Chart */}
          <FindingChart finding={finding} />

          {/* Param changes */}
          {finding.param_changes.length > 0 && (
            <div>
              <h4 className="text-xs text-white/35 uppercase tracking-wider mb-2">
                Parameter Changes
              </h4>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-white/30">
                    <th className="text-left pb-1 font-normal">Parameter</th>
                    <th className="text-right pb-1 font-normal">Current</th>
                    <th className="text-right pb-1 font-normal">Suggested</th>
                    <th className="text-right pb-1 font-normal hidden sm:table-cell">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {finding.param_changes.map((pc) => (
                    <tr key={pc.param_name} className="border-t border-white/5">
                      <td className="py-1.5 mono text-white/70 font-bold">{pc.param_name}</td>
                      <td className="py-1.5 mono text-right text-white/50">{pc.current_value}</td>
                      <td className="py-1.5 mono text-right font-bold"
                        style={{ color: "#E8A020" }}>{pc.suggested_value}</td>
                      <td className="py-1.5 text-right text-white/30 capitalize hidden sm:table-cell">
                        {pc.change_direction}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FindingChart({ finding }: { finding: Finding }) {
  if (!finding.chart_data) return null;
  const cd = finding.chart_data as Record<string, unknown>;

  switch (finding.category) {
    case "oscillation":
      return <OscillationChart data={cd} />;
    case "vibration":
      return <VibrationChart data={cd} />;
    case "battery":
      return <BatteryChart data={cd} />;
    case "gps":
      return <GPSChart data={cd} />;
    case "ekf":
      return <EKFChart data={cd} />;
    default:
      return null;
  }
}
