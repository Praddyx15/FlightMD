"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ReferenceLine, Legend } from "recharts";

interface Props { data: Record<string, unknown>; }

const COLOURS = ["#3A9CF8", "#E8A020", "#0DD97C", "#FF7A2F", "#CC88FF"];

export function EKFChart({ data }: Props) {
  const ts     = (data.timestamps    as number[]) ?? [];
  const ratios = (data.innov_ratios  as Record<string, number[]>) ?? {};

  if (ts.length === 0 || Object.keys(ratios).length === 0) return null;

  const keys = Object.keys(ratios).slice(0, 5); // max 5 lines
  const step = Math.max(1, Math.floor(ts.length / 300));

  const chartData = ts.filter((_, i) => i % step === 0).map((t, i) => {
    const row: Record<string, number> = { t: parseFloat((t / 1000).toFixed(1)) };
    for (const k of keys) {
      row[k] = parseFloat(((ratios[k]?.[i * step]) ?? 0).toFixed(3));
    }
    return row;
  });

  return (
    <div>
      <h4 className="text-xs text-white/35 uppercase tracking-wider mb-2">
        EKF Innovation Test Ratios (threshold = 1.0)
      </h4>
      <div style={{ height: 180 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="t" tickFormatter={(v) => `${v}s`} tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }} />
            <YAxis tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }} />
            <Tooltip contentStyle={{ background: "#0E1428", border: "1px solid rgba(255,255,255,0.1)", fontSize: 10 }} />
            <Legend wrapperStyle={{ fontSize: 9, color: "rgba(255,255,255,0.4)" }} />
            <ReferenceLine y={1.0} stroke="#FF3D3D" strokeDasharray="3 3"
              label={{ value: "fail", fill: "#FF3D3D", fontSize: 9, position: "right" }} />
            {keys.map((k, idx) => (
              <Line key={k} type="monotone" dataKey={k}
                stroke={COLOURS[idx % COLOURS.length]} strokeWidth={1} dot={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
