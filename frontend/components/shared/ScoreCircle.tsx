"use client";

import { useEffect, useRef, useState } from "react";
import { scoreColour } from "@/lib/utils";

interface Props {
  score: number;
  label: string;
  size?: number;
}

export function ScoreCircle({ score, label, size = 140 }: Props) {
  const [displayed, setDisplayed] = useState(0);
  const [drawn, setDrawn] = useState(0);
  const rafRef = useRef<number>(0);

  const radius = (size - 16) / 2;
  const circumference = 2 * Math.PI * radius;
  const colour = scoreColour(score);

  useEffect(() => {
    const duration = 800;
    const start = performance.now();

    function frame(now: number) {
      const elapsed = now - start;
      const t = Math.min(elapsed / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      const current = eased * score;
      setDisplayed(Math.round(current));
      setDrawn(current);
      if (t < 1) rafRef.current = requestAnimationFrame(frame);
    }

    rafRef.current = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(rafRef.current);
  }, [score]);

  const offset = circumference - (drawn / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.07)"
          strokeWidth={10}
        />
        {/* Progress arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={colour}
          strokeWidth={10}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset 0.05s linear, stroke 0.3s" }}
        />
        {/* Centre text — rotate back */}
        <text
          x={size / 2}
          y={size / 2 + 2}
          textAnchor="middle"
          dominantBaseline="middle"
          style={{
            transform: `rotate(90deg)`,
            transformOrigin: `${size / 2}px ${size / 2}px`,
            fill: colour,
            fontSize: size * 0.22,
            fontWeight: "bold",
            fontFamily: "monospace",
          }}
        >
          {displayed}
        </text>
      </svg>
      <span
        className="text-sm font-bold tracking-wide"
        style={{ color: colour }}
      >
        {label}
      </span>
    </div>
  );
}
