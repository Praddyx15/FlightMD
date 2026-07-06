"use client";

import { useState } from "react";
import { pdfExportUrl, jsonExportUrl, gpxExportUrl, kmlExportUrl } from "@/lib/api";
import { copyToClipboard } from "@/lib/utils";

interface Props {
  reportId: string;
  fileName: string;
  hasGpsPath?: boolean;
}

export function ExportBar({ reportId, fileName, hasGpsPath }: Props) {
  const [copiedShare, setCopiedShare] = useState(false);

  async function handleShare() {
    await copyToClipboard(window.location.href);
    setCopiedShare(true);
    setTimeout(() => setCopiedShare(false), 2000);
  }

  return (
    <section>
      <h2 className="text-lg font-bold text-white/80 mb-4">Export</h2>
      <div
        className="rounded-2xl border border-border bg-card/85 p-4 flex flex-wrap gap-3 shadow-md backdrop-blur-md"
      >
        {/* PDF */}
        <a
          href={pdfExportUrl(reportId)}
          download={`flightmd_report_${reportId.slice(0, 8)}.pdf`}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all hover:opacity-90 hover:scale-[1.01]"
          style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
        >
          📄 Download PDF
          <span className="text-xs opacity-50">printable record</span>
        </a>

        {/* JSON */}
        <a
          href={jsonExportUrl(reportId)}
          download={`flightmd_report_${reportId.slice(0, 8)}.json`}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all hover:opacity-90 hover:scale-[1.01]"
          style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
        >
          📊 Download JSON
          <span className="text-xs opacity-50">raw data</span>
        </a>

        {/* GPX */}
        {hasGpsPath && (
          <a
            href={gpxExportUrl(reportId)}
            download={`flightmd_track_${reportId.slice(0, 8)}.gpx`}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all hover:opacity-90 hover:scale-[1.01]"
            style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
          >
            🛰️ Download GPX
            <span className="text-xs opacity-50">flight path</span>
          </a>
        )}

        {/* KML */}
        {hasGpsPath && (
          <a
            href={kmlExportUrl(reportId)}
            download={`flightmd_track_${reportId.slice(0, 8)}.kml`}
            className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all hover:opacity-90 hover:scale-[1.01]"
            style={{ background: "var(--bg-elevated)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
          >
            🌍 Download KML
            <span className="text-xs opacity-50">Google Earth</span>
          </a>
        )}

        {/* Share */}
        <button
          onClick={handleShare}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all hover:scale-[1.01]"
          style={{
            background: copiedShare ? "rgba(13,217,124,0.15)" : "var(--bg-elevated)",
            color: copiedShare ? "#0DD97C" : "var(--text-primary)",
            border: `1px solid ${copiedShare ? "#0DD97C55" : "var(--border)"}`,
          }}
        >
          {copiedShare ? "✓ Link copied!" : "🔗 Share Report"}
          {!copiedShare && <span className="text-xs opacity-50">expires in 1h</span>}
        </button>
      </div>
    </section>
  );
}
