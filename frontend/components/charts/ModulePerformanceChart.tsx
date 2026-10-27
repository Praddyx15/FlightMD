import { MinusCircle } from "lucide-react";
import type { AnalyserResult } from "@/lib/types";
import { fmtScore } from "@/lib/format";
import { TONE_VAR, isAssessed, scoreTone } from "@/lib/utils";
import { TONE_ICON } from "@/components/shared/SeverityBadge";

// Plain HTML bars: readable by screen readers, prints cleanly, and a module that was not
// assessed shows as such instead of a full bar.
export function ModulePerformanceChart({ analyserResults }: { analyserResults: AnalyserResult[] }) {
  if (analyserResults.length === 0) return null;

  const assessed = analyserResults.filter(isAssessed).sort((a, b) => a.health_score - b.health_score);
  const notAssessed = analyserResults.filter((r) => !isAssessed(r));

  return (
    <ul className="space-y-1.5">
      {assessed.map((r) => {
        const tone = scoreTone(r.health_score);
        const Icon = TONE_ICON[tone];
        const pct = Math.max(0, Math.min(100, r.health_score));
        return (
          <li key={r.analyser} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 text-xs sm:grid-cols-[12rem_1fr_auto]">
            <span className="truncate">{r.display_name}</span>
            <span className="h-2 rounded-sm bg-elevated" aria-hidden>
              <span className="block h-full rounded-sm" style={{ width: `${pct}%`, background: TONE_VAR[tone] }} />
            </span>
            <span className="num flex items-center gap-1 whitespace-nowrap" style={{ color: TONE_VAR[tone] }}>
              <Icon aria-hidden className="h-3.5 w-3.5" />
              {fmtScore(r.health_score)}
            </span>
          </li>
        );
      })}
      {notAssessed.map((r) => (
        <li key={r.analyser} className="grid grid-cols-[minmax(0,9rem)_1fr] items-center gap-2 text-xs text-fg-muted sm:grid-cols-[12rem_1fr]">
          <span className="truncate">{r.display_name}</span>
          <span className="flex items-center gap-1">
            <MinusCircle aria-hidden className="h-3.5 w-3.5 shrink-0" />
            Not assessed{r.skip_reason ? `: ${r.skip_reason}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
