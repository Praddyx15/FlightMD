"use client";

import { useEffect, useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { FindingGroup } from "@/lib/groupFindings";
import { groupItemLabel } from "@/lib/groupFindings";
import { SeverityBadge } from "@/components/shared/SeverityBadge";
import { CategoryIcon } from "@/components/shared/CategoryIcon";
import { SEVERITY_TONE, TONE_EDGE, cn } from "@/lib/utils";
import { Confidence, FindingBody, FindingTime, ShowOnChart } from "./FindingParts";

interface Props {
  group: FindingGroup;
  defaultOpen?: boolean;
  activeId?: string | null;
  chartable?: Set<string>;
  onShowChart?: (id: string) => void;
}

export function GroupedFindingCard({ group, defaultOpen = false, activeId, chartable, onShowChart }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  const containsActive = group.items.some((f) => f.id === activeId);

  useEffect(() => {
    if (containsActive) setOpen(true);
  }, [containsActive]);

  return (
    <article className={cn("rounded border border-l-4 bg-surface", TONE_EDGE[SEVERITY_TONE[group.worstSeverity]])}>
      <div className="flex items-start gap-3 px-3 py-3">
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <SeverityBadge severity={group.worstSeverity} />
            <CategoryIcon category={group.category} />
            <h3 className="text-sm font-semibold">{group.groupTitle}</h3>
            <span className="num text-xs text-fg-muted">× {group.items.length}</span>
          </div>
          <p className="text-xs text-fg-muted">{group.items.map(groupItemLabel).join(", ")}</p>
        </div>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={bodyId}
          className="btn no-print shrink-0 px-2"
        >
          <span className="sr-only">{open ? "Hide" : "Show"} the {group.items.length} {group.groupTitle} findings</span>
          <ChevronDown aria-hidden className={cn("h-4 w-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>

      <div id={bodyId} hidden={!open} className="print-expand divide-y border-t px-3">
        {group.items.map((f) => (
          <div
            key={f.id}
            id={`finding-${f.id}`}
            tabIndex={-1}
            className={cn("scroll-mt-4 space-y-2 py-3", f.id === activeId && "-mx-3 px-3 ring-2 ring-inset ring-accent")}
          >
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <SeverityBadge severity={f.severity} />
              <span className="text-sm font-semibold">{groupItemLabel(f)}</span>
              <FindingTime finding={f} />
              <Confidence finding={f} />
              {chartable?.has(f.id) && <ShowOnChart finding={f} onShow={onShowChart} />}
            </div>
            <FindingBody finding={f} />
          </div>
        ))}
      </div>
    </article>
  );
}
