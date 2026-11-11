"use client";

import { useState } from "react";
import { CheckCircle2, ChevronDown } from "lucide-react";
import { useTranslations } from "next-intl";
import type { Finding, Severity } from "@/lib/types";
import { groupFindings, isFindingGroup, type FindingOrGroup } from "@/lib/groupFindings";
import { SEVERITY_ORDER, cn } from "@/lib/utils";
import { SeverityIcon } from "@/components/shared/SeverityBadge";
import { FindingCard } from "./FindingCard";
import { GroupedFindingCard } from "./GroupedFindingCard";
import { FindingsTimeline } from "./FindingsTimeline";

const ALL_SEVERITIES: Severity[] = ["critical", "warning", "info", "good"];

interface Props {
  findings: Finding[];
  duration?: number;
  armed?: [number, number][] | null;
  activeId?: string | null;
  // ids that have a chart to jump to
  chartable?: Set<string>;
  onShowChart?: (id: string) => void;
  onSelect?: (id: string) => void;
}

export function FindingsList({ findings, duration = 0, armed, activeId, chartable, onShowChart, onSelect }: Props) {
  const t = useTranslations("findings");
  const ts = useTranslations("severity");
  const [filter, setFilter] = useState<Severity | "all">("all");
  const [showOthers, setShowOthers] = useState(false);

  const sorted = [...findings].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
  const counts = Object.fromEntries(
    ALL_SEVERITIES.map((s) => [s, findings.filter((f) => f.severity === s).length])
  ) as Record<Severity, number>;

  function select(id: string) {
    const f = findings.find((x) => x.id === id);
    if (f && (f.severity === "info" || f.severity === "good")) setShowOthers(true);
    if (filter !== "all" && f && f.severity !== filter) setFilter("all");
    onSelect?.(id);
  }

  const renderCards = (list: Finding[], open: boolean) =>
    groupFindings(list).map((g: FindingOrGroup) =>
      isFindingGroup(g) ? (
        <GroupedFindingCard
          key={`group-${g.category}-${g.groupTitle}-${g.items[0].id}`}
          group={g}
          defaultOpen={open && g.worstSeverity === "critical"}
          activeId={activeId}
          chartable={chartable}
          onShowChart={onShowChart}
        />
      ) : (
        <FindingCard
          key={g.id}
          finding={g}
          defaultOpen={open && g.severity === "critical"}
          activeId={activeId}
          onShowChart={chartable?.has(g.id) ? onShowChart : undefined}
        />
      )
    );

  if (findings.length === 0) {
    return (
      <section id="findings" aria-labelledby="findings-h" className="scroll-mt-4 space-y-3">
        <h2 id="findings-h" className="text-base font-semibold">{t("title")}</h2>
        <p className="panel flex items-center gap-2 p-4 text-sm">
          <CheckCircle2 aria-hidden className="h-4 w-4 text-ok" />
          {t("none")}
        </p>
      </section>
    );
  }

  const primary = sorted.filter((f) => f.severity === "critical" || f.severity === "warning");
  const others = sorted.filter((f) => f.severity === "info" || f.severity === "good");

  return (
    <section id="findings" aria-labelledby="findings-h" className="scroll-mt-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="findings-h" className="text-base font-semibold">
          {t("title")} <span className="num font-normal text-fg-muted">({findings.length})</span>
        </h2>
        <div className="no-print ml-auto flex flex-wrap gap-1.5" role="group" aria-label={t("filter")}>
          <FilterPill label={t("all")} count={findings.length} active={filter === "all"} onClick={() => setFilter("all")} />
          {ALL_SEVERITIES.map((s) =>
            counts[s] > 0 ? (
              <FilterPill
                key={s}
                severity={s}
                label={ts(s)}
                count={counts[s]}
                active={filter === s}
                onClick={() => setFilter(s)}
              />
            ) : null
          )}
        </div>
      </div>

      <FindingsTimeline findings={findings} duration={duration} armed={armed} onSelect={select} />

      {filter !== "all" ? (
        <div className="space-y-2">{renderCards(sorted.filter((f) => f.severity === filter), true)}</div>
      ) : (
        <>
          {primary.length > 0 ? (
            <div className="space-y-2">{renderCards(primary, true)}</div>
          ) : (
            <p className="panel flex items-center gap-2 p-4 text-sm">
              <CheckCircle2 aria-hidden className="h-4 w-4 text-ok" />
              {t("noPrimary")}
            </p>
          )}

          {others.length > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setShowOthers((v) => !v)}
                aria-expanded={showOthers}
                aria-controls="other-findings"
                className="btn no-print w-full justify-between"
              >
                <span>{t("others", { count: others.length })}</span>
                <ChevronDown aria-hidden className={cn("h-4 w-4 transition-transform", showOthers && "rotate-180")} />
              </button>
              <div id="other-findings" hidden={!showOthers} className="print-expand mt-2 space-y-2">
                {renderCards(others, false)}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function FilterPill({
  label, count, active, onClick, severity,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
  severity?: Severity;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn("btn gap-1 px-2 text-xs", active && "border-accent bg-accent/15")}
    >
      {severity && <SeverityIcon severity={severity} className="h-3.5 w-3.5" />}
      {label} <span className="num">{count}</span>
    </button>
  );
}
