"use client";

import { useState } from "react";
import type { Finding, Severity, Category } from "@/lib/types";
import { FindingCard } from "./FindingCard";

const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0, warning: 1, info: 2, good: 3,
};

const ALL_SEVERITIES: Severity[] = ["critical", "warning", "info", "good"];
const SEVERITY_LABELS: Record<Severity, string> = {
  critical: "Critical", warning: "Warning", info: "Info", good: "Good",
};

interface Props { findings: Finding[]; }

export function FindingsList({ findings }: Props) {
  const [filter, setFilter] = useState<Severity | "all">("all");

  const sorted = [...findings].sort(
    (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
  );

  const filtered = filter === "all"
    ? sorted
    : sorted.filter((f) => f.severity === filter);

  const counts = ALL_SEVERITIES.reduce(
    (acc, s) => ({ ...acc, [s]: findings.filter((f) => f.severity === s).length }),
    {} as Record<Severity, number>
  );

  if (findings.length === 0) {
    return (
      <section>
        <h2 className="text-lg font-bold text-white/80 mb-4">Findings</h2>
        <div
          className="rounded-xl border p-8 text-center"
          style={{ background: "#0E1428", borderColor: "rgba(255,255,255,0.07)" }}
        >
          <div className="text-3xl mb-2">✅</div>
          <p className="text-white/60">No issues detected. Your flight log looks healthy.</p>
        </div>
      </section>
    );
  }

  return (
    <section>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <h2 className="text-lg font-bold text-white/80">
          Findings <span className="text-white/30 font-normal">({findings.length})</span>
        </h2>

        {/* Filter pills */}
        <div className="flex gap-1.5 ml-auto">
          <FilterPill
            label="All"
            count={findings.length}
            active={filter === "all"}
            onClick={() => setFilter("all")}
            colour="rgba(255,255,255,0.5)"
          />
          {ALL_SEVERITIES.map((s) =>
            counts[s] > 0 ? (
              <FilterPill
                key={s}
                label={SEVERITY_LABELS[s]}
                count={counts[s]}
                active={filter === s}
                onClick={() => setFilter(s)}
                colour={SEV_COLOURS[s]}
              />
            ) : null
          )}
        </div>
      </div>

      <div className="space-y-3">
        {filtered.map((f) => (
          <FindingCard key={f.id} finding={f} />
        ))}
      </div>
    </section>
  );
}

const SEV_COLOURS: Record<Severity, string> = {
  critical: "#FF3D3D", warning: "#FF7A2F", info: "#3A9CF8", good: "#0DD97C",
};

function FilterPill({
  label, count, active, onClick, colour,
}: {
  label: string; count: number; active: boolean;
  onClick: () => void; colour: string;
}) {
  return (
    <button
      onClick={onClick}
      className="text-xs px-2.5 py-1 rounded-full transition-all duration-150 font-medium"
      style={{
        color: active ? "#080D1A" : colour,
        background: active ? colour : `${colour}22`,
        border: `1px solid ${colour}55`,
      }}
    >
      {label} {count}
    </button>
  );
}
