"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ReferenceLine } from "recharts";

interface Props { data: Record<string, unknown>; }

export function GPSChart({ data }: Props) {
  const ts   = (data.timestamps as number[]) ?? [];
  const sats = (data.satellites as number[]) ?? [];
  const hdop = (data.hdop       as number[]) ?? [];

  if (ts.length === 0) return null;

  const step = Math.max(1, Math.floor(ts.length / 300));
  const chartData = ts.filter((_, i) => i % step === 0).map((t, i) => ({
    t: parseFloat((t / 1000).toFixed(1)),
    sats: sats[i * step] ?? 0,
    hdop: parseFloat((hdop[i * step] ?? 0).toFixed(2)),
  }));

  return (
    <div>
      <h4 className="text-xs text-white/35 uppercase tracking-wider mb-2">
        GPS — Satellites Used &amp; HDOP
      </h4>
      <div style={{ height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="t" tickFormatter={(v) => `${v}s`} tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }} />
            <YAxis yAxisId="sats" orientation="left" tick={{ fontSize: 10, fill: "#0DD97C" }} />
            <YAxis yAxisId="hdop" orientation="right" tick={{ fontSize: 10, fill: "#FF7A2F" }} />
            <Tooltip contentStyle={{ background: "#171717", border: "1px solid rgba(255,255,255,0.1)", fontSize: 11 }} />
            <ReferenceLine yAxisId="hdop" y={2.0} stroke="#FF7A2F" strokeDasharray="3 3" />
            <Line yAxisId="sats" type="stepAfter" dataKey="sats" stroke="#0DD97C" strokeWidth={1.5} dot={false} name="Satellites" />
            <Line yAxisId="hdop" type="monotone" dataKey="hdop" stroke="#FF7A2F" strokeWidth={1} dot={false} name="HDOP" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
