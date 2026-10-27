"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtNum } from "@/lib/format";
import { AXIS_TICK, GRID_STROKE, TOOLTIP_STYLE } from "./chartTheme";

export interface TrendSeriesPoint {
  x: number; // flight index, oldest first
  y: number | null; // null = not assessed on that flight, drawn as a gap
  label: string;
}

interface TrendLineChartProps {
  points: TrendSeriesPoint[];
  color?: string;
  height?: number;
  unit?: string;
  yDomain?: [number, number];
  digits?: number;
  title?: string;
}

export function TrendLineChart({
  points,
  color = "var(--series-1)",
  height = 160,
  unit = "",
  yDomain,
  digits = 1,
  title = "Trend",
}: TrendLineChartProps) {
  if (points.every((p) => p.y === null)) {
    return (
      <div className="flex items-center justify-center text-xs text-fg-muted" style={{ height }}>
        No assessed values yet
      </div>
    );
  }

  const fmt = (v: number | null) => fmtNum(v, digits, unit || undefined);

  return (
    <figure aria-label={`${title}, ${points.length} flights`}>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} accessibilityLayer>
            <CartesianGrid stroke={GRID_STROKE} strokeOpacity={0.6} vertical={false} />
            <XAxis
              dataKey="x"
              type="number"
              domain={["dataMin", "dataMax"]}
              allowDecimals={false}
              tickFormatter={(v: number) => `#${v + 1}`}
              tick={AXIS_TICK}
              stroke={GRID_STROKE}
            />
            <YAxis
              domain={yDomain ?? ["auto", "auto"]}
              tick={AXIS_TICK}
              stroke={GRID_STROKE}
              width={40}
              tickFormatter={(v: number) => fmtNum(v, digits)}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(_, payload) => {
                const p = payload?.[0]?.payload as TrendSeriesPoint | undefined;
                return p ? `#${p.x + 1} ${p.label}` : "";
              }}
              formatter={(v) => [fmt(v === null ? null : Number(v)), title]}
            />
            <Line
              type="linear"
              dataKey="y"
              stroke={color}
              strokeWidth={2}
              dot={{ r: 3, fill: color, strokeWidth: 0 }}
              activeDot={{ r: 5 }}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <details className="no-print mt-1 text-2xs text-fg-muted">
        <summary className="cursor-pointer">Values</summary>
        <table className="mt-1 w-full">
          <tbody>
            {points.map((p) => (
              <tr key={p.x} className="border-t">
                <td className="py-0.5 pr-2">#{p.x + 1}</td>
                <td className="max-w-0 truncate py-0.5 pr-2">{p.label}</td>
                <td className="num py-0.5 text-right">{p.y === null ? "not assessed" : fmt(p.y)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
