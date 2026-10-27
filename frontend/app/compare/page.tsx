"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowDown, ArrowRight, ArrowUp, CheckCircle2, Minus } from "lucide-react";
import { getDiff, getReport } from "@/lib/api";
import type { DiffFlightSummary, DiffResponse, FlightMDReport } from "@/lib/types";
import { MODULE_LABELS, formatMetric, humaniseMetricKey } from "@/lib/metricLabels";
import { DASH, fmtDate, fmtNum, fmtScore, parseIsoDate } from "@/lib/format";
import { SEVERITY_LABELS, TONE_CLASSES, scoreColour } from "@/lib/utils";
import { SeverityIcon } from "@/components/shared/SeverityBadge";
import { guessAutopilot } from "@/lib/paramFile";

function DeltaBadge({ delta }: { delta: number | null }) {
  if (delta === null) return <span className="text-xs text-fg-muted">{DASH}</span>;
  if (Math.abs(delta) < 0.5) {
    return (
      <span className="num inline-flex items-center gap-1 text-xs text-fg-muted">
        <Minus aria-hidden className="h-3 w-3" /> no change
      </span>
    );
  }
  const better = delta > 0;
  const Icon = better ? ArrowUp : ArrowDown;
  return (
    <span className={`num inline-flex items-center gap-1 text-xs font-semibold ${better ? "text-ok" : "text-caution"}`}>
      <Icon aria-hidden className="h-3 w-3" />
      {better ? "+" : "−"}
      {fmtNum(Math.abs(delta), 0)} {better ? "better" : "worse"}
    </span>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<p className="px-4 py-20 text-center text-sm text-fg-muted">Loading…</p>}>
      <ComparePageContent />
    </Suspense>
  );
}

type Side = FlightMDReport | null;

function ComparePageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const a = searchParams.get("a");
  const b = searchParams.get("b");

  const [data, setData] = useState<DiffResponse | null>(null);
  const [reports, setReports] = useState<[Side, Side]>([null, null]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!a || !b) {
      setError("Two report ids are needed: /compare?a=…&b=…");
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      // the full reports are only for dates and vehicle; the comparison works without them
      const [diff, ra, rb] = await Promise.allSettled([getDiff(a, b), getReport(a), getReport(b)]);
      if (cancelled) return;
      // console.log(diff.status, ra.status, rb.status);
      const repA = ra.status === "fulfilled" ? ra.value : null;
      const repB = rb.status === "fulfilled" ? rb.value : null;

      const da = parseIsoDate(repA?.metadata.log_start_utc);
      const db = parseIsoDate(repB?.metadata.log_start_utc);
      if (da && db && da > db) {
        // "before" must be the earlier flight, not the first one ticked
        router.replace(`/compare?a=${encodeURIComponent(b)}&b=${encodeURIComponent(a)}`);
        return;
      }

      if (diff.status === "rejected") {
        setError(diff.reason instanceof Error ? diff.reason.message : "Could not compare these flights.");
      } else {
        setData(diff.value);
        setReports([repA, repB]);
      }
      setLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [a, b, router]);

  if (loading) return <p className="px-4 py-20 text-center text-sm text-fg-muted" role="status">Comparing flights…</p>;

  if (error || !data) {
    return (
      <div className="mx-auto max-w-xl px-4 py-20 text-center" role="alert">
        <h1 className="mb-2 flex items-center justify-center gap-2 text-value font-semibold">
          <AlertTriangle aria-hidden className="h-5 w-5 text-caution" />
          Could not compare
        </h1>
        <p className="text-sm text-fg-muted">{error}</p>
        <Link href="/" className="btn mt-6">Home</Link>
      </div>
    );
  }

  const [repA, repB] = reports;
  const datesKnown = !!parseIsoDate(repA?.metadata.log_start_utc) && !!parseIsoDate(repB?.metadata.log_start_utc);
  const apA = repA ? guessAutopilot(repA) : null;
  const apB = repB ? guessAutopilot(repB) : null;
  const mismatch =
    (apA && apB && apA !== apB) ||
    (repA?.metadata.vehicle_type && repB?.metadata.vehicle_type && repA.metadata.vehicle_type !== repB.metadata.vehicle_type);

  const moduleRows = Object.entries(data.module_score_deltas);
  const metricRows = Object.entries(data.key_metric_deltas);
  const first = datesKnown ? "Earlier" : "Flight A";
  const second = datesKnown ? "Later" : "Flight B";

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-4 py-8">
      <h1 className="text-value font-semibold">Flight comparison</h1>

      {mismatch && (
        <p role="note" className={`flex items-start gap-2 rounded border p-3 text-sm ${TONE_CLASSES.caution}`}>
          <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          These flights are from different vehicles or autopilots, so the module scores are not directly comparable.
        </p>
      )}
      {!datesKnown && (
        <p className="text-xs text-fg-muted">
          The flight date is missing from at least one log, so A and B are in the order you picked them.
        </p>
      )}

      <div className="grid grid-cols-1 items-center gap-3 sm:grid-cols-[1fr_auto_1fr]">
        <FlightCard flight={data.a} report={repA} heading={first} />
        <div className="flex flex-col items-center gap-1">
          <ArrowRight aria-hidden className="hidden h-5 w-5 text-fg-muted sm:block" />
          <DeltaBadge delta={data.overall_score_delta} />
        </div>
        <FlightCard flight={data.b} report={repB} heading={second} />
      </div>

      <section aria-labelledby="mod-h" className="panel overflow-x-auto">
        <h2 id="mod-h" className="border-b px-4 py-3 text-sm font-semibold">Module scores</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col" className="label px-4 py-2">Module</th>
              <th scope="col" className="label px-3 py-2 text-right">{first}</th>
              <th scope="col" className="label px-3 py-2 text-right">{second}</th>
              <th scope="col" className="label px-4 py-2 text-right">Change</th>
            </tr>
          </thead>
          <tbody>
            {moduleRows.map(([mod, d]) => (
              <tr key={mod} className="border-t">
                <td className="px-4 py-2">{MODULE_LABELS[mod] ?? mod}</td>
                <td className="num px-3 py-2 text-right text-fg-muted">{d.a === null ? "not assessed" : fmtNum(d.a, 0)}</td>
                <td className="num px-3 py-2 text-right text-fg-muted">{d.b === null ? "not assessed" : fmtNum(d.b, 0)}</td>
                <td className="px-4 py-2 text-right"><DeltaBadge delta={d.delta} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {metricRows.length > 0 && (
        <section aria-labelledby="met-h" className="panel overflow-x-auto">
          <h2 id="met-h" className="border-b px-4 py-3 text-sm font-semibold">Raw metrics</h2>
          <p className="px-4 pt-2 text-xs text-fg-muted">Higher is not always better here (HDOP, vibration), so changes are shown without colour.</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th scope="col" className="label px-4 py-2">Metric</th>
                <th scope="col" className="label px-3 py-2 text-right">{first}</th>
                <th scope="col" className="label px-3 py-2 text-right">{second}</th>
                <th scope="col" className="label px-4 py-2 text-right">Change</th>
              </tr>
            </thead>
            <tbody>
              {metricRows.map(([key, d]) => (
                <tr key={key} className="border-t">
                  <td className="px-4 py-2">{humaniseMetricKey(key).label}</td>
                  <td className="num px-3 py-2 text-right text-fg-muted">{formatMetric(key, d.a)}</td>
                  <td className="num px-3 py-2 text-right text-fg-muted">{formatMetric(key, d.b)}</td>
                  <td className="num px-4 py-2 text-right text-xs">
                    {d.delta === null ? DASH : `${d.delta > 0 ? "+" : d.delta < 0 ? "−" : ""}${formatMetric(key, Math.abs(d.delta))}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <FindingDiff
          title="Resolved"
          icon={<CheckCircle2 aria-hidden className="h-4 w-4 text-ok" />}
          items={data.findings_diff.resolved}
          empty={`No finding from the ${first.toLowerCase()} flight went away.`}
        />
        <FindingDiff
          title="New"
          icon={<AlertTriangle aria-hidden className="h-4 w-4 text-caution" />}
          items={data.findings_diff.new}
          empty={`No new findings in the ${second.toLowerCase()} flight.`}
        />
      </div>

      {data.findings_diff.persisting_categories.length > 0 && (
        <section aria-labelledby="persist-h" className="panel p-4">
          <h2 id="persist-h" className="mb-2 text-sm font-semibold">Still present</h2>
          <ul className="flex flex-wrap gap-2">
            {data.findings_diff.persisting_categories.map((p) => (
              <li key={p.category} className="flex items-center gap-1.5 rounded border px-2 py-1 text-xs">
                {MODULE_LABELS[p.category] ?? p.category}:
                <SeverityIcon severity={p.severity_a} className="h-3.5 w-3.5" /> {SEVERITY_LABELS[p.severity_a]}
                <ArrowRight aria-label="to" className="h-3 w-3" />
                <SeverityIcon severity={p.severity_b} className="h-3.5 w-3.5" /> {SEVERITY_LABELS[p.severity_b]}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function FindingDiff({ title, icon, items, empty }: { title: string; icon: React.ReactNode; items: string[]; empty: string }) {
  return (
    <section className="panel p-4">
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title} <span className="num font-normal text-fg-muted">({items.length})</span>
      </h2>
      {items.length === 0 ? (
        <p className="text-xs text-fg-muted">{empty}</p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {items.map((t, i) => <li key={`${t}-${i}`}>{t}</li>)}
        </ul>
      )}
    </section>
  );
}

function FlightCard({ flight, report, heading }: { flight: DiffFlightSummary; report: Side; heading: string }) {
  const flown = parseIsoDate(report?.metadata.log_start_utc);
  const vehicle = [report?.metadata.vehicle_type, report?.metadata.firmware_version].filter(Boolean).join(" · ");
  return (
    <Link href={`/report/${encodeURIComponent(flight.report_id)}`} className="panel block p-4 text-fg no-underline hover:border-fg-subtle">
      <div className="label mb-1">{heading}</div>
      <div className="truncate text-sm font-semibold">{flight.file_name}</div>
      <div className="mt-2 num text-value font-semibold" style={{ color: scoreColour(flight.overall_score) }}>
        {fmtScore(flight.overall_score)}
      </div>
      <div className="text-xs text-fg-muted">
        {flight.score_label} · Grade {flight.letter_grade}
      </div>
      <div className="mt-1 text-xs text-fg-muted">
        {flown ? `Flown ${fmtDate(flown)}` : "Flight date unknown"}
        {vehicle ? ` · ${vehicle}` : ""}
      </div>
    </Link>
  );
}
