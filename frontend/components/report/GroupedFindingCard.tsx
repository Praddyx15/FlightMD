"use client";

import { useState } from "react";
import * as Collapsible from "@radix-ui/react-collapsible";
import type { Finding } from "@/lib/types";
import type { FindingGroup } from "@/lib/groupFindings";
import { groupItemLabel } from "@/lib/groupFindings";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { CategoryIcon } from "@/components/shared/CategoryIcon";
import { SEVERITY_COLOURS, formatMs } from "@/lib/utils";
import { OscillationChart } from "@/components/charts/OscillationChart";
import { VibrationChart }   from "@/components/charts/VibrationChart";
import { BatteryChart }     from "@/components/charts/BatteryChart";
import { GPSChart }         from "@/components/charts/GPSChart";
import { EKFChart }         from "@/components/charts/EKFChart";

export function GroupedFindingCard({ group }: { group: FindingGroup }) {
  const [expanded, setExpanded] = useState(false);
  const colour = SEVERITY_COLOURS[group.worstSeverity];

  return (
    <Collapsible.Root
      open={expanded}
      onOpenChange={setExpanded}
      className="rounded-2xl border overflow-hidden transition-all duration-200 shadow-md"
      style={{
        borderColor: expanded ? `${colour}55` : "var(--border)",
        background: "var(--bg-card)",
      }}
    >
      <Collapsible.Trigger asChild>
        <button className="w-full text-left px-4 py-4 flex items-start gap-3 hover:bg-white/2 transition-colors">
          <div
            className="w-1 self-stretch rounded-full flex-shrink-0"
            style={{ background: colour, minHeight: 20 }}
          />

          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-2 mb-1">
              <SeverityBadge severity={group.worstSeverity} />
              <CategoryIcon category={group.category} />
              <span className="text-white/80 font-semibold text-sm leading-tight">
                {group.groupTitle}
              </span>
              <span
                className="text-xs font-bold px-1.5 py-0.5 rounded-full"
                style={{ color: colour, background: `${colour}22` }}
              >
                {group.items.length}
              </span>
            </div>
            <p className="text-white/55 text-xs leading-relaxed">
              {group.items.length} related findings — {group.items.map(groupItemLabel).join(", ")}
            </p>
          </div>

          <div className="flex-shrink-0 flex flex-col items-end gap-1">
            <span
              className="text-white/30 text-xs mt-1 inline-block transition-transform duration-200"
              style={{ transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}
            >
              ▼
            </span>
          </div>
        </button>
      </Collapsible.Trigger>

      <Collapsible.Content className="collapsible-content">
        <div className="px-4 pb-5 border-t border-white/5 pt-2 divide-y divide-white/5">
          {group.items.map((item) => (
            <GroupItemRow key={item.id} finding={item} />
          ))}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}

function GroupItemRow({ finding }: { finding: Finding }) {
  const colour = SEVERITY_COLOURS[finding.severity];
  const label = groupItemLabel(finding);

  return (
    <div className="py-4 space-y-3 first:pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        <span className="text-white/80 font-semibold text-sm">{label}</span>
        {finding.timestamp_start_ms !== null && (
          <span className="text-white/30 text-xs mono">
            t={formatMs(finding.timestamp_start_ms)}
          </span>
        )}
        <span className="text-white/20 text-xs">
          {Math.round(finding.confidence * 100)}% conf.
        </span>
      </div>

      <p className="text-white/80 text-sm leading-relaxed">{finding.plain_english}</p>

      <div
        className="rounded-xl px-4 py-3"
        style={{ background: "var(--bg-elevated)", borderLeft: `3px solid ${colour}` }}
      >
        <h4 className="text-xs text-white/35 uppercase tracking-wider mb-1">
          Recommended Action
        </h4>
        <p className="text-white/90 text-sm">{finding.recommendation}</p>
      </div>

      <p className="text-white/45 text-xs mono leading-relaxed">
        {finding.technical_summary}
      </p>

      <FindingChart finding={finding} />

      {finding.param_changes.length > 0 && (
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
                <td className="py-1.5 mono text-right font-bold" style={{ color: "#B89642" }}>
                  {pc.suggested_value}
                </td>
                <td className="py-1.5 text-right text-white/30 capitalize hidden sm:table-cell">
                  {pc.change_direction}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
