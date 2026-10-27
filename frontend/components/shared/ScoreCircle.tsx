"use client";

import { useEffect, useState } from "react";
import { MinusCircle } from "lucide-react";
import { useTranslations } from "next-intl";
import { TONE_VAR, scoreTone } from "@/lib/utils";
import { TONE_ICON } from "./SeverityBadge";

interface Props {
  score: number;
  label: string;
  size?: number;
  notAssessed?: boolean;
}

export function ScoreCircle({ score, label, size = 120, notAssessed = false }: Props) {
  const t = useTranslations("score");
  const [drawn, setDrawn] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const stroke = 8;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const value = notAssessed ? 0 : Math.max(0, Math.min(100, score));
  const tone = scoreTone(value);
  const colour = notAssessed ? "var(--text-subtle)" : TONE_VAR[tone];
  const offset = circumference - (drawn ? value / 100 : 0) * circumference;
  const Icon = notAssessed ? MinusCircle : TONE_ICON[tone];

  return (
    <figure className="flex flex-col items-center gap-2" aria-label={notAssessed ? t("notAssessed") : t("aria", { score: Math.round(value), label })}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden>
          <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--border)" strokeWidth={stroke} />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={colour}
            strokeWidth={stroke}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 300ms ease-out" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="num text-hero font-semibold text-fg">{notAssessed ? "—" : Math.round(value)}</span>
          {!notAssessed && <span className="num text-2xs text-fg-muted">/ 100</span>}
        </div>
      </div>
      <figcaption className="flex items-center gap-1 text-sm font-semibold" style={{ color: notAssessed ? "var(--text-muted)" : colour }}>
        <Icon aria-hidden className="h-4 w-4" />
        {notAssessed ? t("notAssessed") : label}
      </figcaption>
    </figure>
  );
}
