import type { Severity } from "@/lib/types";
import { SEVERITY_COLOURS } from "@/lib/utils";

const LABELS: Record<Severity, string> = {
  critical: "CRITICAL",
  warning:  "WARNING",
  info:     "INFO",
  good:     "GOOD",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const colour = SEVERITY_COLOURS[severity];
  return (
    <span
      className="inline-block text-xs font-bold px-2 py-0.5 rounded-full tracking-wider"
      style={{
        color: colour,
        background: `${colour}22`,
        border: `1px solid ${colour}55`,
      }}
    >
      {LABELS[severity]}
    </span>
  );
}
