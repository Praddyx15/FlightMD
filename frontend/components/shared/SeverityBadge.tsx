import { AlertOctagon, AlertTriangle, CheckCircle2, Info, type LucideIcon } from "lucide-react";
import type { Severity } from "@/lib/types";
import { SEVERITY_LABELS, SEVERITY_TONE, TONE_CLASSES, cn, type Tone } from "@/lib/utils";

export const TONE_ICON: Record<Tone, LucideIcon> = {
  critical: AlertOctagon,
  caution: AlertTriangle,
  advisory: Info,
  ok: CheckCircle2,
};

export function SeverityIcon({ severity, className }: { severity: Severity; className?: string }) {
  const Icon = TONE_ICON[SEVERITY_TONE[severity]];
  return <Icon aria-hidden className={cn("h-4 w-4 shrink-0", className)} />;
}

export function SeverityBadge({ severity, count }: { severity: Severity; count?: number }) {
  const tone = SEVERITY_TONE[severity];
  const Icon = TONE_ICON[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-px text-2xs font-semibold uppercase tracking-[0.02em]",
        TONE_CLASSES[tone]
      )}
    >
      <Icon aria-hidden className="h-3.5 w-3.5" />
      {count !== undefined && <span className="num">{count}</span>}
      {SEVERITY_LABELS[severity]}
    </span>
  );
}
