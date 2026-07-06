"use client";

import { useState } from "react";
import type { AirframeConfigResponse } from "@/lib/types";
import { addMaintenanceEntry, updateAirframeConfig, airframeRecordPdfUrl } from "@/lib/api";
import { Wrench, Plus, X, Download, AlertTriangle, CheckCircle2 } from "lucide-react";

interface MaintenancePanelProps {
  airframeLabel: string;
  config: AirframeConfigResponse;
  onUpdated: (config: AirframeConfigResponse) => void;
}

export function MaintenancePanel({ airframeLabel, config, onUpdated }: MaintenancePanelProps) {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [type, setType] = useState("");
  const [notes, setNotes] = useState("");
  const [interval, setInterval_] = useState(config.maintenance_interval_hours?.toString() ?? "");
  const [checklist, setChecklist] = useState<string[]>(config.checklist_items);
  const [newItem, setNewItem] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAddEntry(e: React.FormEvent) {
    e.preventDefault();
    if (!type.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await addMaintenanceEntry(airframeLabel, { date, maintenance_type: type.trim(), notes: notes.trim() });
      onUpdated(updated);
      setType("");
      setNotes("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add maintenance entry.");
    } finally {
      setSaving(false);
    }
  }

  async function saveChecklistAndInterval() {
    setSaving(true);
    setError(null);
    try {
      const parsedInterval = interval.trim() ? parseFloat(interval) : null;
      const updated = await updateAirframeConfig(airframeLabel, {
        checklist_items: checklist,
        maintenance_interval_hours: parsedInterval,
      });
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  function addChecklistItem() {
    if (!newItem.trim()) return;
    setChecklist((prev) => [...prev, newItem.trim()]);
    setNewItem("");
  }

  function removeChecklistItem(idx: number) {
    setChecklist((prev) => prev.filter((_, i) => i !== idx));
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h3 className="font-semibold text-slate-100 flex items-center gap-2">
          <Wrench className="w-5 h-5 text-gold-500" />
          Maintenance
        </h3>
        <a
          href={airframeRecordPdfUrl(airframeLabel)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-700 text-slate-300 hover:text-white hover:border-slate-600 transition-colors"
          title="Download a flight & maintenance record PDF for your own recordkeeping"
        >
          <Download className="w-3.5 h-3.5" />
          Download Flight Record (PDF)
        </a>
      </div>

      {/* Status badge */}
      <div
        className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm ${
          config.maintenance_due
            ? "bg-orange-500/10 border border-orange-500/30 text-orange-300"
            : "bg-emerald-500/10 border border-emerald-500/30 text-emerald-300"
        }`}
      >
        {config.maintenance_due ? <AlertTriangle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
        {config.hours_since_maintenance.toFixed(1)}h since last maintenance
        {config.maintenance_interval_hours && ` (interval: ${config.maintenance_interval_hours}h)`}
        {config.maintenance_due && " — due for service"}
      </div>

      {error && <div className="text-xs text-red-400">{error}</div>}

      {/* Maintenance log */}
      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wide">Maintenance Log</h4>
        {config.maintenance_log.length === 0 ? (
          <p className="text-xs text-white/30">No entries logged yet.</p>
        ) : (
          <div className="divide-y divide-slate-800 border border-slate-800 rounded-lg overflow-hidden">
            {[...config.maintenance_log].reverse().map((m, i) => (
              <div key={i} className="p-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-slate-200">{m.maintenance_type}</span>
                  <span className="text-xs text-white/40 font-mono">{m.date}</span>
                </div>
                {m.notes && <p className="text-xs text-white/40 mt-1">{m.notes}</p>}
              </div>
            ))}
          </div>
        )}

        <form onSubmit={handleAddEntry} className="flex flex-wrap gap-2 pt-1">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="px-2.5 py-1.5 rounded-lg text-xs bg-slate-950 border border-slate-800 text-white/80"
          />
          <input
            type="text"
            value={type}
            onChange={(e) => setType(e.target.value)}
            placeholder="Type (e.g. Propeller replacement)"
            className="flex-1 min-w-[160px] px-2.5 py-1.5 rounded-lg text-xs bg-slate-950 border border-slate-800 text-white/80 placeholder:text-white/25"
          />
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notes (optional)"
            className="flex-1 min-w-[160px] px-2.5 py-1.5 rounded-lg text-xs bg-slate-950 border border-slate-800 text-white/80 placeholder:text-white/25"
          />
          <button
            type="submit"
            disabled={saving || !type.trim()}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white disabled:opacity-40 transition-all"
            style={{ background: "#B89642" }}
          >
            Log Entry
          </button>
        </form>
      </div>

      {/* Maintenance interval + checklist */}
      <div className="space-y-2 pt-2 border-t border-slate-800">
        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wide">Maintenance Interval (hours)</h4>
        <input
          type="number"
          min="0"
          step="0.5"
          value={interval}
          onChange={(e) => setInterval_(e.target.value)}
          placeholder="e.g. 20"
          className="w-32 px-2.5 py-1.5 rounded-lg text-xs bg-slate-950 border border-slate-800 text-white/80 placeholder:text-white/25"
        />
      </div>

      <div className="space-y-2">
        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wide">Pre-Flight Checklist</h4>
        {checklist.length === 0 ? (
          <p className="text-xs text-white/30">No checklist items yet.</p>
        ) : (
          <ul className="space-y-1.5">
            {checklist.map((item, i) => (
              <li key={i} className="flex items-center gap-2 text-sm text-slate-300">
                <span className="flex-1">{item}</span>
                <button onClick={() => removeChecklistItem(i)} className="text-white/30 hover:text-red-400 transition-colors">
                  <X className="w-3.5 h-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={newItem}
            onChange={(e) => setNewItem(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addChecklistItem())}
            placeholder="Add a checklist item…"
            className="flex-1 px-2.5 py-1.5 rounded-lg text-xs bg-slate-950 border border-slate-800 text-white/80 placeholder:text-white/25"
          />
          <button
            onClick={addChecklistItem}
            className="px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-slate-700 text-slate-300 hover:text-white transition-colors flex items-center gap-1"
          >
            <Plus className="w-3.5 h-3.5" />
            Add
          </button>
        </div>
        <button
          onClick={saveChecklistAndInterval}
          disabled={saving}
          className="mt-2 px-3 py-1.5 rounded-lg text-xs font-semibold text-white disabled:opacity-40 transition-all"
          style={{ background: "#B89642" }}
        >
          Save Checklist &amp; Interval
        </button>
      </div>
    </div>
  );
}
