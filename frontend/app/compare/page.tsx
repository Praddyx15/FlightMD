"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { getDiff } from "@/lib/api";
import type { DiffResponse } from "@/lib/types";
import { scoreColour, SEVERITY_COLOURS } from "@/lib/utils";
import { MODULE_LABELS, humaniseMetricKey } from "@/lib/metricLabels";
import { ArrowRight, CheckCircle2, AlertTriangle, Minus } from "lucide-react";

function DeltaBadge({ delta, higherIsBetter = true }: { delta: number | null; higherIsBetter?: boolean }) {
  if (delta === null) {
    return <span className="text-white/20 text-xs font-mono">n/a</span>;
  }
  if (Math.abs(delta) < 0.005) {
    return (
      <span className="flex items-center gap-1 text-white/30 text-xs font-mono">
        <Minus className="w-3 h-3" /> 0
      </span>
    );
  }
  const improved = higherIsBetter ? delta > 0 : delta < 0;
  const colour = improved ? "#0DD97C" : "#FF7A2F";
  return (
    <span className="flex items-center gap-1 text-xs font-mono font-semibold" style={{ color: colour }}>
      {delta > 0 ? "+" : ""}
      {delta.toFixed(delta < 1 && delta > -1 ? 3 : 1)}
    </span>
  );
}

export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <div className="max-w-xl mx-auto px-4 py-24 text-center">
          <div className="text-5xl mb-6 animate-pulse">⚖️</div>
          <p className="text-white/40 text-sm">Loading…</p>
        </div>
      }
    >
      <ComparePageContent />
    </Suspense>
  );
}

