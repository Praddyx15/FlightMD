"use client";

import { useState } from "react";
import { Download, FileJson, FileText, Globe, Route, type LucideIcon } from "lucide-react";
import { downloadFile, gpxExportUrl, jsonExportUrl, kmlExportUrl, pdfExportUrl } from "@/lib/api";

interface Props {
  reportId: string;
  fileName: string;
  hasGpsPath?: boolean;
}

export function ExportBar({ reportId, fileName, hasGpsPath }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = fileName.replace(/\.[^.]+$/, "") || `flightmd_${reportId.slice(0, 8)}`;

  const items: { key: string; label: string; hint: string; url: string; file: string; Icon: LucideIcon }[] = [
    { key: "pdf", label: "PDF", hint: "printable record", url: pdfExportUrl(reportId), file: `${base}_flightmd.pdf`, Icon: FileText },
    { key: "json", label: "JSON", hint: "raw report", url: jsonExportUrl(reportId), file: `${base}_flightmd.json`, Icon: FileJson },
  ];
  if (hasGpsPath) {
    items.push(
      { key: "gpx", label: "GPX", hint: "flight path", url: gpxExportUrl(reportId), file: `${base}.gpx`, Icon: Route },
      { key: "kml", label: "KML", hint: "Google Earth", url: kmlExportUrl(reportId), file: `${base}.kml`, Icon: Globe }
    );
  }

  async function get(key: string, url: string, file: string) {
    setBusy(key);
    setError(null);
    try {
      await downloadFile(url, file);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="export-h" className="no-print space-y-3">
      <h2 id="export-h" className="text-base font-semibold">Export</h2>
      <div className="flex flex-wrap gap-2">
        {items.map(({ key, label, hint, url, file, Icon }) => (
          <button key={key} type="button" onClick={() => get(key, url, file)} disabled={busy !== null} className="btn">
            {busy === key ? <Download aria-hidden className="h-4 w-4 animate-pulse" /> : <Icon aria-hidden className="h-4 w-4" />}
            {label}
            <span className="text-xs text-fg-muted">{hint}</span>
          </button>
        ))}
      </div>
      {error && <p role="alert" className="text-xs text-critical">{error}</p>}
      <p className="text-xs text-fg-muted">The link to this page works for 1 hour unless the flight was tagged with an airframe label.</p>
    </section>
  );
}
