import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { getTranslations } from "next-intl/server";
import { fetchReportOnServer } from "@/lib/serverApi";
import { fmtScore, fmtUtc, parseIsoDate } from "@/lib/format";
import { isReportAssessed } from "@/lib/utils";
import { ReportDone } from "@/components/report/ReportDone";
import { ReportLive } from "@/components/report/ReportLive";
import { FailedProblem } from "@/components/report/Problem";

export const dynamic = "force-dynamic";

interface Props {
  params: { id: string };
}

// one API call per request, shared by the metadata and the page
const loadReport = cache(fetchReportOnServer);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const t = await getTranslations("meta.report");
  const res = await loadReport(params.id);
  const robots = { index: false, follow: false };

  if (res.kind !== "done") {
    return { title: t(res.kind === "missing" ? "missingTitle" : "pendingTitle"), robots };
  }

  const r = res.report;
  const m = r.metadata;
  const flown = parseIsoDate(m.log_start_utc);
  const vehicle = [m.vehicle_type, m.airframe_name].filter(Boolean).join(" · ") || t("unknownVehicle");
  const date = flown ? fmtUtc(flown) : t("unknownDate");
  const description = isReportAssessed(r)
    ? t("description", { score: fmtScore(r.overall_score), grade: r.letter_grade, vehicle, date })
    : t("descriptionNotAssessed", { vehicle, date });
  const title = `${r.file_name} · FlightMD`;

  return {
    title: r.file_name,
    description,
    robots,
    openGraph: { title, description, type: "article", siteName: "FlightMD" },
    twitter: { card: "summary", title, description },
  };
}

export default async function ReportPage({ params }: Props) {
  const res = await loadReport(params.id);

  if (res.kind === "missing") notFound();
  if (res.kind === "done") return <ReportDone report={res.report} />;
  if (res.kind === "failed") return <FailedProblem error={res.error} />;
  // still running, or the server couldn't reach the API: the browser polls
  return <ReportLive id={params.id} />;
}
