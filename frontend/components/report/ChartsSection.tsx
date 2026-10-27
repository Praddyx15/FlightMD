"use client";

import type { ReportCharts } from "@/lib/chartData";
import { SEVERITY_TONE, cn, findingEnd, findingStart } from "@/lib/utils";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { CategoryIcon } from "@/components/shared/CategoryIcon";
import { TimeSeriesChart, type ChartWindow } from "@/components/charts/TimeSeriesChart";
import { SpectrumChart } from "@/components/charts/SpectrumChart";

interface Props {
  charts: ReportCharts;
  activeId?: string | null;
  armed?: [number, number][] | null;
}

export function ChartsSection({ charts, activeId, armed }: Props) {
  if (charts.specs.length === 0) return null;
  const activeKey = activeId ? charts.chartOf.get(activeId) : undefined;

  return (
    <section id="charts" aria-labelledby="charts-h" className="scroll-mt-4 space-y-3">
      <h2 id="charts-h" className="text-base font-semibold">Evidence</h2>
      <p className="text-xs text-fg-muted">
        Shaded spans and dashed lines mark when each finding happened, in the finding&apos;s severity colour.
      </p>
      <div className="grid gap-3 lg:grid-cols-2">
        {charts.specs.map((spec) => {
          const windows: ChartWindow[] = (charts.findingsOn.get(spec.key) ?? []).flatMap((f) => {
            const start = findingStart(f);
            return start === null
              ? []
              : [{ id: f.id, start, end: findingEnd(f), tone: SEVERITY_TONE[f.severity], label: f.title }];
          });
          return (
            <article
              key={spec.key}
              id={`chart-${spec.key}`}
              tabIndex={-1}
              className={cn("panel scroll-mt-4 p-3", activeKey === spec.key && "ring-2 ring-accent")}
            >
              <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
                <CategoryIcon category={spec.category} />
                {spec.title}
              </h3>
              <ErrorBoundary what="Chart">
                {spec.kind === "time" ? (
                  <TimeSeriesChart spec={spec} windows={windows} activeId={activeId} armed={armed} />
                ) : (
                  <SpectrumChart spec={spec} />
                )}
              </ErrorBoundary>
            </article>
          );
        })}
      </div>
    </section>
  );
}
