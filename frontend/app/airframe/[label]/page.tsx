"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getTrends, getAirframeConfig } from "@/lib/api";
import type { TrendsResponse, AirframeConfigResponse } from "@/lib/types";
import { scoreColour } from "@/lib/utils";
import { MODULE_LABELS, humaniseMetricKey } from "@/lib/metricLabels";
import { TrendLineChart, type TrendSeriesPoint } from "@/components/charts/TrendLineChart";
import { MaintenancePanel } from "@/components/airframe/MaintenancePanel";
import { AlertsPanel } from "@/components/airframe/AlertsPanel";
import { TrendingUp, ArrowLeftRight, ExternalLink } from "lucide-react";

export default function AirframeTrendsPage() {
  const params = useParams();
  const router = useRouter();
  const label = decodeURIComponent(params?.label as string);

  const [data, setData] = useState<TrendsResponse | null>(null);
  const [config, setConfig] = useState<AirframeConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    async function load() {
      try {
        const [trends, airframeConfig] = await Promise.all([
          getTrends(label),
          getAirframeConfig(label),
        ]);
        setData(trends);
        setConfig(airframeConfig);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load trend data.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [label]);

  function toggleSelect(reportId: string) {
    setSelected((prev) => {
      if (prev.includes(reportId)) return prev.filter((id) => id !== reportId);
      if (prev.length >= 2) return [prev[1], reportId];
      return [...prev, reportId];
    });
  }

  if (loading) {
    return (
      <div className="max-w-xl mx-auto px-4 py-24 text-center">
        <div className="text-5xl mb-6 animate-pulse">📈</div>
        <p className="text-white/40 text-sm">Loading trend history…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-20 text-center">
        <div className="text-red-400 text-xl mb-3">⚠️ Could Not Load Trends</div>
        <p className="text-white/50">{error}</p>
      </div>
    );
  }

  if (!data || data.flight_count === 0) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-12 space-y-8">
        <div className="text-center space-y-3">
          <TrendingUp className="w-10 h-10 mx-auto text-white/20" />
          <h2 className="text-xl font-bold text-slate-100">No tagged flights yet for &quot;{label}&quot;</h2>
          <p className="text-white/50 text-sm max-w-md mx-auto">
            Trend history only includes flights you tag with an airframe label at upload
            time — everything else stays ephemeral and expires after an hour, as always.
            Upload a flight and give it this label to start building history.
          </p>
          <a href="/" className="inline-block mt-2 text-sm underline" style={{ color: "#E8A020" }}>
            ← Upload a flight
          </a>
        </div>
        {config && (
          <>
            <MaintenancePanel airframeLabel={label} config={config} onUpdated={setConfig} />
            <AlertsPanel airframeLabel={label} config={config} onUpdated={setConfig} />
          </>
        )}
      </div>
    );
  }

  const { flights } = data;
  const scorePoints: TrendSeriesPoint[] = flights.map((f, i) => ({
    x: i, y: f.overall_score, label: f.file_name,
  }));

  const moduleKeys = Object.keys(flights[flights.length - 1]?.module_scores ?? {});
  const allMetricKeys = Array.from(
    new Set(flights.flatMap((f) => Object.keys(f.key_metrics)))
  ).sort();

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-100 flex items-center gap-2">
            <TrendingUp className="w-6 h-6" style={{ color: "#E8A020" }} />
            {label}
          </h1>
          <p className="text-sm text-white/40 mt-1">
            {data.flight_count} tagged {data.flight_count === 1 ? "flight" : "flights"} · trend history
          </p>
        </div>
        {selected.length === 2 && (
          <button
            onClick={() => router.push(`/compare?a=${selected[0]}&b=${selected[1]}`)}
            className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-white transition-all"
            style={{ background: "#E8A020" }}
          >
            <ArrowLeftRight className="w-4 h-4" />
            Compare Selected
          </button>
        )}
      </div>

      {/* Overall score trend */}
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl">
        <h3 className="font-semibold text-slate-100 mb-3">Overall Health Score</h3>
        <TrendLineChart points={scorePoints} yDomain={[0, 100]} color="#E8A020" />
      </div>

      {/* Per-module score trends */}
      <div className="space-y-3">
        <h2 className="text-lg font-bold text-slate-100">Module Health Over Time</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {moduleKeys.map((mod) => {
            const points = flights.map((f, i) => ({
              x: i, y: f.module_scores[mod] ?? 100, label: f.file_name,
            }));
            const latest = points[points.length - 1]?.y ?? 100;
            return (
              <div key={mod} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-sm font-semibold text-slate-200">
                    {MODULE_LABELS[mod] ?? mod}
                  </h4>
                  <span className="text-xs font-mono" style={{ color: scoreColour(latest) }}>
                    {latest.toFixed(0)}
                  </span>
                </div>
                <TrendLineChart points={points} yDomain={[0, 100]} height={100} color={scoreColour(latest)} />
              </div>
            );
          })}
        </div>
      </div>

      {/* Raw key metric trends — the drift that never triggers a finding */}
      {allMetricKeys.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-lg font-bold text-slate-100">Raw Metric Trends</h2>
          <p className="text-xs text-white/40 -mt-2">
            These are the underlying numbers behind each module score — they can show a
            slow drift long before a finding actually fires.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {allMetricKeys.map((key) => {
              const { label: metricLabel, unit } = humaniseMetricKey(key);
              const points = flights
                .map((f, i) => ({ x: i, y: f.key_metrics[key], label: f.file_name }))
                .filter((p): p is TrendSeriesPoint => p.y !== undefined);
              if (points.length === 0) return null;
              return (
                <div key={key} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
                  <h4 className="text-sm font-semibold text-slate-200 mb-2">{metricLabel}</h4>
                  <TrendLineChart points={points} unit={unit} height={100} color="#3A9CF8" />
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Maintenance & alerts */}
      {config && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
          <MaintenancePanel airframeLabel={label} config={config} onUpdated={setConfig} />
          <AlertsPanel airframeLabel={label} config={config} onUpdated={setConfig} />
        </div>
      )}

      {/* Flight list with compare picker */}
      <div className="space-y-3">
        <h2 className="text-lg font-bold text-slate-100">Flight History</h2>
        <p className="text-xs text-white/40 -mt-2">Select two flights to compare side by side.</p>
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden divide-y divide-slate-800">
          {[...flights].reverse().map((f) => (
            <div key={f.report_id} className="p-4 flex items-center gap-4">
              <input
                type="checkbox"
                checked={selected.includes(f.report_id)}
                onChange={() => toggleSelect(f.report_id)}
                className="w-4 h-4 accent-[#E8A020]"
              />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-slate-200 truncate">{f.file_name}</div>
                <div className="text-xs text-white/40">
                  {new Date(f.created_at * 1000).toLocaleString()}
                </div>
              </div>
              <span
                className="px-2 py-0.5 rounded border text-xs font-bold"
                style={{
                  color: scoreColour(f.overall_score),
                  background: `${scoreColour(f.overall_score)}1a`,
                  borderColor: `${scoreColour(f.overall_score)}40`,
                }}
              >
                {f.overall_score}%
              </span>
              <a
                href={`/report/${f.report_id}`}
                className="text-white/30 hover:text-white/60 transition-colors"
                title="View full report"
              >
                <ExternalLink className="w-4 h-4" />
              </a>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
