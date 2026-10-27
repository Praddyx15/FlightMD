"use client";

import { useRef, useState } from "react";
import { ArrowRight, Search, Sparkles } from "lucide-react";
import type { Category, Finding, FlightMDReport, ParamRecommendation } from "@/lib/types";
import { ASK_MAX_CHARS, askAI } from "@/lib/api";
import { fmtParam, fmtScore } from "@/lib/format";
import { MODULE_LABELS, formatMetric, humaniseMetricKey } from "@/lib/metricLabels";
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

const TOPICS: [Category, RegExp][] = [
  ["oscillation", /oscillat|wobbl|shak|pid|tun/],
  ["vibration", /vibrat|clip|imu|accel/],
  ["ekf", /ekf|estimator|innovation/],
  ["battery", /batter|voltage|sag|power|cell/],
  ["gps", /gps|satellite|hdop|fix|jamm|spoof/],
  ["motors", /motor|esc|rpm|prop/],
];

const PRESETS = ["Vibration", "Battery", "GPS", "Parameter changes"];

// Only says what the report itself contains: module score, findings, key_metrics.
function searchReport(report: FlightMDReport, text: string): Omit<QAEntry, "id" | "query" | "source"> {
  const q = text.toLowerCase();

  if (/param|change|recommend|setting/.test(q)) {
    const params = report.param_change_sheet;
    return {
      answer: params.length
        ? `The report suggests ${params.length} parameter ${params.length === 1 ? "change" : "changes"}.`
        : "The report suggests no parameter changes.",
      findings: [],
      params,
    };
  }

  const topic = TOPICS.find(([, re]) => re.test(q))?.[0];
  if (topic) {
    const label = MODULE_LABELS[topic] ?? topic;
    const result = report.analyser_results.find((r) => r.analyser === topic);
    const findings = report.findings.filter((f) => f.category === topic);
    if (!result) return { answer: `This report has no ${label} check.`, findings, params: [] };
    if (!isAssessed(result)) {
      return {
        answer: `${label}: not assessed${result.skip_reason ? ` (${result.skip_reason})` : ""}.`,
        findings: [],
        params: [],
      };
    }
    const lines = Object.entries(result.key_metrics).map(
      ([k, v]) => `${humaniseMetricKey(`${topic}.${k}`).label}: ${formatMetric(`${topic}.${k}`, v)}`
    );
    const answer = findings.length
      ? `${label}: module score ${fmtScore(result.health_score)}, ${findings.length} ${findings.length === 1 ? "finding" : "findings"}.`
      : `${label}: no finding in this category; module score ${fmtScore(result.health_score)}.`;
    return { answer, lines, findings, params: [] };
  }

  const findings = report.findings.filter((f) =>
    [f.title, f.plain_english, f.recommendation].some((s) => s.toLowerCase().includes(q))
  );
  const params = report.param_change_sheet.filter(
    (p) => p.param_name.toLowerCase().includes(q) || p.reason.toLowerCase().includes(q)
  );
  return {
    answer: findings.length || params.length
      ? `Matches for "${text}" in this report:`
      : `Nothing in this report mentions "${text}". Try a check name: oscillation, vibration, EKF, battery, GPS, motors, or "parameter changes".`,
    findings,
    params,
  };
}

export default function QAAssistant({ report }: QAAssistantProps) {
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
          push({ query: q, answer: res.answer || "No answer came back.", findings: [], params: [], source: "ai" });
          return;
        }
        // server has no AI key -> plain search for the rest of the session
        setAiUnavailable(true);
      } catch (e) {
        // a one-off failure; the toggle stays usable
        push({ query: q, answer: e instanceof Error ? e.message : "The AI request failed.", findings: [], params: [], source: "error" });
        return;
      } finally {
        setThinking(false);
      }
    }

    push({ query: q, ...searchReport(report, q), source: "search" });
  }

  return (
    <section aria-labelledby="qa-h" className="no-print space-y-3">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 id="qa-h" className="flex items-center gap-2 text-base font-semibold">
            {aiOn ? <Sparkles aria-hidden className="h-4 w-4 text-accent" /> : <Search aria-hidden className="h-4 w-4 text-accent" />}
            {aiOn ? "Ask about this report" : "Search this report"}
          </h2>
          <p className="text-xs text-fg-muted">
            Answers come only from this report: its findings, module scores and metrics.
            {aiOn ? " The AI is told to answer from this report only; check its answer against the findings." : ""}
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-fg-muted">
          <span>Use AI</span>
          <button
            type="button"
            role="switch"
            aria-checked={aiOn}
            disabled={aiUnavailable}
            onClick={() => setUseAI((v) => !v)}
            title={aiUnavailable ? "No AI provider is configured on this server" : undefined}
            className={cn(
              "relative h-5 w-9 rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              aiOn ? "border-accent-solid bg-accent-solid" : "bg-elevated"
            )}
          >
            <span
              className={cn(
                "absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full bg-fg transition-transform",
                aiOn && "translate-x-4 bg-on-accent"
              )}
            />
          </button>
        </label>
      </div>

      {aiUnavailable && (
        <p className="text-xs text-fg-muted">
          This server has no AI provider configured, so questions use the built-in search. That is expected without an API key.
        </p>
      )}

      <div aria-live="polite" className="panel max-h-[420px] space-y-3 overflow-y-auto p-3">
        {history.length === 0 && !thinking && (
          <p className="py-4 text-center text-sm text-fg-muted">Ask about a check, a parameter, or a word from the findings.</p>
        )}
        {history.map((item) => (
          <div key={item.id} className="space-y-2 border-b pb-3 last:border-b-0 last:pb-0">
            <p className="text-sm font-medium">
              <span className="sr-only">You asked: </span>
              {item.query}
            </p>
            <div className="space-y-2 rounded bg-elevated p-3 text-sm">
              {item.source === "ai" && <p className="label">AI answer, from this report only</p>}
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
                        <ArrowRight aria-label="to" className="mx-1 inline h-3 w-3" />
                        <span className="font-semibold text-accent-text">{fmtParam(p.suggested_value)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ))}
        {thinking && <p className="text-sm text-fg-muted">Asking…</p>}
      </div>

      <div className="flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button key={p} type="button" disabled={thinking} onClick={() => ask(p)} className="btn text-xs">
            {p}
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
        <label htmlFor="qa-input" className="sr-only">Question about this report</label>
        <input
          id="qa-input"
          type="text"
          value={query}
          disabled={thinking}
          maxLength={ASK_MAX_CHARS}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={aiOn ? "e.g. why did the GPS finding fire?" : "e.g. battery, HDOP, MC_ROLLRATE_P"}
          className="input min-w-0 flex-1"
        />
        <button type="submit" disabled={thinking || !query.trim()} className="btn-primary">
          {aiOn ? "Ask" : "Search"}
        </button>
      </form>
    </section>
  );
}
