"use client";

import { useRef, useState } from "react";
import { Bell, Plus, X } from "lucide-react";
import type { AirframeConfigResponse, AlertRule } from "@/lib/types";
import { updateAirframeConfig } from "@/lib/api";

interface AlertsPanelProps {
  airframeLabel: string;
  config: AirframeConfigResponse;
  onUpdated: (config: AirframeConfigResponse) => void;
}

const METRIC_OPTIONS = [
  { value: "overall_score", label: "Overall score" },
  { value: "module.oscillation", label: "Oscillation module score" },
  { value: "module.vibration", label: "Vibration module score" },
  { value: "module.ekf", label: "EKF module score" },
  { value: "module.battery", label: "Battery module score" },
  { value: "module.gps", label: "GPS module score" },
  { value: "module.motors", label: "Motors module score" },
  { value: "oscillation.roll_peak_hz", label: "Roll oscillation frequency (Hz)" },
  { value: "battery.sag_per_cell_v", label: "Battery sag per cell (V)" },
  { value: "gps.max_hdop", label: "Max GPS HDOP" },
  { value: "gps.min_satellites", label: "Min satellites tracked" },
  { value: "vibration.max_imu_rms", label: "Max IMU vibration (m/s²)" },
];

// threshold stays a string while typing so "0." or "-" don't snap to 0
interface Row extends Omit<AlertRule, "threshold"> {
  key: number;
  threshold: string;
}

export function AlertsPanel({ airframeLabel, config, onUpdated }: AlertsPanelProps) {
  const nextKey = useRef(0);
  const toRow = (r: AlertRule): Row => ({ ...r, threshold: String(r.threshold), key: nextKey.current++ });
  const [rules, setRules] = useState<Row[]>(() => config.alert_rules.map(toRow));
  const [webhookUrl, setWebhookUrl] = useState(config.webhook_url ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function updateRule(key: number, patch: Partial<Row>) {
    setRules((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
    setSaved(false);
  }

  async function save() {
    const parsed: AlertRule[] = [];
    for (const r of rules) {
      const n = Number(r.threshold);
      if (r.threshold.trim() === "" || !Number.isFinite(n)) {
        setError(`Threshold for "${METRIC_OPTIONS.find((o) => o.value === r.metric)?.label ?? r.metric}" is not a number.`);
        return;
      }
      parsed.push({ metric: r.metric, comparison: r.comparison, threshold: n, label: r.label });
    }
    const url = webhookUrl.trim();
    if (url && !url.startsWith("https://")) {
      setError("The webhook URL must start with https://");
      return;
    }

    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateAirframeConfig(airframeLabel, { alert_rules: parsed, webhook_url: url || null });
      onUpdated(updated);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the alert rules.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="alerts-h" className="panel space-y-4 p-4">
      <h2 id="alerts-h" className="flex items-center gap-2 text-base font-semibold">
        <Bell aria-hidden className="h-4 w-4 text-accent" />
        Alerts
      </h2>
      <p className="text-xs text-fg-muted">
        When a new flight tagged &quot;{airframeLabel}&quot; breaks a rule, FlightMD posts a message to
        this airframe&apos;s webhook (Slack and Discord work). Only holders of the airframe token can
        change it.
      </p>

      {error && <p role="alert" className="text-xs text-critical">{error}</p>}

      <div className="space-y-2">
        {rules.map((rule, i) => (
          <fieldset key={rule.key} className="grid grid-cols-2 gap-2 rounded border bg-elevated p-2 sm:grid-cols-[1fr_auto_6rem_1fr_auto]">
            <legend className="sr-only">Rule {i + 1}</legend>
            <label className="sr-only" htmlFor={`r-metric-${rule.key}`}>Metric</label>
            <select
              id={`r-metric-${rule.key}`}
              value={rule.metric}
              onChange={(e) => updateRule(rule.key, { metric: e.target.value })}
              className="input col-span-2 sm:col-span-1"
            >
              {METRIC_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            <label className="sr-only" htmlFor={`r-cmp-${rule.key}`}>Comparison</label>
            <select
              id={`r-cmp-${rule.key}`}
              value={rule.comparison}
              onChange={(e) => updateRule(rule.key, { comparison: e.target.value as "lt" | "gt" })}
              className="input"
            >
              <option value="lt">below</option>
              <option value="gt">above</option>
            </select>
            <label className="sr-only" htmlFor={`r-th-${rule.key}`}>Threshold</label>
            <input
              id={`r-th-${rule.key}`}
              type="text"
              inputMode="decimal"
              value={rule.threshold}
              onChange={(e) => updateRule(rule.key, { threshold: e.target.value })}
              className="input num"
            />
            <label className="sr-only" htmlFor={`r-label-${rule.key}`}>Description</label>
            <input
              id={`r-label-${rule.key}`}
              type="text"
              value={rule.label}
              onChange={(e) => updateRule(rule.key, { label: e.target.value })}
              placeholder="Description (optional)"
              className="input col-span-2 sm:col-span-1"
            />
            <button
              type="button"
              onClick={() => setRules((prev) => prev.filter((r) => r.key !== rule.key))}
              className="btn border-transparent bg-transparent px-2 text-fg-muted"
              aria-label={`Remove rule ${i + 1}`}
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          </fieldset>
        ))}
        <button
          type="button"
          onClick={() => setRules((prev) => [...prev, toRow({ metric: "overall_score", comparison: "lt", threshold: 70, label: "" })])}
          className="btn"
        >
          <Plus aria-hidden className="h-4 w-4" />
          Add rule
        </button>
      </div>

      <div className="space-y-1 border-t pt-3">
        <label htmlFor="webhook-url" className="label block">Webhook URL</label>
        <input
          id="webhook-url"
          type="url"
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder="https://hooks.slack.com/… or https://discord.com/api/webhooks/…"
          aria-describedby="webhook-help"
          className="input w-full"
        />
        <p id="webhook-help" className="text-xs text-fg-muted">Must be https:// and reach a public address.</p>
      </div>

      <div className="flex items-center gap-3">
        <button type="button" onClick={save} disabled={saving} className="btn-primary">
          Save alert rules
        </button>
        {saved && <span role="status" className="text-xs text-ok">Saved</span>}
      </div>
    </section>
  );
}
