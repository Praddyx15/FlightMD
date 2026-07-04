"use client";

import { useRouter } from "next/navigation";
import { useState, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { DropZone } from "@/components/upload/DropZone";
import { UploadProgress } from "@/components/upload/UploadProgress";
import { uploadLog, getReports } from "@/lib/api";
import { gradeColour, scoreColour } from "@/lib/utils";
import { FileText, Calendar, Clock, Cloud, ShieldCheck } from "lucide-react";
import { DroneScene } from "@/components/three/DroneScene";

gsap.registerPlugin(ScrollTrigger);

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; progress: number }
  | { phase: "error"; message: string };

interface ReportSummary {
  report_id: string;
  file_name: string;
  file_size_bytes: number;
  overall_score: number;
  score_label: string;
  letter_grade: string;
  duration_seconds: number;
  firmware_version: string;
  vehicle_type: string;
  weather_desc: string;
  created_at: number;
}

export default function HomePage() {
  const router = useRouter();
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const [history, setHistory] = useState<ReportSummary[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);

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
      const resp = await uploadLog(file, (pct) => {
        setState({ phase: "uploading", progress: pct });
      });
      router.push(`/report/${resp.report_id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Upload failed. Please try again.";
      setState({ phase: "error", message: msg });
    }
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
        <h1 className="text-4xl sm:text-5xl font-bold mb-4" style={{ color: "#E8EDF5" }}>
          Your drone&apos;s flight log,{" "}
          <span style={{ color: "#E8A020" }}>decoded.</span>
        </h1>
        <p className="text-lg text-white/60 max-w-xl mx-auto">
          Upload a PX4, ArduPilot, or MAVLink telemetry log.
          Get a deterministic diagnostic report in ~20 seconds — no AI required. Free, open-source, no login required.
        </p>
        <DroneScene
          className="w-full h-72 sm:h-96 -my-4"
          scrollProgress={droneScrollProgress}
        />
      </div>

      {/* Upload card */}
      <div
        className="rounded-xl border p-6 sm:p-8 shadow-2xl"
        style={{ background: "#0E1428", borderColor: "rgba(255,255,255,0.08)" }}
      >
        {state.phase === "uploading" ? (
          <UploadProgress progress={state.progress} />
        ) : (
          <>
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
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-slate-100 flex items-center space-x-2">
            <ShieldCheck className="w-5 h-5 text-indigo-400" />
            <span>Flight Log Hub</span>
          </h2>
          <span className="text-xs text-slate-400 font-mono">
            {history.length} {history.length === 1 ? 'flight' : 'flights'} logged
          </span>
        </div>

        {loadingHistory ? (
          <div className="text-center py-12 text-slate-500 text-sm">
            Loading flight logs...
          </div>
        ) : history.length === 0 ? (
          <div className="text-center py-12 bg-slate-900/50 border border-slate-800 rounded-xl text-slate-500 text-sm">
            No previously analysed logs. Upload your first flight log above.
          </div>
        ) : (
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-lg divide-y divide-slate-800">
            {history.map((item, idx) => (
              <motion.div
                key={item.report_id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: Math.min(idx * 0.04, 0.4) }}
                onClick={() => router.push(`/report/${item.report_id}`)}
                className="p-4 sm:p-5 hover:bg-slate-850 cursor-pointer transition-all duration-200 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
              >
                <div className="space-y-1.5 flex-1 min-w-0">
                  <div className="flex items-center space-x-2.5">
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
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-slate-400">
                    <span className="flex items-center space-x-1">
                      <Calendar className="w-3.5 h-3.5 text-slate-500" />
                      <span>{new Date(item.created_at * 1000).toLocaleDateString()}</span>
                    </span>
                    <span className="flex items-center space-x-1">
                      <Clock className="w-3.5 h-3.5 text-slate-500" />
                      <span>{(item.duration_seconds / 60).toFixed(1)} mins</span>
                    </span>
                    {item.weather_desc && item.weather_desc !== "N/A" && (
                      <span className="flex items-center space-x-1 max-w-[200px] sm:max-w-xs truncate">
                        <Cloud className="w-3.5 h-3.5 text-slate-500" />
                        <span className="truncate">{item.weather_desc}</span>
                      </span>
                    )}
                    <span className="font-mono text-slate-500">
                      {formatSize(item.file_size_bytes)}
                    </span>
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
      <div className="space-y-4">
        <h2 className="text-xl font-bold text-slate-100">Analysis Capabilities</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {MODULES.map((m) => (
            <div
              key={m.name}
              className="rounded-lg border p-3 text-center"
              style={{ background: "#0E1428", borderColor: "rgba(255,255,255,0.06)" }}
            >
              <div className="text-xl mb-1">{m.icon}</div>
              <div className="text-xs font-semibold text-white/70">{m.name}</div>
              <div className="text-xs text-white/35 mt-0.5">{m.weight}% weight</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const MODULES = [
  { name: "Oscillation",  icon: "〰️", weight: 20 },
  { name: "Vibration",    icon: "📳", weight: 20 },
  { name: "EKF Health",   icon: "🔭", weight: 20 },
  { name: "Battery",      icon: "🔋", weight: 15 },
  { name: "GPS Quality",  icon: "📡", weight: 15 },
  { name: "Parameters",   icon: "⚙️", weight:  5 },
  { name: "Motors / ESC", icon: "🔄", weight:  5 },
];
