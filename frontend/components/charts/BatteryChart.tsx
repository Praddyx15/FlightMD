"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from "recharts";

interface Props { data: Record<string, unknown>; }

export function BatteryChart({ data }: Props) {
  const ts      = (data.timestamps as number[]) ?? [];
  const voltage = (data.voltage    as number[]) ?? [];
  const current = (data.current    as number[]) ?? [];
  const pct     = (data.remaining_pct as number[]) ?? [];

  if (ts.length === 0) return null;

  const step = Math.max(1, Math.floor(ts.length / 300));
  const chartData = ts.filter((_, i) => i % step === 0).map((t, i) => ({
    t: parseFloat((t / 1000).toFixed(1)),
    v: parseFloat((voltage[i * step] ?? 0).toFixed(2)),
    i: parseFloat((current[i * step] ?? 0).toFixed(1)),
    pct: parseFloat((pct[i * step] ?? 0).toFixed(1)),
  }));

  return (
    <div>
      <h4 className="text-xs text-white/35 uppercase tracking-wider mb-2">
        Battery — Voltage (V) &amp; Current (A)
      </h4>
      <div style={{ height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="t" tickFormatter={(v) => `${v}s`} tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }} />
            <YAxis yAxisId="v" orientation="left" tick={{ fontSize: 10, fill: "#B89642" }} />
            <YAxis yAxisId="i" orientation="right" tick={{ fontSize: 10, fill: "#3A9CF8" }} />
            <Tooltip contentStyle={{ background: "#171717", border: "1px solid rgba(255,255,255,0.1)", fontSize: 11 }} />
            <Line yAxisId="v" type="monotone" dataKey="v" stroke="#B89642" strokeWidth={1.5} dot={false} name="Voltage (V)" />
            <Line yAxisId="i" type="monotone" dataKey="i" stroke="#3A9CF8" strokeWidth={1} dot={false} name="Current (A)" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
