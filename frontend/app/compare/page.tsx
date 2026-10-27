"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowRight, CheckCircle2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { getDiff, getReport } from "@/lib/api";
import type { DiffFlightSummary, DiffResponse, FlightMDReport } from "@/lib/types";
import { DASH, fmtDate, fmtNum, fmtScore, parseIsoDate } from "@/lib/format";
import { TONE_CLASSES, scoreColour } from "@/lib/utils";
import { useErrorText } from "@/lib/errors";
import { useLabels } from "@/lib/useLabels";
import { useUnits } from "@/lib/units";
import { SeverityIcon } from "@/components/shared/SeverityBadge";
import { DeltaBadge } from "@/components/shared/DeltaBadge";
import { FindingDiff } from "@/components/shared/FindingDiff";
import { guessAutopilot } from "@/lib/paramFile";

function Loading() {
  const t = useTranslations("compare");
  return <p className="px-4 py-20 text-center text-sm text-fg-muted">{t("loading")}</p>;
}

export default function ComparePage() {
  return (
    <Suspense fallback={<Loading />}>
      <ComparePageContent />
    </Suspense>
  );
}

type Side = FlightMDReport | null;

function ComparePageContent() {
  const t = useTranslations("compare");
  const ts = useTranslations("severity");
  const errText = useErrorText();
  const labels = useLabels();
  const units = useUnits();
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
      setError(t("needTwo"));
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
        setError(errText(diff.reason, "diff"));
      } else {
        setData(diff.value);
        setReports([repA, repB]);
      }
      setLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [a, b, router, t, errText]);

  if (loading) return <p className="px-4 py-20 text-center text-sm text-fg-muted" role="status">{t("comparing")}</p>;

  if (error || !data) {
    return (
      <div className="mx-auto max-w-xl px-4 py-20 text-center" role="alert">
        <h1 className="mb-2 flex items-center justify-center gap-2 text-value font-semibold">
          <AlertTriangle aria-hidden className="h-5 w-5 text-caution" />
          {t("failedTitle")}
        </h1>
        <p className="text-sm text-fg-muted">{error}</p>
        <Link href="/" className="btn mt-6">{t("home")}</Link>
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
  const first = datesKnown ? t("earlier") : t("flightA");
  const second = datesKnown ? t("later") : t("flightB");

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-4 py-8">
      <h1 className="text-value font-semibold">{t("title")}</h1>

      {mismatch && (
        <p role="note" className={`flex items-start gap-2 rounded border p-3 text-sm ${TONE_CLASSES.caution}`}>
          <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          {t("mismatch")}
        </p>
      )}
      {!datesKnown && <p className="text-xs text-fg-muted">{t("noDates")}</p>}

      <div className="grid grid-cols-1 items-center gap-3 sm:grid-cols-[1fr_auto_1fr]">
        <FlightCard flight={data.a} report={repA} heading={first} />
        <div className="flex flex-col items-center gap-1">
          <ArrowRight aria-hidden className="hidden h-5 w-5 text-fg-muted sm:block" />
          <DeltaBadge delta={data.overall_score_delta} />
        </div>
        <FlightCard flight={data.b} report={repB} heading={second} />
      </div>

      <section aria-labelledby="mod-h" className="panel overflow-x-auto">
        <h2 id="mod-h" className="border-b px-4 py-3 text-sm font-semibold">{t("modules")}</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th scope="col" className="label px-4 py-2">{t("module")}</th>
              <th scope="col" className="label px-3 py-2 text-right">{first}</th>
              <th scope="col" className="label px-3 py-2 text-right">{second}</th>
              <th scope="col" className="label px-4 py-2 text-right">{t("change")}</th>
            </tr>
          </thead>
          <tbody>
            {moduleRows.map(([mod, d]) => (
              <tr key={mod} className="border-t">
                <td className="px-4 py-2">{labels.module(mod)}</td>
                <td className="num px-3 py-2 text-right text-fg-muted">{d.a === null ? t("notAssessed") : fmtNum(d.a, 0)}</td>
                <td className="num px-3 py-2 text-right text-fg-muted">{d.b === null ? t("notAssessed") : fmtNum(d.b, 0)}</td>
                <td className="px-4 py-2 text-right"><DeltaBadge delta={d.delta} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {metricRows.length > 0 && (
        <section aria-labelledby="met-h" className="panel overflow-x-auto">
          <h2 id="met-h" className="border-b px-4 py-3 text-sm font-semibold">{t("metrics")}</h2>
          <p className="px-4 pt-2 text-xs text-fg-muted">{t("metricsNote")}</p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left">
                <th scope="col" className="label px-4 py-2">{t("metric")}</th>
                <th scope="col" className="label px-3 py-2 text-right">{first}</th>
                <th scope="col" className="label px-3 py-2 text-right">{second}</th>
                <th scope="col" className="label px-4 py-2 text-right">{t("change")}</th>
              </tr>
            </thead>
            <tbody>
              {metricRows.map(([key, d]) => (
                <tr key={key} className="border-t">
                  <td className="px-4 py-2">{labels.metric(key, units).label}</td>
                  <td className="num px-3 py-2 text-right text-fg-muted">{labels.format(key, d.a, units)}</td>
                  <td className="num px-3 py-2 text-right text-fg-muted">{labels.format(key, d.b, units)}</td>
                  <td className="num px-4 py-2 text-right text-xs">
                    {d.delta === null ? DASH : `${d.delta > 0 ? "+" : d.delta < 0 ? "−" : ""}${labels.format(key, Math.abs(d.delta), units)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <FindingDiff
          title={t("resolved")}
          icon={<CheckCircle2 aria-hidden className="h-4 w-4 text-ok" />}
          items={data.findings_diff.resolved}
          empty={datesKnown ? t("noneResolvedEarlier") : t("noneResolvedA")}
        />
        <FindingDiff
          title={t("new")}
          icon={<AlertTriangle aria-hidden className="h-4 w-4 text-caution" />}
          items={data.findings_diff.new}
          empty={datesKnown ? t("noneNewLater") : t("noneNewB")}
        />
      </div>

      {data.findings_diff.persisting_categories.length > 0 && (
        <section aria-labelledby="persist-h" className="panel p-4">
          <h2 id="persist-h" className="mb-2 text-sm font-semibold">{t("persisting")}</h2>
          <ul className="flex flex-wrap gap-2">
            {data.findings_diff.persisting_categories.map((p) => (
              <li key={p.category} className="flex items-center gap-1.5 rounded border px-2 py-1 text-xs">
                {labels.module(p.category)}:
                <SeverityIcon severity={p.severity_a} className="h-3.5 w-3.5" /> {ts(p.severity_a)}
                <ArrowRight aria-label={t("to")} className="h-3 w-3" />
                <SeverityIcon severity={p.severity_b} className="h-3.5 w-3.5" /> {ts(p.severity_b)}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function FlightCard({ flight, report, heading }: { flight: DiffFlightSummary; report: Side; heading: string }) {
  const t = useTranslations("compare");
  const flown = parseIsoDate(report?.metadata.log_start_utc);
  const vehicle = [report?.metadata.vehicle_type, report?.metadata.firmware_version].filter(Boolean).join(" · ");
  return (
    <Link href={`/report/${encodeURIComponent(flight.report_id)}`} className="panel block p-4 text-fg no-underline hover:border-fg-subtle">
      <div className="label mb-1">{heading}</div>
      <div className="truncate text-sm font-semibold">{flight.file_name}</div>
      <div className="num mt-2 text-value font-semibold" style={{ color: scoreColour(flight.overall_score) }}>
        {fmtScore(flight.overall_score)}
      </div>
      <div className="text-xs text-fg-muted">{t("scoreLine", { label: flight.score_label, grade: flight.letter_grade })}</div>
      <div className="mt-1 text-xs text-fg-muted">
        {flown ? t("flown", { date: fmtDate(flown) }) : t("dateUnknown")}
        {vehicle ? ` · ${vehicle}` : ""}
      </div>
    </Link>
  );
}
