"use client";

import { useState } from "react";
import { pdfExportUrl, jsonExportUrl } from "@/lib/api";
import { copyToClipboard } from "@/lib/utils";

interface Props {
  reportId: string;
  fileName: string;
}

export function ExportBar({ reportId, fileName }: Props) {
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
        className="rounded-xl border p-4 flex flex-wrap gap-3"
        style={{ background: "#0E1428", borderColor: "rgba(255,255,255,0.07)" }}
      >
        {/* PDF */}
        <a
          href={pdfExportUrl(reportId)}
          download={`flightmd_report_${reportId.slice(0, 8)}.pdf`}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all hover:opacity-90"
          style={{ background: "#1A3A5C", color: "#E8EDF5", border: "1px solid #2A5A8C" }}
        >
          📄 Download PDF
          <span className="text-xs opacity-50">DGCA compliant</span>
        </a>

        {/* JSON */}
        <a
          href={jsonExportUrl(reportId)}
          download={`flightmd_report_${reportId.slice(0, 8)}.json`}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all hover:opacity-90"
          style={{ background: "#141C35", color: "#E8EDF5", border: "1px solid rgba(255,255,255,0.1)" }}
        >
          📊 Download JSON
          <span className="text-xs opacity-50">raw data</span>
        </a>

        {/* Share */}
        <button
          onClick={handleShare}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all"
          style={{
            background: copiedShare ? "#0DD97C22" : "#141C35",
            color: copiedShare ? "#0DD97C" : "rgba(255,255,255,0.7)",
            border: `1px solid ${copiedShare ? "#0DD97C55" : "rgba(255,255,255,0.1)"}`,
          }}
        >
          {copiedShare ? "✓ Link copied!" : "🔗 Share Report"}
          {!copiedShare && <span className="text-xs opacity-50">expires in 1h</span>}
        </button>
      </div>
    </section>
  );
}
