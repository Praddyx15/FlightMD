"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle, ArrowLeftRight, TrendingUp } from "lucide-react";
import { AirframeAuthError, getAirframeConfig, getTrends } from "@/lib/api";
import type { AirframeConfigResponse, TrendsResponse } from "@/lib/types";
import { MODULE_LABELS, humaniseMetricKey } from "@/lib/metricLabels";
import { fmtDateTime, fmtScore } from "@/lib/format";
import { TONE_CLASSES, scoreColour, scoreTone } from "@/lib/utils";
import { TrendLineChart, type TrendSeriesPoint } from "@/components/charts/TrendLineChart";
import { MaintenancePanel } from "@/components/airframe/MaintenancePanel";
import { AlertsPanel } from "@/components/airframe/AlertsPanel";
import { AirframeLocked, AirframeTokenInfo } from "@/components/airframe/AirframeAccess";

function decodeLabel(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  try {
    return decodeURIComponent(raw);
  } catch {
    return null; // malformed %-escape in a hand-typed URL
  }
}

type Load =
  | { phase: "loading" }
  | { phase: "locked"; error: AirframeAuthError }
  | { phase: "error"; message: string }
  | { phase: "ready"; trends: TrendsResponse; config: AirframeConfigResponse };

export default function AirframeTrendsPage() {
  const params = useParams();
  const router = useRouter();
  const label = decodeLabel(params?.label);

  const [load, setLoad] = useState<Load>({ phase: "loading" });
  const [reloadKey, setReloadKey] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    if (!label) return;
    let cancelled = false;
    setLoad({ phase: "loading" });
    (async () => {
      const [t, c] = await Promise.allSettled([getTrends(label), getAirframeConfig(label)]);
      if (cancelled) return;
      const auth = [t, c].find(
        (r): r is PromiseRejectedResult => r.status === "rejected" && r.reason instanceof AirframeAuthError
      );
      if (auth) setLoad({ phase: "locked", error: auth.reason as AirframeAuthError });
      else if (t.status === "rejected") setLoad({ phase: "error", message: String(t.reason?.message ?? t.reason) });
      else if (c.status === "rejected") setLoad({ phase: "error", message: String(c.reason?.message ?? c.reason) });
      else setLoad({ phase: "ready", trends: t.value, config: c.value });
    })();
    return () => {
      cancelled = true;
    };
  }, [label, reloadKey]);

  const reload = () => setReloadKey((k) => k + 1);

  if (!label) {
    return <p className="px-4 py-20 text-center text-sm text-fg-muted">This airframe link is malformed.</p>;
  }

  if (load.phase === "loading") {
    return <p className="px-4 py-20 text-center text-sm text-fg-muted" role="status">Loading {label}…</p>;
  }

  if (load.phase === "locked") {
    return (
      <div className="px-4 py-12">
        <AirframeLocked label={label} error={load.error} onUnlocked={reload} />
      </div>
    );
  }

  if (load.phase === "error") {
    return (
      <div className="mx-auto max-w-xl px-4 py-20 text-center" role="alert">
        <h1 className="mb-2 flex items-center justify-center gap-2 text-value font-semibold">
          <AlertTriangle aria-hidden className="h-5 w-5 text-caution" />
          Could not load {label}
        </h1>
        <p className="text-sm text-fg-muted">{load.message}</p>
        <button type="button" onClick={reload} className="btn mt-6">Try again</button>
      </div>
    );
  }

  const { trends, config } = load;
  const setConfig = (c: AirframeConfigResponse) => setLoad({ phase: "ready", trends, config: c });
  const flights = trends.flights;

  function toggleSelect(id: string) {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      return prev.length >= 2 ? [prev[1], id] : [...prev, id];
    });
  }

  function compare() {
    // flights come oldest first, so index order is flight order
    const [a, b] = [...selected].sort(
      (x, y) => flights.findIndex((f) => f.report_id === x) - flights.findIndex((f) => f.report_id === y)
    );
    router.push(`/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  }

  const header = (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h1 className="flex items-center gap-2 text-value font-semibold">
            <TrendingUp aria-hidden className="h-5 w-5 text-accent" />
            {label}
          </h1>
          <p className="text-sm text-fg-muted">
            <span className="num">{trends.flight_count}</span> tagged {trends.flight_count === 1 ? "flight" : "flights"}
          </p>
        </div>
        {selected.length === 2 && (
          <button type="button" onClick={compare} className="btn-primary">
            <ArrowLeftRight aria-hidden className="h-4 w-4" />
            Compare selected
          </button>
        )}
      </div>
      <AirframeTokenInfo label={label} onForget={reload} />
    </div>
  );

  const panels = (
    <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
      <MaintenancePanel airframeLabel={label} config={config} onUpdated={setConfig} />
      <AlertsPanel airframeLabel={label} config={config} onUpdated={setConfig} />
    </div>
  );

  if (trends.flight_count === 0) {
    return (
      <div className="mx-auto max-w-5xl space-y-8 px-4 py-8">
        {header}
        <p className="panel p-4 text-sm text-fg-muted">
          No flights tagged &quot;{label}&quot; yet. Upload a log with this airframe label to start its
          trend history; untagged flights expire after an hour. <Link href="/">Upload a flight</Link>
        </p>
        {panels}
      </div>
    );
  }

  const scorePoints: TrendSeriesPoint[] = flights.map((f, i) => ({ x: i, y: f.overall_score, label: f.file_name }));
  const moduleKeys = Array.from(new Set(flights.flatMap((f) => Object.keys(f.module_scores))));
  const metricKeys = Array.from(new Set(flights.flatMap((f) => Object.keys(f.key_metrics)))).sort();

  return (
    <div className="mx-auto max-w-5xl space-y-8 px-4 py-8">
      {header}

      <section aria-labelledby="overall-h" className="panel p-4">
        <h2 id="overall-h" className="mb-2 text-sm font-semibold">Overall health score</h2>
        <TrendLineChart points={scorePoints} yDomain={[0, 100]} digits={0} title="Overall score" />
      </section>

      <section aria-labelledby="modules-h" className="space-y-3">
        <h2 id="modules-h" className="text-base font-semibold">Module health over time</h2>
        <p className="text-xs text-fg-muted">Gaps are flights where the module was not assessed.</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {moduleKeys.map((mod) => {
            // missing or null = skipped / not assessed: a gap, never 100
            const points = flights.map((f, i) => {
              const v = f.module_scores[mod];
              return { x: i, y: typeof v === "number" ? v : null, label: f.file_name };
            });
            const latest = [...points].reverse().find((p) => p.y !== null)?.y ?? null;
            const name = MODULE_LABELS[mod] ?? mod;
            return (
              <div key={mod} className="panel p-3">
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{name}</h3>
                  <span className="num text-xs" style={latest !== null ? { color: scoreColour(latest) } : undefined}>
                    {latest === null ? "not assessed" : fmtScore(latest)}
                  </span>
                </div>
                <TrendLineChart points={points} yDomain={[0, 100]} height={110} digits={0} title={name} />
              </div>
            );
          })}
        </div>
      </section>

      {metricKeys.length > 0 && (
        <section aria-labelledby="metrics-h" className="space-y-3">
          <h2 id="metrics-h" className="text-base font-semibold">Raw metrics over time</h2>
          <p className="text-xs text-fg-muted">The numbers behind each score: a slow drift shows here before a finding fires.</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {metricKeys.map((key) => {
              const meta = humaniseMetricKey(key);
              const points = flights.map((f, i) => {
                const v = f.key_metrics[key];
                return { x: i, y: typeof v === "number" ? v : null, label: f.file_name };
              });
              return (
                <div key={key} className="panel p-3">
                  <h3 className="mb-1 text-sm font-semibold">{meta.label}</h3>
                  <TrendLineChart points={points} unit={meta.unit} digits={meta.digits} height={110} title={meta.label} />
                </div>
              );
            })}
          </div>
        </section>
      )}

      {panels}

      <section aria-labelledby="history-h" className="space-y-3">
        <h2 id="history-h" className="text-base font-semibold">Flight history</h2>
        <p className="text-xs text-fg-muted">Tick two flights to compare them.</p>
        <ul className="panel divide-y">
          {[...flights].reverse().map((f) => (
            <li key={f.report_id} className="flex items-center gap-3 px-3 py-2.5">
              <input
                type="checkbox"
                id={`sel-${f.report_id}`}
                checked={selected.includes(f.report_id)}
                onChange={() => toggleSelect(f.report_id)}
                className="h-4 w-4 shrink-0 accent-[var(--accent)] pointer-coarse:h-6 pointer-coarse:w-6"
              />
              <label htmlFor={`sel-${f.report_id}`} className="sr-only">Select {f.file_name} to compare</label>
              <div className="min-w-0 flex-1">
                <Link href={`/report/${encodeURIComponent(f.report_id)}`} className="block truncate text-sm font-medium text-fg hover:underline">
                  {f.file_name}
                </Link>
                <div className="text-xs text-fg-muted">Uploaded {fmtDateTime(new Date(f.created_at * 1000))}</div>
              </div>
              <span className={`num shrink-0 rounded-sm border px-1.5 py-px text-xs font-semibold ${TONE_CLASSES[scoreTone(f.overall_score)]}`}>
                {f.letter_grade} · {fmtScore(f.overall_score)}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
