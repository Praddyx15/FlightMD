"use client";

import { useState } from "react";
import type { AirframeConfigResponse, AlertRule } from "@/lib/types";
import { updateAirframeConfig } from "@/lib/api";
import { Bell, Plus, X } from "lucide-react";

interface AlertsPanelProps {
  airframeLabel: string;
  config: AirframeConfigResponse;
  onUpdated: (config: AirframeConfigResponse) => void;
}

const METRIC_OPTIONS = [
  { value: "overall_score", label: "Overall Score" },
  { value: "module.oscillation", label: "Oscillation Module Score" },
  { value: "module.vibration", label: "Vibration Module Score" },
  { value: "module.ekf", label: "EKF Module Score" },
  { value: "module.battery", label: "Battery Module Score" },
  { value: "module.gps", label: "GPS Module Score" },
  { value: "module.motors", label: "Motors Module Score" },
  { value: "oscillation.roll_peak_hz", label: "Roll Oscillation Frequency" },
  { value: "battery.sag_per_cell_v", label: "Battery Sag per Cell" },
  { value: "gps.max_hdop", label: "Max GPS HDOP" },
  { value: "gps.min_satellites", label: "Min Satellites Tracked" },
  { value: "vibration.max_imu_rms", label: "Max IMU Vibration" },
];

function emptyRule(): AlertRule {
  return { metric: "overall_score", comparison: "lt", threshold: 70, label: "" };
}

export function AlertsPanel({ airframeLabel, config, onUpdated }: AlertsPanelProps) {
  const [rules, setRules] = useState<AlertRule[]>(config.alert_rules.length ? config.alert_rules : []);
  const [webhookUrl, setWebhookUrl] = useState(config.webhook_url ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function updateRule(idx: number, patch: Partial<AlertRule>) {
    setRules((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  }

  function removeRule(idx: number) {
    setRules((prev) => prev.filter((_, i) => i !== idx));
  }

  async function save() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateAirframeConfig(airframeLabel, {
        alert_rules: rules,
        webhook_url: webhookUrl.trim() || null,
      });
      onUpdated(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save alert rules.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <h3 className="font-semibold text-slate-100 flex items-center gap-2">
        <Bell className="w-5 h-5 text-indigo-400" />
        Alerts
      </h3>
      <p className="text-xs text-white/40 -mt-2">
        When a new tagged flight breaches a rule below, FlightMD posts a message to your webhook URL
        (Slack/Discord-compatible). No account or email needed — just point it at a webhook you control.
      </p>

      {error && <div className="text-xs text-red-400">{error}</div>}
      {saved && <div className="text-xs text-emerald-400">Saved.</div>}

      <div className="space-y-2">
        {rules.map((rule, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 bg-slate-950 border border-slate-800 rounded-lg p-2.5">
            <select
              value={rule.metric}
              onChange={(e) => updateRule(i, { metric: e.target.value })}
              className="px-2 py-1.5 rounded-md text-xs bg-slate-900 border border-slate-800 text-white/80"
            >
              {METRIC_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <select
              value={rule.comparison}
              onChange={(e) => updateRule(i, { comparison: e.target.value as "lt" | "gt" })}
              className="px-2 py-1.5 rounded-md text-xs bg-slate-900 border border-slate-800 text-white/80"
            >
              <option value="lt">below</option>
              <option value="gt">above</option>
            </select>
            <input
              type="number"
              step="any"
              value={rule.threshold}
              onChange={(e) => updateRule(i, { threshold: parseFloat(e.target.value) || 0 })}
              className="w-24 px-2 py-1.5 rounded-md text-xs bg-slate-900 border border-slate-800 text-white/80"
            />
            <input
              type="text"
              value={rule.label}
              onChange={(e) => updateRule(i, { label: e.target.value })}
              placeholder="Description (optional)"
              className="flex-1 min-w-[120px] px-2 py-1.5 rounded-md text-xs bg-slate-900 border border-slate-800 text-white/80 placeholder:text-white/25"
            />
            <button onClick={() => removeRule(i)} className="text-white/30 hover:text-red-400 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
        <button
          onClick={() => setRules((prev) => [...prev, emptyRule()])}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-700 text-slate-300 hover:text-white transition-colors"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Rule
        </button>
      </div>

      <div className="space-y-1.5 pt-2 border-t border-slate-800">
        <h4 className="text-xs font-semibold text-white/50 uppercase tracking-wide">Webhook URL</h4>
        <input
          type="url"
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder="https://discord.com/api/webhooks/... or https://hooks.slack.com/..."
          className="w-full px-2.5 py-1.5 rounded-lg text-xs bg-slate-950 border border-slate-800 text-white/80 placeholder:text-white/25"
        />
        <p className="text-xxs text-white/25">Must be https:// and resolve to a public address.</p>
      </div>

      <button
        onClick={save}
        disabled={saving}
        className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white disabled:opacity-40 transition-all"
        style={{ background: "#E8A020" }}
      >
        Save Alert Rules
      </button>
    </div>
  );
}