function ComparePageContent() {
  const searchParams = useSearchParams();
  const a = searchParams.get("a");
  const b = searchParams.get("b");

  const [data, setData] = useState<DiffResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!a || !b) {
      setError("Two report IDs are required — pass ?a=...&b=... in the URL.");
      setLoading(false);
      return;
    }
    async function load() {
      try {
        const diff = await getDiff(a!, b!);
        setData(diff);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load comparison.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [a, b]);

  if (loading) {
    return (
      <div className="max-w-xl mx-auto px-4 py-24 text-center">
        <div className="text-5xl mb-6 animate-pulse">⚖️</div>
        <p className="text-white/40 text-sm">Comparing flights…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-20 text-center">
        <div className="text-red-400 text-xl mb-3">⚠️ Could Not Compare</div>
        <p className="text-white/50">{error}</p>
        <a href="/" className="mt-6 inline-block text-sm underline" style={{ color: "#E8A020" }}>
          ← Back home
        </a>
      </div>
    );
  }

  const moduleRows = Object.entries(data.module_score_deltas);
  const metricRows = Object.entries(data.key_metric_deltas);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      <h1 className="text-2xl font-bold text-slate-100">Flight Comparison</h1>

      {/* Header: A vs B */}
      <div className="grid grid-cols-[1fr,auto,1fr] items-center gap-4">
        <FlightCard flight={data.a} />
        <div className="flex flex-col items-center gap-1">
          <ArrowRight className="w-6 h-6 text-white/30" />
          <DeltaBadge delta={data.overall_score_delta} />
        </div>
        <FlightCard flight={data.b} />
      </div>

      {/* Module score deltas */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-800">
          <h3 className="font-semibold text-slate-100">Module Health Score Changes</h3>
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-white/40 uppercase tracking-wide">
              <th className="text-left px-6 py-2">Module</th>
              <th className="text-right px-4 py-2">Before</th>
              <th className="text-right px-4 py-2">After</th>
              <th className="text-right px-6 py-2">Δ</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {moduleRows.map(([mod, d]) => (
              <tr key={mod}>
                <td className="px-6 py-2.5 text-slate-200">{MODULE_LABELS[mod] ?? mod}</td>
                <td className="px-4 py-2.5 text-right font-mono text-white/60">
                  {d.a !== null ? d.a.toFixed(0) : "—"}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-white/60">
                  {d.b !== null ? d.b.toFixed(0) : "—"}
                </td>
                <td className="px-6 py-2.5 text-right"><DeltaBadge delta={d.delta} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Key metric deltas */}
      {metricRows.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-800">
            <h3 className="font-semibold text-slate-100">Raw Metric Changes</h3>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-white/40 uppercase tracking-wide">
                <th className="text-left px-6 py-2">Metric</th>
                <th className="text-right px-4 py-2">Before</th>
                <th className="text-right px-4 py-2">After</th>
                <th className="text-right px-6 py-2">Δ</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {metricRows.map(([key, d]) => {
                const { label, unit } = humaniseMetricKey(key);
                return (
                  <tr key={key}>
                    <td className="px-6 py-2.5 text-slate-200">{label}</td>
                    <td className="px-4 py-2.5 text-right font-mono text-white/60">
                      {d.a !== null ? `${d.a.toFixed(3)}${unit}` : "—"}
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-white/60">
                      {d.b !== null ? `${d.b.toFixed(3)}${unit}` : "—"}
                    </td>
                    {/* Higher isn't always better for raw metrics (e.g. lower
                        oscillation Hz amplitude / HDOP is better) — shown
                        neutrally as a plain delta rather than colour-coded. */}
                    <td className="px-6 py-2.5 text-right font-mono text-white/50 text-xs">
                      {d.delta !== null ? `${d.delta > 0 ? "+" : ""}${d.delta.toFixed(3)}` : "n/a"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Findings diff */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <h3 className="font-semibold text-slate-100 mb-3 flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            Resolved ({data.findings_diff.resolved.length})
          </h3>
          {data.findings_diff.resolved.length === 0 ? (
            <p className="text-xs text-white/30">No findings from the first flight went away.</p>
          ) : (
            <ul className="space-y-1.5 text-sm text-white/70">
              {data.findings_diff.resolved.map((title) => (
                <li key={title} className="flex items-start gap-2">
                  <span className="text-emerald-400 mt-0.5">✓</span> {title}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <h3 className="font-semibold text-slate-100 mb-3 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-orange-400" />
            New ({data.findings_diff.new.length})
          </h3>
          {data.findings_diff.new.length === 0 ? (
            <p className="text-xs text-white/30">No new findings appeared in the second flight.</p>
          ) : (
            <ul className="space-y-1.5 text-sm text-white/70">
              {data.findings_diff.new.map((title) => (
                <li key={title} className="flex items-start gap-2">
                  <span className="text-orange-400 mt-0.5">!</span> {title}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {data.findings_diff.persisting_categories.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5">
          <h3 className="font-semibold text-slate-100 mb-3">Persisting Issue Categories</h3>
          <div className="flex flex-wrap gap-2">
            {data.findings_diff.persisting_categories.map((p) => (
              <span
                key={p.category}
                className="px-2.5 py-1 rounded-lg border text-xs font-mono"
                style={{
                  color: SEVERITY_COLOURS[p.severity_b],
                  borderColor: `${SEVERITY_COLOURS[p.severity_b]}40`,
                  background: `${SEVERITY_COLOURS[p.severity_b]}15`,
                }}
              >
                {p.category} ({p.severity_a} → {p.severity_b})
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FlightCard({ flight }: { flight: DiffResponse["a"] }) {
  return (
    <a
      href={`/report/${flight.report_id}`}
      className="block bg-slate-900 border border-slate-800 rounded-2xl p-5 hover:border-slate-700 transition-colors"
    >
      <div className="text-sm font-semibold text-slate-200 truncate mb-2">{flight.file_name}</div>
      <div className="flex items-center gap-2">
        <span className="text-3xl font-bold" style={{ color: scoreColour(flight.overall_score) }}>
          {flight.overall_score}
        </span>
        <span className="text-xs text-white/40">/ 100</span>
      </div>
      <div className="text-xs text-white/40 mt-1">{flight.score_label} · Grade {flight.letter_grade}</div>
    </a>
  );
}
