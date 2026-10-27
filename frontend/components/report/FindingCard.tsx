"use client";

import { useEffect, useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import type { Finding } from "@/lib/types";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { CategoryIcon } from "@/components/shared/CategoryIcon";
import { SEVERITY_TONE, TONE_EDGE, cn } from "@/lib/utils";
import { Confidence, FindingBody, FindingTime, ShowOnChart } from "./FindingParts";

interface Props {
  finding: Finding;
  defaultOpen?: boolean;
  activeId?: string | null;
  onShowChart?: (id: string) => void;
}

export function FindingCard({ finding, defaultOpen = false, activeId, onShowChart }: Props) {
  const t = useTranslations("findings");
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const active = activeId === finding.id;

  useEffect(() => {
    if (active) setOpen(true);
  }, [active]);

  return (
    <article
      id={`finding-${finding.id}`}
      tabIndex={-1}
      className={cn(
        "scroll-mt-4 rounded border border-l-4 bg-surface",
        TONE_EDGE[SEVERITY_TONE[finding.severity]],
        active && "ring-2 ring-accent"
      )}
    >
      <div className="flex items-start gap-3 px-3 py-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <SeverityBadge severity={finding.severity} />
            <CategoryIcon category={finding.category} />
            <h3 className="text-sm font-semibold">{finding.title}</h3>
          </div>
          {!open && <p className="line-clamp-2 text-xs text-fg-muted">{finding.recommendation}</p>}
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
            <FindingTime finding={finding} />
            <Confidence finding={finding} />
            {onShowChart && <ShowOnChart finding={finding} onShow={onShowChart} />}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={bodyId}
          className="btn no-print shrink-0 px-2"
        >
          <span className="sr-only">{t(open ? "hideDetails" : "showDetails", { title: finding.title })}</span>
          <ChevronDown aria-hidden className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>
      <div id={bodyId} hidden={!open} className="print-expand border-t px-3 pb-4 pt-3">
        <FindingBody finding={finding} />
      </div>
    </article>
  );
}
