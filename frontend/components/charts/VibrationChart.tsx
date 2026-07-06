"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, ReferenceLine } from "recharts";

interface Props { data: Record<string, unknown>; }

export function VibrationChart({ data }: Props) {
  const ts   = (data.timestamps as number[]) ?? [];
  const x    = (data.x as number[]) ?? [];
  const y    = (data.y as number[]) ?? [];
  const z    = (data.z as number[]) ?? [];

  if (ts.length === 0) return null;

  const step = Math.max(1, Math.floor(ts.length / 300));
  const chartData = ts.filter((_, i) => i % step === 0).map((t, i) => ({
    t: parseFloat((t / 1000).toFixed(1)),
    x: parseFloat((x[i * step] ?? 0).toFixed(2)),
    y: parseFloat((y[i * step] ?? 0).toFixed(2)),
    z: parseFloat((z[i * step] ?? 0).toFixed(2)),
  }));

  return (
    <div>
      <h4 className="text-xs text-white/35 uppercase tracking-wider mb-2">
        IMU Acceleration (m/s²)
      </h4>
      <div style={{ height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.04)" />
            <XAxis dataKey="t" tickFormatter={(v) => `${v}s`} tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }} />
            <YAxis tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }} />
            <Tooltip contentStyle={{ background: "#171717", border: "1px solid rgba(255,255,255,0.1)", fontSize: 11 }}
              labelFormatter={(l) => `${l}s`} />
            <ReferenceLine y={30} stroke="#FF3D3D" strokeDasharray="3 3" />
            <ReferenceLine y={-30} stroke="#FF3D3D" strokeDasharray="3 3" />
            <Line type="monotone" dataKey="x" stroke="#3A9CF8" strokeWidth={1} dot={false} name="X" />
            <Line type="monotone" dataKey="y" stroke="#0DD97C" strokeWidth={1} dot={false} name="Y" />
            <Line type="monotone" dataKey="z" stroke="#B89642" strokeWidth={1} dot={false} name="Z" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
