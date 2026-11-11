"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { AlertTriangle, Database, Tag } from "lucide-react";
import { useTranslations } from "next-intl";
import { DropZone, LOG_EXTENSIONS, MAX_FILE_SIZE_MB } from "@/components/upload/DropZone";
import { UploadProgress } from "@/components/upload/UploadProgress";
import { RecentReports } from "@/components/home/RecentReports";
import { ScoreScale } from "@/components/shared/ScoreScale";
import { AirframeAuthError, uploadLog } from "@/lib/api";
import { useErrorText } from "@/lib/errors";
import { addRecentReport } from "@/lib/storage";

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; progress: number }
  | { phase: "error"; message: string; airframe?: string };

const CHECKS = ["oscillation", "vibration", "ekf", "battery", "gps", "parameters", "motors"] as const;
const BRIEF_RE = /^[0-9a-f]{64}$/i;

export default function HomePage() {
  const t = useTranslations("home");
  const errText = useErrorText();
  const router = useRouter();
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const [airframeLabel, setAirframeLabel] = useState("");
  const [contribute, setContribute] = useState(false);
  const [brief, setBrief] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  async function handleFile(file: File) {
    const name = file.name.toLowerCase();
    if (!LOG_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      setState({ phase: "error", message: t("unsupported") });
      return;
    }
    if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
      setState({ phase: "error", message: t("tooLarge", { mb: MAX_FILE_SIZE_MB }) });
      return;
    }
    const planningBrief = brief.trim();
    if (planningBrief && !BRIEF_RE.test(planningBrief)) {
      setState({ phase: "error", message: t("badBrief") });
      return;
    }

    const label = airframeLabel.trim();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setState({ phase: "uploading", progress: 0 });

    try {
      const resp = await uploadLog(file, (pct) => setState({ phase: "uploading", progress: pct }), {
        airframeLabel: label,
        contribute,
        planningBrief,
        signal: ctrl.signal,
      });
      addRecentReport({
        id: resp.report_id,
        fileName: file.name,
        uploadedAt: Date.now(),
        airframeLabel: label || null,
        deduplicated: resp.deduplicated === true,
        contributionId: resp.contribution_id ?? null,
      });
      router.push(`/report/${encodeURIComponent(resp.report_id)}`);
    } catch (err) {
      if (ctrl.signal.aborted) {
        setState({ phase: "idle" });
        return;
      }
      setState({
        phase: "error",
        message: errText(err, "upload"),
        airframe: err instanceof AirframeAuthError ? label : undefined,
      });
    } finally {
      abortRef.current = null;
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-12 px-4 py-10">
      <section aria-labelledby="hero-h" className="space-y-6">
        <div>
          <h1 id="hero-h" className="text-hero font-semibold tracking-tight">{t("hero")}</h1>
          <p className="mt-3 text-base text-fg-muted">{t("intro")}</p>
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
                        {t.rich("tokenHint", {
                          link: (chunks) => <Link href={`/airframe/${encodeURIComponent(state.airframe ?? "")}`}>{chunks}</Link>,
                        })}
                      </p>
                    )}
                  </div>
                  <button type="button" onClick={() => setState({ phase: "idle" })} className="btn shrink-0">
                    {t("dismiss")}
                  </button>
                </div>
              )}

              <div>
                <label htmlFor="airframe-label" className="mb-1 flex items-center gap-1.5 text-xs font-medium text-fg-muted">
                  <Tag aria-hidden className="h-3.5 w-3.5" />
                  {t("airframeLabel")}
                </label>
                <input
                  id="airframe-label"
                  type="text"
                  value={airframeLabel}
                  onChange={(e) => setAirframeLabel(e.target.value)}
                  placeholder={t("airframePlaceholder")}
                  maxLength={40}
                  aria-describedby="airframe-help"
                  className="input w-full"
                />
                <p id="airframe-help" className="mt-1 text-xs text-fg-muted">{t("airframeHelp")}</p>
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
                    {t("contribute")}
                  </label>
                  <p id="contribute-help" className="text-xs text-fg-muted">{t("contributeHelp")}</p>
                </div>
              </div>

              <details className="text-xs text-fg-muted">
                <summary className="cursor-pointer">{t("briefSummary")}</summary>
                <div className="mt-2 space-y-1">
                  <label htmlFor="planning-brief" className="block font-medium">{t("briefLabel")}</label>
                  <input
                    id="planning-brief"
                    type="text"
                    value={brief}
                    onChange={(e) => setBrief(e.target.value)}
                    spellCheck={false}
                    autoComplete="off"
                    maxLength={64}
                    placeholder={t("briefPlaceholder")}
                    aria-describedby="brief-help"
                    className="input num w-full"
                  />
                  <p id="brief-help">{t("briefHelp")}</p>
                </div>
              </details>
            </div>
          )}
        </div>
      </section>

      <RecentReports />

      <section aria-labelledby="checks-h" className="space-y-3">
        <h2 id="checks-h" className="text-base font-semibold">{t("checksTitle")}</h2>
        <ul className="panel divide-y text-sm">
          {CHECKS.map((c) => (
            <li key={c} className="flex flex-col gap-0.5 px-3 py-2 sm:flex-row sm:gap-3">
              <span className="font-medium sm:w-32 sm:shrink-0">{t(`checks.${c}.name`)}</span>
              <span className="text-fg-muted">{t(`checks.${c}.what`)}</span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-fg-muted">{t("checksNote")}</p>
      </section>

      <section aria-labelledby="scoring-h" className="space-y-3">
        <h2 id="scoring-h" className="text-base font-semibold">{t("scoringTitle")}</h2>
        <ScoreScale />
      </section>
    </div>
  );
}
