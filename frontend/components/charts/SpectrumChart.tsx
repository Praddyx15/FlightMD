"use client";

import { useMemo } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useTranslations } from "next-intl";
import type { SpectrumChartSpec } from "@/lib/chartData";
import { fmtNum } from "@/lib/format";
import { AXIS_TICK, GRID_STROKE, TOOLTIP_STYLE, seriesColour } from "./chartTheme";

export function SpectrumChart({ spec, height = 200 }: { spec: SpectrumChartSpec; height?: number }) {
  const t = useTranslations("charts");
  const title = t(`titles.${spec.title.key}`, spec.title.values);
  const rows = useMemo(() => spec.freq.map((f, i) => ({ f, amp: spec.amp[i] })), [spec]);
  const fMax = spec.freq[spec.freq.length - 1];

  return (
    <figure
      aria-label={spec.peakHz !== null
        ? t("spectrumAriaPeak", { title, max: fmtNum(fMax, 0, "Hz"), peak: fmtNum(spec.peakHz, 1, "Hz") })
        : t("spectrumAria", { title, max: fmtNum(fMax, 0, "Hz") })}
    >
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 16, right: 12, left: 0, bottom: 0 }} accessibilityLayer>
            <CartesianGrid stroke={GRID_STROKE} strokeOpacity={0.6} vertical={false} />
            <XAxis
              dataKey="f"
              type="number"
              domain={[0, fMax]}
              tickFormatter={(v: number) => fmtNum(v, 0)}
              tick={AXIS_TICK}
              stroke={GRID_STROKE}
              unit=" Hz"
              minTickGap={24}
            />
            <YAxis tick={AXIS_TICK} stroke={GRID_STROKE} width={44} tickFormatter={(v: number) => fmtNum(v, 3)} />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(v) => fmtNum(Number(v), 1, "Hz")}
              formatter={(v) => [fmtNum(Number(v), 4), t("amplitude")]}
            />
            {spec.peakHz !== null && (
              <ReferenceLine
                x={spec.peakHz}
                stroke="var(--caution)"
                strokeDasharray="4 2"
                ifOverflow="extendDomain"
                label={{ value: t("peak", { hz: fmtNum(spec.peakHz, 1, "Hz") }), fill: "var(--caution)", fontSize: 11, position: "top" }}
              />
            )}
            <Line type="linear" dataKey="amp" name={t("amplitude")} stroke={seriesColour(0)} strokeWidth={1.5} dot={false} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
