"use client";

import { useState } from "react";

export interface TrendSeriesPoint {
  x: number;      // flight index
  y: number;
  label: string;  // tooltip label, e.g. file name
}

interface TrendLineChartProps {
  points: TrendSeriesPoint[];
  color?: string;
  height?: number;
  unit?: string;
  /** Optional fixed y-domain, e.g. [0, 100] for scores. Auto-scaled if omitted. */
  yDomain?: [number, number];
}

const PADDING = { top: 12, right: 12, bottom: 22, left: 34 };

/**
 * Minimal dependency-free SVG line chart for cross-flight trends. Built
 * in-house rather than pulling in a charting library — the app already
 * hand-rolls its 3D scenes and animations, and a handful of points on an
 * axis doesn't need a 40KB dependency.
 */
export function TrendLineChart({
  points,
  color = "#E8A020",
  height = 160,
  unit = "",
  yDomain,
}: TrendLineChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const width = 560;

  if (points.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-white/30"
        style={{ height }}
      >
        No data
      </div>
    );
  }

  const innerW = width - PADDING.left - PADDING.right;
  const innerH = height - PADDING.top - PADDING.bottom;

  const ys = points.map((p) => p.y);
  const [yMin, yMax] = yDomain ?? [Math.min(...ys), Math.max(...ys)];
  const ySpan = yMax - yMin || 1;

  const xFor = (i: number) =>
    points.length === 1
      ? PADDING.left + innerW / 2
      : PADDING.left + (i / (points.length - 1)) * innerW;
  const yFor = (v: number) =>
    PADDING.top + innerH - ((v - yMin) / ySpan) * innerH;

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(i).toFixed(1)} ${yFor(p.y).toFixed(1)}`)
    .join(" ");

  const gridLines = 3;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
      style={{ height }}
      onMouseLeave={() => setHoverIdx(null)}
    >
      {/* horizontal gridlines */}
      {Array.from({ length: gridLines + 1 }, (_, i) => {
        const v = yMin + (ySpan * i) / gridLines;
        const y = yFor(v);
        return (
          <g key={i}>
            <line
              x1={PADDING.left} x2={width - PADDING.right}
              y1={y} y2={y}
              stroke="rgba(255,255,255,0.06)" strokeWidth={1}
            />
            <text x={PADDING.left - 6} y={y + 3} textAnchor="end" fontSize="9" fill="rgba(255,255,255,0.35)">
              {v.toFixed(v < 10 ? 1 : 0)}
            </text>
          </g>
        );
      })}

      <path d={linePath} fill="none" stroke={color} strokeWidth={2} />

      {points.map((p, i) => (
        <g key={i}>
          <circle
            cx={xFor(i)} cy={yFor(p.y)} r={hoverIdx === i ? 5 : 3.5}
            fill={color}
            stroke="#080D1A" strokeWidth={1.5}
            onMouseEnter={() => setHoverIdx(i)}
          />
          {/* wider invisible hit target */}
          <rect
            x={xFor(i) - innerW / points.length / 2}
            y={PADDING.top}
            width={innerW / points.length}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(i)}
          />
        </g>
      ))}

      {hoverIdx !== null && (
        <g>
          <line
            x1={xFor(hoverIdx)} x2={xFor(hoverIdx)}
            y1={PADDING.top} y2={PADDING.top + innerH}
            stroke="rgba(255,255,255,0.15)" strokeWidth={1}
          />
          <text
            x={Math.min(Math.max(xFor(hoverIdx), 50), width - 60)}
            y={PADDING.top + 10}
            textAnchor="middle"
            fontSize="10"
            fontWeight="600"
            fill="#E8EDF5"
          >
            {points[hoverIdx].y.toFixed(2)}{unit}
          </text>
          <text
            x={Math.min(Math.max(xFor(hoverIdx), 50), width - 60)}
            y={height - 6}
            textAnchor="middle"
            fontSize="8"
            fill="rgba(255,255,255,0.4)"
          >
            {points[hoverIdx].label}
          </text>
        </g>
      )}
    </svg>
  );
}
