import type { FlightMDReport } from "@/lib/types";
import { ModulePerformanceChart } from "@/components/charts/ModulePerformanceChart";
import { DASH, fmtDuration, fmtInt, fmtNum, isNum, parseIsoDate, fmtUtc } from "@/lib/format";

function Item({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded border bg-elevated px-2.5 py-2">
      <dt className="label">{label}</dt>
      <dd className={mono ? "num break-words text-xs" : "break-words text-sm"}>{value}</dd>
    </div>
  );
}

export function FlightDetails({ report }: { report: FlightMDReport }) {
  const m = report.metadata;
  const w = m.weather;
  const flown = parseIsoDate(m.log_start_utc);
  const warnings = m.parse_warnings ?? [];

  return (
    <section id="details" aria-labelledby="details-h" className="scroll-mt-4 space-y-3">
      <h2 id="details-h" className="text-base font-semibold">Flight details</h2>

      <div className="panel p-4">
        <h3 className="label mb-2">Module scores</h3>
        <ModulePerformanceChart analyserResults={report.analyser_results} />
      </div>

      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
        <Item label="Flight start" value={flown ? fmtUtc(flown) : DASH} mono />
        <Item label="Duration" value={fmtDuration(m.duration_seconds)} mono />
        <Item label="Arm events" value={fmtInt(m.arm_count)} mono />
        <Item label="Max altitude" value={fmtNum(m.max_altitude_m, 1, "m")} mono />
        <Item label="Max speed" value={fmtNum(m.max_speed_ms, 1, "m/s")} mono />
        <Item label="Distance" value={fmtNum(m.total_distance_m, 0, "m")} mono />
        <Item label="Vehicle" value={m.vehicle_type || DASH} />
        <Item label="Firmware" value={m.firmware_version || m.px4_version || DASH} mono />
        <Item label="Hardware" value={m.hardware_id || DASH} mono />
        <Item label="Flight modes" value={m.flight_modes_used.length ? m.flight_modes_used.join(", ") : DASH} />
        {m.location_name && <Item label="Location" value={m.location_name} />}
        {w && (
          <Item
            label="Weather (day)"
            value={[
              w.description,
              isNum(w.wind_speed_max_ms) ? `wind max ${fmtNum(w.wind_speed_max_ms, 1, "m/s")}` : null,
              isNum(w.temperature_min_c) && isNum(w.temperature_max_c)
                ? `${fmtNum(w.temperature_min_c, 0)} to ${fmtNum(w.temperature_max_c, 0, "°C")}`
                : null,
            ].filter(Boolean).join(", ") || DASH}
          />
        )}
        <Item label="Processed in" value={fmtNum(report.processing_time_ms / 1000, 1, "s")} mono />
        <Item label="Schema" value={report.schema_version} mono />
      </dl>

      {warnings.length > 0 && (
        <details className="text-xs text-fg-muted">
          <summary className="cursor-pointer">
            {warnings.length} parser {warnings.length === 1 ? "warning" : "warnings"}: parts of the log that were skipped or repaired
          </summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {warnings.map((msg, i) => (
              <li key={i}>{msg}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
