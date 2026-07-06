"use client";

import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  ReferenceLine, ResponsiveContainer, CartesianGrid,
} from "recharts";

interface Props { data: Record<string, unknown>; }

export function OscillationChart({ data }: Props) {
  const freqs = (data.frequencies as number[]) ?? [];
  const amps  = (data.amplitudes  as number[]) ?? [];
  const peakHz = (data.peak_hz    as number) ?? 0;

  if (freqs.length === 0) return null;

  const chartData = freqs.slice(0, 200).map((f, i) => ({
    freq: parseFloat(f.toFixed(2)),
    amp:  parseFloat((amps[i] ?? 0).toFixed(4)),
  }));

  return (
    <div>
      <h4 className="text-xs text-white/35 uppercase tracking-wider mb-2">
        FFT Frequency Spectrum — {data.axis as string ?? ""} axis
      </h4>
      <div style={{ height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.04)" />
            <XAxis
              dataKey="freq"
              tickFormatter={(v) => `${v}Hz`}
              tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }}
              domain={[0, 30]}
            />
            <YAxis tick={{ fontSize: 10, fill: "rgba(255,255,255,0.35)" }} />
            <Tooltip
              contentStyle={{ background: "#171717", border: "1px solid rgba(255,255,255,0.1)", fontSize: 11 }}
              labelFormatter={(l) => `${l} Hz`}
              formatter={(v: number) => [v.toFixed(4), "Amplitude"]}
            />
            <ReferenceLine x={peakHz} stroke="#FF7A2F" strokeDasharray="3 3"
              label={{ value: `${peakHz.toFixed(1)} Hz`, fill: "#FF7A2F", fontSize: 10, position: "top" }} />
            <Line
              type="monotone" dataKey="amp"
              stroke="#B89642" strokeWidth={1.5} dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
