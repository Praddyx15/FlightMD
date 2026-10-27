"use client";

import { useRef, useState } from "react";
import { ArrowRight, Search, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import type { Category, Finding, FlightMDReport, ParamRecommendation } from "@/lib/types";
import { ASK_MAX_CHARS, askAI } from "@/lib/api";
import { fmtParam, fmtScore, type UnitSystem } from "@/lib/format";
import type { Labels } from "@/lib/metricLabels";
import { useLabels } from "@/lib/useLabels";
import { useErrorText } from "@/lib/errors";
import { useUnits } from "@/lib/units";
import { cn, isAssessed } from "@/lib/utils";
import { SeverityIcon } from "@/components/shared/SeverityBadge";

interface QAAssistantProps {
  report: FlightMDReport;
}

interface QAEntry {
  id: number;
  query: string;
  answer: string;
  lines?: string[];
  findings: Finding[];
  params: ParamRecommendation[];
  source: "search" | "ai" | "error";
}

type Translate = (key: string, values?: Record<string, string | number>) => string;

// keyword matching stays English for now: the words people type about drones mostly are
const TOPICS: [Category, RegExp][] = [
  ["oscillation", /oscillat|wobbl|shak|pid|tun/],
  ["vibration", /vibrat|clip|imu|accel/],
  ["ekf", /ekf|estimator|innovation/],
  // before battery, which also matches "power"
  ["power", /vcc|brownout|power supply|board volt/],
  ["battery", /batter|voltage|sag|power|cell/],
  ["gps", /gps|satellite|hdop|fix|jamm|spoof/],
  ["motors", /motor|esc|rpm|prop/],
];

const PRESETS = ["vibration", "battery", "gps", "params"] as const;

// Only says what the report itself contains: module score, findings, key_metrics.
export function searchReport(
  report: FlightMDReport,
  text: string,
  t: Translate,
  labels: Labels,
  units: UnitSystem = "metric"
): Omit<QAEntry, "id" | "query" | "source"> {
  const q = text.toLowerCase();

  if (/param|change|recommend|setting/.test(q)) {
    const params = report.param_change_sheet;
    return { answer: t("answer.params", { count: params.length }), findings: [], params };
  }

  const topic = TOPICS.find(([, re]) => re.test(q))?.[0];
  if (topic) {
    const label = labels.module(topic);
    const result = report.analyser_results.find((r) => r.analyser === topic);
    const findings = report.findings.filter((f) => f.category === topic);
    if (!result) return { answer: t("answer.noCheck", { label }), findings, params: [] };
    if (!isAssessed(result)) {
      return {
        answer: result.skip_reason
          ? t("answer.notAssessedBecause", { label, reason: result.skip_reason })
          : t("answer.notAssessed", { label }),
        findings: [],
        params: [],
      };
    }
    const lines = Object.entries(result.key_metrics).map(
      ([k, v]) => `${labels.metric(`${topic}.${k}`, units).label}: ${labels.format(`${topic}.${k}`, v, units)}`
    );
    const answer = findings.length
      ? t("answer.module", { label, score: fmtScore(result.health_score), count: findings.length })
      : t("answer.moduleClean", { label, score: fmtScore(result.health_score) });
    return { answer, lines, findings, params: [] };
  }

  const findings = report.findings.filter((f) =>
    [f.title, f.plain_english, f.recommendation].some((s) => s.toLowerCase().includes(q))
  );
  const params = report.param_change_sheet.filter(
    (p) => p.param_name.toLowerCase().includes(q) || p.reason.toLowerCase().includes(q)
  );
  return {
    answer: findings.length || params.length ? t("answer.matches", { text }) : t("answer.nothing", { text }),
    findings,
    params,
  };
}

export default function QAAssistant({ report }: QAAssistantProps) {
  const t = useTranslations("qa");
  const labels = useLabels();
  const units = useUnits();
  const errText = useErrorText();
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState<QAEntry[]>([]);
  const [useAI, setUseAI] = useState(false);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [thinking, setThinking] = useState(false);
  const nextId = useRef(0);

  const aiOn = useAI && !aiUnavailable;

  function push(entry: Omit<QAEntry, "id">) {
    setHistory((prev) => [...prev, { ...entry, id: nextId.current++ }]);
  }

  async function ask(text: string) {
    const q = text.trim();
    if (!q) return;
    setQuery("");

    if (aiOn) {
      setThinking(true);
      try {
        const res = await askAI(report.report_id, q);
        if (res.configured) {
          push({ query: q, answer: res.answer || t("noAnswer"), findings: [], params: [], source: "ai" });
          return;
        }
        // server has no AI key -> plain search for the rest of the session
        setAiUnavailable(true);
      } catch (e) {
        // a one-off failure; the toggle stays usable
        push({ query: q, answer: errText(e, "ask"), findings: [], params: [], source: "error" });
        return;
      } finally {
        setThinking(false);
      }
    }

    push({ query: q, ...searchReport(report, q, t, labels, units), source: "search" });
  }

  return (
    <section aria-labelledby="qa-h" className="no-print space-y-3">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 id="qa-h" className="flex items-center gap-2 text-base font-semibold">
            {aiOn ? <Sparkles aria-hidden className="h-4 w-4 text-accent" /> : <Search aria-hidden className="h-4 w-4 text-accent" />}
            {aiOn ? t("titleAI") : t("title")}
          </h2>
          <p className="text-xs text-fg-muted">
            {t("scope")}
            {aiOn ? ` ${t("scopeAI")}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <span id="qa-ai-label">{t("useAI")}</span>
          <button
            type="button"
            role="switch"
            aria-checked={aiOn}
            aria-labelledby="qa-ai-label"
            disabled={aiUnavailable}
            onClick={() => setUseAI((v) => !v)}
            title={aiUnavailable ? t("noProvider") : undefined}
            className={cn(
              "relative h-5 w-9 rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              aiOn ? "border-accent-solid bg-accent-solid" : "bg-elevated"
            )}
          >
            <span
              className={cn(
                "absolute left-0.5 top-0.5 size-3.5 rounded-full bg-fg transition-transform",
                aiOn && "translate-x-4 bg-on-accent"
              )}
            />
          </button>
        </div>
      </div>

      {aiUnavailable && <p className="text-xs text-fg-muted">{t("aiUnavailable")}</p>}

      <div aria-live="polite" className="panel max-h-[420px] space-y-3 overflow-y-auto p-3">
        {history.length === 0 && !thinking && (
          <p className="py-4 text-center text-sm text-fg-muted">{t("empty")}</p>
        )}
        {history.map((item) => (
          <div key={item.id} className="space-y-2 border-b pb-3 last:border-b-0 last:pb-0">
            <p className="text-sm font-medium">
              <span className="sr-only">{t("youAsked")} </span>
              {item.query}
            </p>
            <div className="space-y-2 rounded bg-elevated p-3 text-sm">
              {item.source === "ai" && <p className="label">{t("aiAnswer")}</p>}
              <p className={cn("whitespace-pre-line", item.source === "error" && "text-critical")}>{item.answer}</p>
              {item.lines && item.lines.length > 0 && (
                <ul className="num space-y-0.5 text-xs text-fg-muted">
                  {item.lines.map((l) => <li key={l}>{l}</li>)}
                </ul>
              )}
              {item.findings.length > 0 && (
                <ul className="space-y-1.5">
                  {item.findings.map((f) => (
                    <li key={f.id}>
                      <a href={`#finding-${f.id}`} className="flex items-start gap-2 text-fg no-underline hover:underline">
                        <SeverityIcon severity={f.severity} className={cn("mt-0.5", f.severity === "critical" ? "text-critical" : f.severity === "warning" ? "text-caution" : "text-fg-muted")} />
                        <span className="text-xs">{f.title}</span>
                      </a>
                    </li>
                  ))}
                </ul>
              )}
              {item.params.length > 0 && (
                <ul className="space-y-1">
                  {item.params.map((p) => (
                    <li key={p.param_name} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                      <span className="num font-medium">{p.param_name}</span>
                      <span className="num">
                        <span className="text-fg-muted">{fmtParam(p.current_value)}</span>
                        <ArrowRight aria-label={t("to")} className="mx-1 inline h-3 w-3" />
                        <span className="font-semibold text-accent-text">{fmtParam(p.suggested_value)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ))}
        {thinking && <p className="text-sm text-fg-muted">{t("asking")}</p>}
      </div>

      <div className="flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button key={p} type="button" disabled={thinking} onClick={() => ask(t(`presets.${p}`))} className="btn text-xs">
            {t(`presets.${p}`)}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(query);
        }}
        className="flex gap-2"
      >
        <label htmlFor="qa-input" className="sr-only">{t("inputLabel")}</label>
        <input
          id="qa-input"
          type="text"
          value={query}
          disabled={thinking}
          maxLength={ASK_MAX_CHARS}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={aiOn ? t("placeholderAI") : t("placeholder")}
          className="input min-w-0 flex-1"
        />
        <button type="submit" disabled={thinking || !query.trim()} className="btn-primary">
          {aiOn ? t("ask") : t("search")}
        </button>
      </form>
    </section>
  );
}
