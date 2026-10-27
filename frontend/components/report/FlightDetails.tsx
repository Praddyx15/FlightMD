"use client";

import { useMessages, useTranslations } from "next-intl";
import type { FlightMDReport } from "@/lib/types";
import { ModulePerformanceChart } from "@/components/charts/ModulePerformanceChart";
import { CopyText } from "@/components/shared/CopyText";
import { DASH, fmtDuration, fmtInt, fmtNum, fmtQty, fmtUtc, isNum, parseIsoDate } from "@/lib/format";
import { useUnits } from "@/lib/units";

function Item({ label, value, mono = false }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="rounded border bg-elevated px-2.5 py-2">
      <dt className="label">{label}</dt>
      <dd className={mono ? "num break-words text-xs" : "break-words text-sm"}>{value}</dd>
    </div>
  );
}

export function FlightDetails({ report }: { report: FlightMDReport }) {
  const t = useTranslations("details");
  const formats = useMessages().formats;
  const units = useUnits();
  const m = report.metadata;
  const w = m.weather;
  const flown = parseIsoDate(m.log_start_utc);
  const generated = parseIsoDate(report.generated_at);
  // the parser can repeat itself; one line per distinct message
  const warnings = Array.from(new Set(m.parse_warnings ?? []));
  // detector id -> readable name; an id we have no name for yet shows as is
  const known = m.source_format && typeof formats === "object" ? formats[m.source_format] : undefined;
  const format = typeof known === "string" ? known : m.source_format || null;

  return (
    <section id="details" aria-labelledby="details-h" className="scroll-mt-4 space-y-3">
      <h2 id="details-h" className="text-base font-semibold">{t("title")}</h2>

      <div className="panel p-4">
        <h3 className="label mb-2">{t("moduleScores")}</h3>
        <ModulePerformanceChart analyserResults={report.analyser_results} />
      </div>

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        <Item label={t("flightStart")} value={flown ? fmtUtc(flown) : DASH} mono />
        <Item label={t("duration")} value={fmtDuration(m.duration_seconds)} mono />
        <Item label={t("armEvents")} value={fmtInt(m.arm_count)} mono />
        <Item label={t("maxAltitude")} value={fmtQty(m.max_altitude_m, "altitude", units, 1)} mono />
        <Item label={t("maxSpeed")} value={fmtQty(m.max_speed_ms, "speed", units, 1)} mono />
        <Item label={t("distance")} value={fmtQty(m.total_distance_m, "distance", units, 0)} mono />
        <Item label={t("vehicle")} value={m.vehicle_type || DASH} />
        {m.airframe_name && <Item label={t("airframe")} value={m.airframe_name} />}
        <Item label={t("firmware")} value={m.firmware_version || m.px4_version || DASH} mono />
        <Item label={t("hardware")} value={m.hardware_id || DASH} mono />
        <Item label={t("modes")} value={m.flight_modes_used.length ? m.flight_modes_used.join(", ") : DASH} />
        {m.location_name && <Item label={t("location")} value={m.location_name} />}
        {w && (
          <Item
            label={t("weather")}
            value={[
              w.description,
              isNum(w.wind_speed_max_ms) ? t("windMax", { wind: fmtQty(w.wind_speed_max_ms, "speed", units, 1) }) : null,
              isNum(w.temperature_min_c) && isNum(w.temperature_max_c)
                ? t("tempRange", {
                    min: fmtQty(w.temperature_min_c, "temperature", units, 0),
                    max: fmtQty(w.temperature_max_c, "temperature", units, 0),
                  })
                : null,
            ].filter(Boolean).join(", ") || DASH}
          />
        )}
        {format && <Item label={t("logFormat")} value={format} />}
        {m.log_sha256 && <Item label={t("logHash")} value={<CopyText text={m.log_sha256} label={t("logHash")} />} mono />}
        <Item label={t("processedIn")} value={fmtNum(report.processing_time_ms / 1000, 1, "s")} mono />
        <Item label={t("schema")} value={report.schema_version} mono />
        {generated && <Item label={t("generated")} value={fmtUtc(generated)} mono />}
      </dl>

      {warnings.length > 0 && (
        <details className="text-xs text-fg-muted">
          <summary className="cursor-pointer">{t("parserWarnings", { count: warnings.length })}</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {warnings.map((msg) => (
              <li key={msg}>{msg}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
