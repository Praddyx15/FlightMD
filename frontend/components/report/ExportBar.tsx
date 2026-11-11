"use client";

import { useState } from "react";
import { Download, FileJson, FileText, Globe, Route, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { ApiError, downloadFile, gpxExportUrl, jsonExportUrl, kmlExportUrl, pdfExportUrl } from "@/lib/api";
import { useErrorText } from "@/lib/errors";

interface Props {
  reportId: string;
  fileName: string;
  hasGpsPath?: boolean;
}

type Kind = "pdf" | "json" | "gpx" | "kml";

export function ExportBar({ reportId, fileName, hasGpsPath }: Props) {
  const t = useTranslations("export");
  const errText = useErrorText();
  const [busy, setBusy] = useState<Kind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const base = fileName.replace(/\.[^.]+$/, "") || `flightmd_${reportId.slice(0, 8)}`;

  const items: { key: Kind; url: string; file: string; Icon: LucideIcon }[] = [
    { key: "pdf", url: pdfExportUrl(reportId), file: `${base}_flightmd.pdf`, Icon: FileText },
    { key: "json", url: jsonExportUrl(reportId), file: `${base}_flightmd.json`, Icon: FileJson },
  ];
  if (hasGpsPath) {
    items.push(
      { key: "gpx", url: gpxExportUrl(reportId), file: `${base}.gpx`, Icon: Route },
      { key: "kml", url: kmlExportUrl(reportId), file: `${base}.kml`, Icon: Globe }
    );
  }

  async function get(key: Kind, url: string, file: string) {
    setBusy(key);
    setError(null);
    setNote(null);
    try {
      await downloadFile(url, file);
    } catch (e) {
      // 501: this server has no PDF renderer; the print stylesheet is the same layout
      if (key === "pdf" && e instanceof ApiError && e.status === 501) {
        setNote(t("pdfFallback"));
        window.print();
      } else {
        setError(errText(e, "download"));
      }
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="export-h" className="no-print space-y-3">
      <h2 id="export-h" className="text-base font-semibold">{t("title")}</h2>
      <div className="flex flex-wrap gap-2">
        {items.map(({ key, url, file, Icon }) => (
          <button key={key} type="button" onClick={() => get(key, url, file)} disabled={busy !== null} className="btn">
            {busy === key ? <Download aria-hidden className="h-4 w-4 animate-pulse" /> : <Icon aria-hidden className="h-4 w-4" />}
            {key.toUpperCase()}
            <span className="text-xs text-fg-muted">{t(`hint.${key}`)}</span>
          </button>
        ))}
      </div>
      {error && <p role="alert" className="text-xs text-critical">{error}</p>}
      {note && <p role="status" className="text-xs text-fg-muted">{note}</p>}
      <p className="text-xs text-fg-muted">{t("note")}</p>
    </section>
  );
}
