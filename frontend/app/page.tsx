"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { DropZone } from "@/components/upload/DropZone";
import { UploadProgress } from "@/components/upload/UploadProgress";
import { uploadLog } from "@/lib/api";

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; progress: number }
  | { phase: "error"; message: string };

export default function HomePage() {
  const router = useRouter();
  const [state, setState] = useState<UploadState>({ phase: "idle" });

  async function handleFile(file: File) {
    // Client-side validation
    if (!file.name.toLowerCase().endsWith(".ulg")) {
      setState({ phase: "error", message: "Only PX4 ULog (.ulg) files are supported." });
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

  return (
    <div className="max-w-2xl mx-auto px-4 py-16 sm:py-24">
      {/* Hero */}
      <div className="text-center mb-12">
        <h1 className="text-4xl sm:text-5xl font-bold mb-4" style={{ color: "#E8EDF5" }}>
          Your drone&apos;s flight log,{" "}
          <span style={{ color: "#E8A020" }}>decoded.</span>
        </h1>
        <p className="text-lg text-white/60 max-w-xl mx-auto">
          Upload a PX4 <code className="mono text-sm bg-white/10 px-1.5 py-0.5 rounded">.ulg</code> file.
          Get an AI-powered diagnostic report in ~20 seconds. Free, open-source, no login required.
        </p>
      </div>

      {/* Upload card */}
      <div
        className="rounded-xl border p-6 sm:p-8"
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

      {/* What we analyse */}
      <div className="mt-12 grid grid-cols-2 sm:grid-cols-4 gap-3">
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

      {/* Privacy note */}
      <p className="text-center text-xs text-white/30 mt-8">
        Files are analysed in memory and never stored. Reports expire after 1 hour.
        Analysis cost ~$0.004 in AI tokens per flight log.
      </p>
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
  { name: "AI Report",    icon: "🤖", weight:  0 },
];
