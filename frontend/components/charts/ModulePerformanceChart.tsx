"use client";

import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell, ResponsiveContainer } from "recharts";
import type { AnalyserResult } from "@/lib/types";
import { scoreColour } from "@/lib/utils";

interface Props {
  analyserResults: AnalyserResult[];
}

interface TooltipPayloadItem {
  payload?: { name: string; score: number };
}

// Every applicable module's health_score at a glance — the overall score is
// a single weighted number, but "why" always traces back to one or two
// modules dragging it down, and this makes that visible without opening
// every finding card individually.
export function ModulePerformanceChart({ analyserResults }: Props) {
  const applicable = analyserResults.filter((r) => !r.skipped);

  if (applicable.length === 0) return null;

  const chartData = applicable
    .map((r) => ({ name: r.display_name, score: Math.round(r.health_score) }))
    .sort((a, b) => a.score - b.score);

  const height = Math.max(160, chartData.length * 34);

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartData}
          layout="vertical"
          margin={{ top: 4, right: 24, left: 8, bottom: 0 }}
        >
          <CartesianGrid stroke="rgba(255,255,255,0.04)" horizontal={false} />
          <XAxis
            type="number"
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={110}
            tick={{ fontSize: 11, fill: "rgba(255,255,255,0.7)" }}
          />
          <Tooltip
            cursor={{ fill: "rgba(255,255,255,0.03)" }}
            contentStyle={{ background: "#171717", border: "1px solid rgba(255,255,255,0.1)", fontSize: 11 }}
            labelStyle={{ color: "rgba(255,255,255,0.85)", fontWeight: 600, marginBottom: 4 }}
            itemStyle={{ color: "#E7C25B" }}
            formatter={(value: number) => [`${value}/100`, "Health score"]}
            labelFormatter={(_label: string, payload: TooltipPayloadItem[]) =>
              payload?.[0]?.payload?.name ?? ""
            }
          />
          <Bar dataKey="score" radius={[0, 4, 4, 0]} barSize={16}>
            {chartData.map((entry) => (
              <Cell key={entry.name} fill={scoreColour(entry.score)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
