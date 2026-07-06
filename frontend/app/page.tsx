"use client";

import { useRouter } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { DropZone } from "@/components/upload/DropZone";
import { UploadProgress } from "@/components/upload/UploadProgress";
import { uploadLog, getReports, type ReportSummary } from "@/lib/api";
import { gradeColour, scoreColour } from "@/lib/utils";
import { FileText, Calendar, Clock, Cloud, ShieldCheck, Tag, ArrowLeftRight, TrendingUp, Database } from "lucide-react";
import GradientText from "@/components/shared/GradientText";
import MagicBento from "@/components/shared/MagicBento";
import { ScoreScale } from "@/components/shared/ScoreScale";

gsap.registerPlugin(ScrollTrigger);

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; progress: number }
  | { phase: "error"; message: string };

export default function HomePage() {
  const router = useRouter();
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const [airframeLabel, setAirframeLabel] = useState("");
  const [contributeToDataset, setContributeToDataset] = useState(false);
  const [history, setHistory] = useState<ReportSummary[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [compareSelection, setCompareSelection] = useState<string[]>([]);

  const heroRef = useRef<HTMLDivElement>(null);
  const droneScrollProgress = useRef(0);

  // Drive the 3D drone's tilt/rise from scroll position through the hero —
  // read each frame by DroneModel's useFrame, not tweened directly, so it
  // never fights the model's own idle rotation for ownership of the object.
  useEffect(() => {
    if (!heroRef.current) return;
    const trigger = ScrollTrigger.create({
      trigger: heroRef.current,
      start: "top top",
      end: "bottom top",
      scrub: true,
      onUpdate: (self) => {
        droneScrollProgress.current = self.progress;
      },
    });
    return () => trigger.kill();
  }, []);

  useEffect(() => {
    async function loadHistory() {
      try {
        const data = await getReports();
        setHistory(data);
      } catch (err) {
        console.error("Failed to load flight history:", err);
      } finally {
        setLoadingHistory(false);
      }
    }
    loadHistory();
  }, []);

  const SUPPORTED_EXTENSIONS = [".ulg", ".ulog", ".bin", ".tlog"];

  async function handleFile(file: File) {
    const lowerName = file.name.toLowerCase();
    if (!SUPPORTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext))) {
      setState({
        phase: "error",
        message: "Unsupported file. Upload a PX4 (.ulg), ArduPilot (.bin), or MAVLink telemetry (.tlog) log.",
      });
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      setState({ phase: "error", message: "File too large. Maximum size is 50MB." });
      return;
    }

    setState({ phase: "uploading", progress: 0 });

    try {
      const resp = await uploadLog(
        file,
        (pct) => {
          setState({ phase: "uploading", progress: pct });
        },
        airframeLabel,
        contributeToDataset
      );
      router.push(`/report/${resp.report_id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload failed. Please try again.";
      setState({ phase: "error", message: msg });
    }
  }

  function toggleCompareSelection(reportId: string) {
    setCompareSelection((prev) => {
      if (prev.includes(reportId)) return prev.filter((id) => id !== reportId);
      if (prev.length >= 2) return [prev[1], reportId];
      return [...prev, reportId];
    });
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024 * 1024) {
      return `${(bytes / 1024).toFixed(1)} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-12 sm:py-16 space-y-12">
      {/* Hero */}
      <div ref={heroRef} className="text-center mb-8">
        <h1 className="text-4xl sm:text-5xl font-bold mb-4 text-slate-100 flex flex-col sm:flex-row items-center justify-center gap-2">
          <span>Your drone&apos;s flight log,</span>
          <GradientText
            colors={["#B89642", "#E7C25B", "#D1AE52"]}
            animationSpeed={6}
            showBorder={false}
            className="text-4xl sm:text-5xl font-bold"
          >
            decoded.
          </GradientText>
        </h1>
        <p className="text-lg text-white max-w-xl mx-auto">
          Upload a PX4, ArduPilot, or MAVLink telemetry log.
          Get a deterministic diagnostic report in ~20 seconds — no AI required. Free, open-source, no login required.
        </p>
      </div>

      {/* Upload card */}
      <div
        className="rounded-2xl border border-border bg-card/85 p-6 sm:p-8 shadow-2xl backdrop-blur-md"
      >
        {state.phase === "uploading" ? (
          <UploadProgress progress={state.progress} />
        ) : (
          <>
            <div className="mb-4">
              <label className="flex items-center gap-1.5 text-xs font-semibold text-white/50 mb-1.5">
                <Tag className="w-3.5 h-3.5" />
                Airframe label <span className="font-normal text-white/30">(optional)</span>
              </label>
              <input
                type="text"
                value={airframeLabel}
                onChange={(e) => setAirframeLabel(e.target.value)}
                placeholder="e.g. Quad-1 — tag it to track trends across flights"
                maxLength={40}
                className="w-full px-3 py-2 rounded-lg text-sm bg-slate-950 border border-slate-800 text-white/80 placeholder:text-white/25 focus:outline-none focus:border-gold-500/50"
              />
              <p className="text-xxs text-white/80 mt-1">
                Untagged flights stay ephemeral and expire in 1 hour, as always. Tagging
                opts this flight into permanent trend history under that label.
              </p>
            </div>
            <div className="mb-4 flex items-start gap-2.5 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2.5">
              <input
                type="checkbox"
                id="contribute-dataset"
                checked={contributeToDataset}
                onChange={(e) => setContributeToDataset(e.target.checked)}
                className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-700 bg-slate-900 accent-gold-500"
              />
              <label htmlFor="contribute-dataset" className="text-xxs text-white/70 cursor-pointer">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-white/50 mb-0.5">
                  <Database className="w-3.5 h-3.5" />
                  Contribute this log anonymously
                </span>
                Save a copy of this log and its analysis to FlightMD&apos;s open dataset, used to improve
                the analysis engine and, eventually, train a FlightMD model. No name, account, or upload
                source is stored with it — just the log file and its report. This is other people&apos;s
                flight data too, so it&apos;s opt-in and off by default; leave it unchecked if you&apos;d
                rather not share.
              </label>
            </div>
            <DropZone onFile={handleFile} disabled={false} />
            {state.phase === "error" && (
              <div className="mt-4 p-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-sm">
                {state.message}
                <button
                  onClick={() => setState({ phase: "idle" })}
                  className="ml-3 underline hover:no-underline"
                >
                  Try again
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Flight Log History Hub */}
      <div className="space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <h2 className="text-xl font-bold text-slate-100 flex items-center space-x-2">
            <ShieldCheck className="w-5 h-5 text-gold-500" />
            <span>Flight Log Hub</span>
          </h2>
          <div className="flex items-center gap-3">
            {compareSelection.length === 2 && (
              <button
                onClick={() => router.push(`/compare?a=${compareSelection[0]}&b=${compareSelection[1]}`)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-bg bg-accent hover:opacity-90 active:scale-95 transition-all"
              >
                <ArrowLeftRight className="w-3.5 h-3.5" />
                Compare Selected
              </button>
            )}
            <span className="text-xs text-slate-400 font-mono">
              {history.length} {history.length === 1 ? 'flight' : 'flights'} logged
            </span>
          </div>
        </div>

        {loadingHistory ? (
          <div className="text-center py-12 text-white/80 text-sm">
            Loading flight logs...
          </div>
        ) : history.length === 0 ? (
          <div className="text-center py-12 bg-card/40 border border-border rounded-xl text-white/80 text-sm">
            No previously analysed logs. Upload your first flight log above.
          </div>
        ) : (
          <div className="bg-card/40 border border-border rounded-xl overflow-hidden shadow-lg divide-y divide-border/60 backdrop-blur-sm">
            {history.map((item, idx) => (
              <motion.div
                key={item.report_id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, delay: Math.min(idx * 0.04, 0.4), ease: "easeOut" }}
                onClick={() => router.push(`/report/${item.report_id}`)}
                className="p-4 sm:p-5 hover:bg-elevated/40 hover:scale-[1.005] cursor-pointer transition-all duration-300 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
              >
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <input
                    type="checkbox"
                    checked={compareSelection.includes(item.report_id)}
                    onChange={() => toggleCompareSelection(item.report_id)}
                    onClick={(e) => e.stopPropagation()}
                    className="w-4 h-4 mt-1.5 accent-[#B89642] flex-shrink-0"
                    title="Select to compare"
                  />
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="flex items-center space-x-2.5 flex-wrap gap-y-1">
                      <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
                      <span className="font-semibold text-slate-200 truncate">{item.file_name}</span>
                      <span
                        className="px-2 py-0.5 rounded border text-xs font-bold"
                        style={{
                          color: gradeColour(item.letter_grade),
                          background: `${gradeColour(item.letter_grade)}1a`,
                          borderColor: `${gradeColour(item.letter_grade)}40`,
                        }}
                      >
                        Grade {item.letter_grade}
                      </span>
                      {item.airframe_label && (
                        <a
                          href={`/airframe/${encodeURIComponent(item.airframe_label)}`}
                          onClick={(e) => e.stopPropagation()}
                          className="flex items-center gap-1 px-2 py-0.5 rounded border text-xs font-semibold border-gold-500/40 bg-gold-500/15 text-gold-300 hover:bg-gold-500/25 transition-colors"
                          title="View trend history for this airframe"
                        >
                          <TrendingUp className="w-3 h-3" />
                          {item.airframe_label}
                        </a>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-white/80">
                      <span className="flex items-center space-x-1">
                        <Calendar className="w-3.5 h-3.5 text-slate-500" />
                        <span>{new Date(item.created_at * 1000).toLocaleDateString()}</span>
                      </span>
                      <span className="flex items-center space-x-1">
                        <Clock className="w-3.5 h-3.5 text-slate-500" />
                        <span>{(item.duration_seconds / 60).toFixed(1)} mins</span>
                      </span>
                      {item.weather_desc && item.weather_desc !== "N/A" && (
                        <span className="flex items-center gap-1">
                          <Cloud className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
                          <span>{item.weather_desc}</span>
                        </span>
                      )}
                      <span className="font-mono text-slate-500">
                        {formatSize(item.file_size_bytes)}
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center justify-between sm:justify-end space-x-4">
                  <div className="text-right">
                    <div className="text-sm font-semibold text-slate-300">
                      Score: <span style={{ color: scoreColour(item.overall_score) }}>{item.overall_score}%</span>
                    </div>
                    <span className="text-xxs text-slate-500 block uppercase tracking-wider">{item.score_label}</span>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>

      {/* What we analyse */}
      <div className="space-y-6">
        <h2 className="text-xl font-bold text-slate-100">Analysis Capabilities</h2>
        <MagicBento />
      </div>

      {/* Scoring scale */}
      <div className="space-y-4">
        <h2 className="text-xl font-bold text-slate-100">How Scoring Works</h2>
        <ScoreScale />
      </div>
    </div>
  );
}
