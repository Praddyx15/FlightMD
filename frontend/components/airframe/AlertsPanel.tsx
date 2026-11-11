"use client";

import { useRef, useState } from "react";
import { Bell, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import type { AirframeConfigResponse, AlertRule } from "@/lib/types";
import { updateAirframeConfig } from "@/lib/api";
import { useErrorText } from "@/lib/errors";
import { useLabels } from "@/lib/useLabels";

interface AlertsPanelProps {
  airframeLabel: string;
  config: AirframeConfigResponse;
  onUpdated: (config: AirframeConfigResponse) => void;
}

// the API's alert metric ids
const METRIC_OPTIONS = [
  "overall_score",
  "module.oscillation",
  "module.vibration",
  "module.ekf",
  "module.battery",
  "module.gps",
  "module.motors",
  "oscillation.roll_peak_hz",
  "battery.sag_per_cell_v",
  "gps.max_hdop",
  "gps.min_satellites",
  "vibration.max_imu_rms",
];

// threshold stays a string while typing so "0." or "-" don't snap to 0
interface Row extends Omit<AlertRule, "threshold"> {
  key: number;
  threshold: string;
}

export function AlertsPanel({ airframeLabel, config, onUpdated }: AlertsPanelProps) {
  const t = useTranslations("alerts");
  const errText = useErrorText();
  const labels = useLabels();
  const nextKey = useRef(0);
  const toRow = (r: AlertRule): Row => ({ ...r, threshold: String(r.threshold), key: nextKey.current++ });
  const [rules, setRules] = useState<Row[]>(() => config.alert_rules.map(toRow));
  const [webhookUrl, setWebhookUrl] = useState(config.webhook_url ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function optionLabel(metric: string) {
    if (metric === "overall_score") return t("overall");
    if (metric.startsWith("module.")) return t("moduleScore", { module: labels.module(metric.slice(7)) });
    const m = labels.metric(metric);
    return m.unit ? `${m.label} (${m.unit})` : m.label;
  }

  function updateRule(key: number, patch: Partial<Row>) {
    setRules((prev) => prev.map((r) => (r.key === key ? { ...r, ...patch } : r)));
    setSaved(false);
  }

  async function save() {
    const parsed: AlertRule[] = [];
    for (const r of rules) {
      const n = Number(r.threshold);
      if (r.threshold.trim() === "" || !Number.isFinite(n)) {
        setError(t("badThreshold", { metric: optionLabel(r.metric) }));
        return;
      }
      parsed.push({ metric: r.metric, comparison: r.comparison, threshold: n, label: r.label });
    }
    const url = webhookUrl.trim();
    if (url && !url.startsWith("https://")) {
      setError(t("badWebhook"));
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
      setError(errText(err, "alertsSave"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="alerts-h" className="panel space-y-4 p-4">
      <h2 id="alerts-h" className="flex items-center gap-2 text-base font-semibold">
        <Bell aria-hidden className="h-4 w-4 text-accent" />
        {t("title")}
      </h2>
      <p className="text-xs text-fg-muted">{t("help", { label: airframeLabel })}</p>

      {error && <p role="alert" className="text-xs text-critical">{error}</p>}

      <div className="space-y-2">
        {rules.map((rule, i) => (
          <fieldset key={rule.key} className="grid grid-cols-2 gap-2 rounded border bg-elevated p-2 sm:grid-cols-[1fr_auto_6rem_1fr_auto]">
            <legend className="sr-only">{t("rule", { n: i + 1 })}</legend>
            <label className="sr-only" htmlFor={`r-metric-${rule.key}`}>{t("metric")}</label>
            <select
              id={`r-metric-${rule.key}`}
              value={rule.metric}
              onChange={(e) => updateRule(rule.key, { metric: e.target.value })}
              className="input col-span-2 sm:col-span-1"
            >
              {METRIC_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>{optionLabel(opt)}</option>
              ))}
            </select>
            <label className="sr-only" htmlFor={`r-cmp-${rule.key}`}>{t("comparison")}</label>
            <select
              id={`r-cmp-${rule.key}`}
              value={rule.comparison}
              onChange={(e) => updateRule(rule.key, { comparison: e.target.value as "lt" | "gt" })}
              className="input"
            >
              <option value="lt">{t("below")}</option>
              <option value="gt">{t("above")}</option>
            </select>
            <label className="sr-only" htmlFor={`r-th-${rule.key}`}>{t("threshold")}</label>
            <input
              id={`r-th-${rule.key}`}
              type="text"
              inputMode="decimal"
              value={rule.threshold}
              onChange={(e) => updateRule(rule.key, { threshold: e.target.value })}
              className="input num"
            />
            <label className="sr-only" htmlFor={`r-label-${rule.key}`}>{t("description")}</label>
            <input
              id={`r-label-${rule.key}`}
              type="text"
              value={rule.label}
              onChange={(e) => updateRule(rule.key, { label: e.target.value })}
              placeholder={t("descriptionPlaceholder")}
              className="input col-span-2 sm:col-span-1"
            />
            <button
              type="button"
              onClick={() => setRules((prev) => prev.filter((r) => r.key !== rule.key))}
              className="btn border-transparent bg-transparent px-2 text-fg-muted"
              aria-label={t("remove", { n: i + 1 })}
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
          {t("add")}
        </button>
      </div>

      <div className="space-y-1 border-t pt-3">
        <label htmlFor="webhook-url" className="label block">{t("webhook")}</label>
        <input
          id="webhook-url"
          type="url"
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder={t("webhookPlaceholder")}
          aria-describedby="webhook-help"
          className="input w-full"
        />
        <p id="webhook-help" className="text-xs text-fg-muted">{t("webhookHelp")}</p>
      </div>

      <div className="flex items-center gap-3">
        <button type="button" onClick={save} disabled={saving} className="btn-primary">
          {t("save")}
        </button>
        {saved && <span role="status" className="text-xs text-ok">{t("saved")}</span>}
      </div>
    </section>
  );
}
