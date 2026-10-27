"use client";

import { useTranslations } from "next-intl";
import type { Finding } from "@/lib/types";
import { fmtClock } from "@/lib/format";
import { SEVERITY_ORDER, SEVERITY_TONE, TONE_FILL_VAR, TONE_VAR, findingEnd, findingStart } from "@/lib/utils";
import { TONE_ICON } from "@/components/shared/SeverityBadge";

interface Props {
  findings: Finding[];
  duration: number;
  armed?: [number, number][] | null;
  onSelect: (id: string) => void;
}

// 0 -> end of log, one marker per timed finding; a tap jumps to its card.
export function FindingsTimeline({ findings, duration, armed, onSelect }: Props) {
  const t = useTranslations("findings");
  const ts = useTranslations("severity");
  const timed = findings
    .map((f) => ({ f, start: findingStart(f), end: findingEnd(f) }))
    .filter((x): x is { f: Finding; start: number; end: number | null } => x.start !== null)
    // worst drawn last so it sits on top
    .sort((a, b) => SEVERITY_ORDER[b.f.severity] - SEVERITY_ORDER[a.f.severity]);

  if (timed.length === 0) return null;

  const span = Math.max(duration, ...timed.map((x) => x.end ?? x.start), 1);
  const pct = (s: number) => `${Math.max(0, Math.min(100, (s / span) * 100))}%`;

  return (
    <div className="space-y-1">
      <div className="label">{t("timeline")}</div>
      <div className="relative h-8 rounded-sm border bg-elevated" role="group" aria-label={t("timelineLabel")}>
        {armed?.map(([s, e]) => (
          <div
            key={`${s}-${e}`}
            className="absolute inset-y-0 bg-fg-muted/10"
            style={{ left: pct(s), width: `calc(${pct(e)} - ${pct(s)})` }}
            aria-hidden
          />
        ))}
        {timed.map(({ f, start, end }) => {
          const tone = SEVERITY_TONE[f.severity];
          const Icon = TONE_ICON[tone];
          const hasSpan = end !== null && end > start;
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => onSelect(f.id)}
              className="absolute top-0 flex h-full min-w-3 -translate-x-1/2 items-center justify-center rounded-sm pointer-coarse:min-w-6"
              style={{
                left: hasSpan ? `calc((${pct(start)} + ${pct(end!)}) / 2)` : pct(start),
                width: hasSpan ? `calc(${pct(end!)} - ${pct(start)})` : undefined,
                background: hasSpan ? `color-mix(in srgb, ${TONE_FILL_VAR[tone]} 25%, transparent)` : undefined,
                color: TONE_VAR[tone],
              }}
              aria-label={t("marker", { severity: ts(f.severity), time: fmtClock(start), title: f.title })}
              title={`${fmtClock(start)} ${f.title}`}
            >
              <Icon aria-hidden className="h-3.5 w-3.5" />
            </button>
          );
        })}
      </div>
      <div className="num flex justify-between text-2xs text-fg-muted" aria-hidden>
        <span>0:00</span>
        {armed && armed.length > 0 && <span className="font-sans">{t("armedBand")}</span>}
        <span>{fmtClock(span)}</span>
      </div>
    </div>
  );
}
