"use client";

import { useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Download, Plus, Wrench, X } from "lucide-react";
import { useTranslations } from "next-intl";
import type { AirframeConfigResponse } from "@/lib/types";
import { addMaintenanceEntry, downloadAirframeRecord, updateAirframeConfig } from "@/lib/api";
import { useErrorText } from "@/lib/errors";
import { fmtNum, localIsoDate } from "@/lib/format";
import { TONE_CLASSES } from "@/lib/utils";

interface MaintenancePanelProps {
  airframeLabel: string;
  config: AirframeConfigResponse;
  onUpdated: (config: AirframeConfigResponse) => void;
}

export function MaintenancePanel({ airframeLabel, config, onUpdated }: MaintenancePanelProps) {
  const t = useTranslations("maintenance");
  const errText = useErrorText();
  const num = (chunks: React.ReactNode) => <span className="num">{chunks}</span>;
  const [date, setDate] = useState(() => localIsoDate());
  const [type, setType] = useState("");
  const [notes, setNotes] = useState("");
  const [interval, setInterval_] = useState(config.maintenance_interval_hours?.toString() ?? "");
  const nextKey = useRef(0);
  const [checklist, setChecklist] = useState(() => config.checklist_items.map((text) => ({ key: nextKey.current++, text })));
  const [newItem, setNewItem] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function run(fn: () => Promise<AirframeConfigResponse>, fallback: string) {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      onUpdated(await fn());
      return true;
    } catch (err) {
      setError(errText(err, fallback));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function handleAddEntry(e: React.FormEvent) {
    e.preventDefault();
    if (!type.trim()) return;
    const ok = await run(
      () => addMaintenanceEntry(airframeLabel, { date, maintenance_type: type.trim(), notes: notes.trim() }),
      "maintenance"
    );
    if (ok) {
      setType("");
      setNotes("");
    }
  }

  async function saveSettings() {
    const hours = interval.trim() ? Number(interval) : null;
    if (hours !== null && (!Number.isFinite(hours) || hours < 0)) {
      setError(t("badInterval"));
      return;
    }
    const ok = await run(
      () => updateAirframeConfig(airframeLabel, {
        checklist_items: checklist.map((c) => c.text),
        maintenance_interval_hours: hours,
      }),
      "airframeUpdate"
    );
    if (ok) setSaved(true);
  }

  async function downloadRecord() {
    setError(null);
    try {
      await downloadAirframeRecord(airframeLabel);
    } catch (err) {
      setError(errText(err, "download"));
    }
  }

  function addChecklistItem() {
    const text = newItem.trim();
    if (!text) return;
    setChecklist((prev) => [...prev, { key: nextKey.current++, text }]);
    setNewItem("");
  }

  const due = config.maintenance_due;
  const StatusIcon = due ? AlertTriangle : CheckCircle2;

  return (
    <section aria-labelledby="maint-h" className="panel space-y-5 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="maint-h" className="flex items-center gap-2 text-base font-semibold">
          <Wrench aria-hidden className="h-4 w-4 text-accent" />
          {t("title")}
        </h2>
        <button type="button" onClick={downloadRecord} className="btn ml-auto text-xs">
          <Download aria-hidden className="h-4 w-4" />
          {t("record")}
        </button>
      </div>

      <p className={`flex items-center gap-2 rounded border px-3 py-2 text-sm ${TONE_CLASSES[due ? "caution" : "ok"]}`}>
        <StatusIcon aria-hidden className="h-4 w-4 shrink-0" />
        <span>
          {t.rich(due ? "due" : "ok", { num, hours: fmtNum(config.hours_since_maintenance, 1, "h") })}
          {config.maintenance_interval_hours != null && (
            <> {t.rich("interval", { num, hours: fmtNum(config.maintenance_interval_hours, 1, "h") })}</>
          )}
        </span>
      </p>

      {error && <p role="alert" className="text-xs text-critical">{error}</p>}

      <div className="space-y-2">
        <h3 className="label">{t("log")}</h3>
        {config.maintenance_log.length === 0 ? (
          <p className="text-xs text-fg-muted">{t("noEntries")}</p>
        ) : (
          <ul className="divide-y rounded border">
            {/* append-only log that is never reordered, so the position is a stable key */}
            {[...config.maintenance_log].reverse().map((m, i) => (
              // eslint-disable-next-line react/no-array-index-key
              <li key={`${m.date}-${i}`} className="p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{m.maintenance_type}</span>
                  <span className="num text-xs text-fg-muted">{m.date}</span>
                </div>
                {m.notes && <p className="mt-1 text-xs text-fg-muted">{m.notes}</p>}
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={handleAddEntry} className="grid grid-cols-1 gap-2 pt-1 sm:grid-cols-[auto_1fr]">
          <label className="sr-only" htmlFor="m-date">{t("date")}</label>
          <input id="m-date" type="date" value={date} onChange={(e) => setDate(e.target.value)} className="input num" />
          <label className="sr-only" htmlFor="m-type">{t("work")}</label>
          <input
            id="m-type"
            type="text"
            value={type}
            onChange={(e) => setType(e.target.value)}
            placeholder={t("workPlaceholder")}
            className="input"
          />
          <label className="sr-only" htmlFor="m-notes">{t("notes")}</label>
          <input
            id="m-notes"
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder={t("notesPlaceholder")}
            className="input sm:col-span-2"
          />
          <button type="submit" disabled={saving || !type.trim()} className="btn-primary sm:col-span-2 sm:justify-self-start">
            {t("logEntry")}
          </button>
        </form>
      </div>

      <div className="space-y-2 border-t pt-4">
        <label htmlFor="m-interval" className="label block">{t("intervalLabel")}</label>
        <input
          id="m-interval"
          type="number"
          inputMode="decimal"
          min="0"
          step="0.5"
          value={interval}
          onChange={(e) => setInterval_(e.target.value)}
          placeholder={t("intervalPlaceholder")}
          className="input num w-32"
        />
      </div>

      <div className="space-y-2">
        <h3 className="label">{t("checklist")}</h3>
        {checklist.length === 0 ? (
          <p className="text-xs text-fg-muted">{t("noItems")}</p>
        ) : (
          <ul className="space-y-1">
            {checklist.map((item) => (
              <li key={item.key} className="flex items-center gap-2 text-sm">
                <span className="flex-1">{item.text}</span>
                <button
                  type="button"
                  onClick={() => setChecklist((prev) => prev.filter((c) => c.key !== item.key))}
                  className="btn border-transparent bg-transparent px-2 text-fg-muted"
                  aria-label={t("removeItem", { item: item.text })}
                >
                  <X aria-hidden className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <label htmlFor="m-new-item" className="sr-only">{t("newItem")}</label>
          <input
            id="m-new-item"
            type="text"
            value={newItem}
            onChange={(e) => setNewItem(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addChecklistItem();
              }
            }}
            placeholder={t("newItemPlaceholder")}
            className="input min-w-0 flex-1"
          />
          <button type="button" onClick={addChecklistItem} className="btn">
            <Plus aria-hidden className="h-4 w-4" />
            {t("add")}
          </button>
        </div>
        <div className="flex items-center gap-3 pt-1">
          <button type="button" onClick={saveSettings} disabled={saving} className="btn-primary">
            {t("save")}
          </button>
          {saved && <span role="status" className="text-xs text-ok">{t("saved")}</span>}
        </div>
      </div>
    </section>
  );
}
