"use client";

import { useMemo } from "react";
import {
  CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { useTranslations } from "next-intl";
import type { Msg, TimeChartSpec } from "@/lib/chartData";
import { fmtClock, fmtNum } from "@/lib/format";
import { TONE_FILL_VAR, TONE_VAR, type Tone } from "@/lib/utils";
import { AXIS_TICK, GRID_STROKE, TOOLTIP_STYLE, seriesColour, seriesDash } from "./chartTheme";

export interface ChartWindow {
  id: string;
  start: number;
  end: number | null;
  tone: Tone;
  label: string;
}

interface Props {
  spec: TimeChartSpec;
  windows?: ChartWindow[];
  activeId?: string | null;
  armed?: [number, number][] | null;
  height?: number;
}

function range(values: (number | null)[]): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v === null) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo <= hi ? [lo, hi] : null;
}

export function TimeSeriesChart({ spec, windows = [], activeId, armed, height = 200 }: Props) {
  const t = useTranslations("charts");
  const tr = (m: Msg, ns: "titles" | "series" | "refs") => t(`${ns}.${m.key}`, m.values);
  const title = tr(spec.title, "titles");
  const rows = useMemo(
    () =>
      spec.t.map((t, i) => {
        const row: Record<string, number | null> = { t };
        for (const s of spec.series) row[s.key] = s.values[i];
        return row;
      }),
    [spec]
  );

  const hasRight = spec.series.some((s) => s.axis === "right");
  const t0 = spec.t[0];
  const t1 = spec.t[spec.t.length - 1];
  const unitOf = (axis?: "left" | "right") => (axis === "right" ? spec.rightUnit : spec.leftUnit);

  const summary = spec.series
    .map((s) => {
      const r = range(s.values);
      const u = unitOf(s.axis);
      return r ? t("seriesRange", { label: tr(s.label, "series"), lo: fmtNum(r[0], 2), hi: fmtNum(r[1], 2, u) }) : null;
    })
    .filter(Boolean)
    .join(" · ");

  return (
    <figure aria-label={t("timeAria", { title, from: fmtClock(t0), to: fmtClock(t1), summary })}>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: hasRight ? 0 : 12, left: 0, bottom: 0 }} accessibilityLayer>
            <CartesianGrid stroke={GRID_STROKE} strokeOpacity={0.6} vertical={false} />
            <XAxis
              dataKey="t"
              type="number"
              domain={[t0, t1]}
              tickFormatter={(v: number) => fmtClock(v)}
              tick={AXIS_TICK}
              stroke={GRID_STROKE}
              minTickGap={24}
            />
            <YAxis yAxisId="left" tick={AXIS_TICK} stroke={GRID_STROKE} width={44} tickFormatter={(v: number) => fmtNum(v, 2)} />
            {hasRight && (
              <YAxis yAxisId="right" orientation="right" tick={AXIS_TICK} stroke={GRID_STROKE} width={40} tickFormatter={(v: number) => fmtNum(v, 2)} />
            )}

            {armed?.map(([s, e]) => (
              <ReferenceArea key={`armed-${s}-${e}`} yAxisId="left" x1={Math.max(s, t0)} x2={Math.min(e, t1)} fill="var(--text-muted)" fillOpacity={0.06} ifOverflow="hidden" />
            ))}

            {windows.map((w) => {
              const active = w.id === activeId;
              const end = w.end !== null && w.end > w.start ? w.end : null;
              return end !== null ? (
                <ReferenceArea
                  key={w.id}
                  yAxisId="left"
                  x1={w.start}
                  x2={end}
                  fill={TONE_FILL_VAR[w.tone]}
                  fillOpacity={active ? 0.3 : 0.15}
                  stroke={active ? TONE_VAR[w.tone] : undefined}
                  ifOverflow="hidden"
                />
              ) : (
                <ReferenceLine
                  key={w.id}
                  yAxisId="left"
                  x={w.start}
                  stroke={TONE_VAR[w.tone]}
                  strokeWidth={active ? 2 : 1}
                  strokeDasharray="4 2"
                  ifOverflow="hidden"
                />
              );
            })}

            {spec.refLines?.map((r) => (
              <ReferenceLine
                key={r.label.key}
                yAxisId={r.axis ?? "left"}
                y={r.y}
                stroke="var(--text-muted)"
                strokeDasharray="3 3"
                label={{ value: tr(r.label, "refs"), fill: "var(--text-muted)", fontSize: 11, position: "insideTopRight" }}
              />
            ))}

            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={(v) => `t = ${fmtClock(Number(v), 1)}`}
              formatter={(v, name, item) => {
                const s = spec.series.find((x) => x.key === item.dataKey);
                return [fmtNum(Number(v), 2, unitOf(s?.axis)), String(name)];
              }}
            />

            {spec.series.map((s, i) => (
              <Line
                key={s.key}
                yAxisId={s.axis ?? "left"}
                type={s.step ? "stepAfter" : "linear"}
                dataKey={s.key}
                name={tr(s.label, "series")}
                stroke={seriesColour(i)}
                strokeDasharray={seriesDash(i)}
                strokeWidth={1.5}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <figcaption className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-fg-muted">
        {spec.series.map((s, i) => (
          <span key={s.key} className="flex items-center gap-1.5">
            <svg width="20" height="6" aria-hidden>
              <line x1="0" y1="3" x2="20" y2="3" stroke={seriesColour(i)} strokeWidth="2" strokeDasharray={seriesDash(i)} />
            </svg>
            {tr(s.label, "series")}
            {unitOf(s.axis)
              ? ` (${hasRight ? t(s.axis === "right" ? "unitRight" : "unitLeft", { unit: unitOf(s.axis) ?? "" }) : unitOf(s.axis)})`
              : ""}
          </span>
        ))}
        {armed && armed.length > 0 && <span>{t("armedShaded")}</span>}
      </figcaption>
    </figure>
  );
}
