"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { AlertTriangle, Database, Tag } from "lucide-react";
import { DropZone, LOG_EXTENSIONS, MAX_FILE_SIZE_MB } from "@/components/upload/DropZone";
import { UploadProgress } from "@/components/upload/UploadProgress";
import { RecentReports } from "@/components/home/RecentReports";
import { ScoreScale } from "@/components/shared/ScoreScale";
import { AirframeAuthError, uploadLog } from "@/lib/api";
import { addRecentReport } from "@/lib/storage";

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; progress: number }
  | { phase: "error"; message: string; airframe?: string };

const CHECKS = [
  ["Oscillation", "control-loop oscillation per axis, with the rate-P change to make"],
  ["Vibration", "IMU RMS and clipping per sensor"],
  ["EKF health", "innovation test ratios and solution flags"],
  ["Battery", "sag per cell under load"],
  ["GPS", "fix, satellites, HDOP, jamming"],
  ["Parameters", "known-bad and out-of-range values"],
  ["Motors / ESC", "balance, dropouts, saturation"],
];

export default function HomePage() {
  const router = useRouter();
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const [airframeLabel, setAirframeLabel] = useState("");
  const [contribute, setContribute] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function handleFile(file: File) {
    const name = file.name.toLowerCase();
    if (!LOG_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      setState({ phase: "error", message: "Unsupported file. Upload a PX4 (.ulg), ArduPilot (.bin) or MAVLink telemetry (.tlog) log." });
      return;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      setState({ phase: "error", message: `File too large. The limit is ${MAX_FILE_SIZE_MB} MB.` });
      return;
    }

    const label = airframeLabel.trim();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setState({ phase: "uploading", progress: 0 });

    try {
      const resp = await uploadLog(file, (pct) => setState({ phase: "uploading", progress: pct }), label, contribute, ctrl.signal);
      addRecentReport({ id: resp.report_id, fileName: file.name, uploadedAt: Date.now(), airframeLabel: label || null });
      router.push(`/report/${encodeURIComponent(resp.report_id)}`);
    } catch (err) {
      if (ctrl.signal.aborted) {
        setState({ phase: "idle" });
        return;
      }
      const message = err instanceof Error ? err.message : "Upload failed. Please try again.";
      setState({ phase: "error", message, airframe: err instanceof AirframeAuthError ? label : undefined });
    } finally {
      abortRef.current = null;
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-12 px-4 py-10">
      <section aria-labelledby="hero-h" className="space-y-6">
        <div>
          <h1 id="hero-h" className="text-hero font-semibold tracking-tight">Find out why your drone flew badly.</h1>
          <p className="mt-3 text-base text-fg-muted">
            Drop a PX4 .ulg, ArduPilot .bin or MAVLink .tlog. About 20 seconds later you get a scored
            report and the exact parameter changes to make. Deterministic, no account, untagged logs
            deleted after 1 hour.
          </p>
        </div>

        <div className="panel p-4 sm:p-6">
          {state.phase === "uploading" ? (
            <UploadProgress progress={state.progress} onCancel={() => abortRef.current?.abort()} />
          ) : (
            <div className="space-y-4">
              <DropZone onFile={handleFile} disabled={false} />

              {state.phase === "error" && (
                <div role="alert" className="flex items-start gap-2 rounded border border-critical-fill/50 bg-critical-fill/15 p-3 text-sm">
                  <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-critical" />
                  <div className="flex-1">
                    <p className="text-critical">{state.message}</p>
                    {state.airframe && (
                      <p className="mt-1 text-xs text-fg-muted">
                        If this is your airframe, paste its access token on the{" "}
                        <Link href={`/airframe/${encodeURIComponent(state.airframe)}`}>airframe page</Link>, then upload again.
                      </p>
                    )}
                  </div>
                  <button type="button" onClick={() => setState({ phase: "idle" })} className="btn shrink-0">
                    Dismiss
                  </button>
                </div>
              )}

              <div>
                <label htmlFor="airframe-label" className="mb-1 flex items-center gap-1.5 text-xs font-medium text-fg-muted">
                  <Tag aria-hidden className="h-3.5 w-3.5" />
                  Airframe label (optional)
                </label>
                <input
                  id="airframe-label"
                  type="text"
                  value={airframeLabel}
                  onChange={(e) => setAirframeLabel(e.target.value)}
                  placeholder="e.g. Quad-1"
                  maxLength={40}
                  aria-describedby="airframe-help"
                  className="input w-full"
                />
                <p id="airframe-help" className="mt-1 text-xs text-fg-muted">
                  Untagged flights expire after 1 hour. A label keeps this flight in that airframe&apos;s
                  trend history; the first time you manage a label you get an access token for it.
                </p>
              </div>

              <div className="flex items-start gap-2.5">
                <input
                  type="checkbox"
                  id="contribute-dataset"
                  checked={contribute}
                  onChange={(e) => setContribute(e.target.checked)}
                  aria-describedby="contribute-help"
                  className="mt-1 h-4 w-4 shrink-0 accent-[var(--accent)] pointer-coarse:h-6 pointer-coarse:w-6"
                />
                <div>
                  <label htmlFor="contribute-dataset" className="flex cursor-pointer items-center gap-1.5 text-sm font-medium">
                    <Database aria-hidden className="h-3.5 w-3.5 text-fg-muted" />
                    Contribute this log anonymously
                  </label>
                  <p id="contribute-help" className="text-xs text-fg-muted">
                    Saves a copy of the log and its report to FlightMD&apos;s open dataset to improve the
                    analysis. No name, account or source is stored. Off by default.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      <RecentReports />

      <section aria-labelledby="checks-h" className="space-y-3">
        <h2 id="checks-h" className="text-base font-semibold">What it checks</h2>
        <ul className="panel divide-y text-sm">
          {CHECKS.map(([name, what]) => (
            <li key={name} className="flex flex-col gap-0.5 px-3 py-2 sm:flex-row sm:gap-3">
              <span className="font-medium sm:w-32 sm:shrink-0">{name}</span>
              <span className="text-fg-muted">{what}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-fg-muted">
          Rockets and balloons also get an ascent &amp; recovery check. Checks the log has no data for
          are marked &quot;Not assessed&quot;.
        </p>
      </section>

      <section aria-labelledby="scoring-h" className="space-y-3">
        <h2 id="scoring-h" className="text-base font-semibold">How scoring works</h2>
        <ScoreScale />
      </section>
    </div>
  );
}
