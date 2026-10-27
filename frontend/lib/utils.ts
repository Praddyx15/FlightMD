import { clsx, type ClassValue } from "clsx";
import type { AnalyserResult, Finding, FlightMDReport, Severity } from "./types";
import { isNum } from "./format";

// plain join: tailwind-merge would read text-hero / text-value as colours and drop them
export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export type Tone = "critical" | "caution" | "advisory" | "ok";

export const SEVERITY_TONE: Record<Severity, Tone> = {
  critical: "critical",
  warning: "caution",
  info: "advisory",
  good: "ok",
};

// for SVG/inline styles; Tailwind classes use text-critical etc.
export const TONE_VAR: Record<Tone, string> = {
  critical: "var(--critical)",
  caution: "var(--caution)",
  advisory: "var(--advisory)",
  ok: "var(--ok)",
};

export const TONE_FILL_VAR: Record<Tone, string> = {
  critical: "var(--critical-fill)",
  caution: "var(--caution-fill)",
  advisory: "var(--advisory-fill)",
  ok: "var(--ok-fill)",
};

export const SEVERITY_COLOURS: Record<Severity, string> = {
  critical: TONE_VAR.critical,
  warning: TONE_VAR.caution,
  info: TONE_VAR.advisory,
  good: TONE_VAR.ok,
};

// written out in full so Tailwind's scanner sees every class
export const TONE_CLASSES: Record<Tone, string> = {
  critical: "text-critical bg-critical-fill/15 border-critical-fill/50",
  caution: "text-caution bg-caution-fill/15 border-caution-fill/50",
  advisory: "text-advisory bg-advisory-fill/15 border-advisory-fill/50",
  ok: "text-ok bg-ok-fill/15 border-ok-fill/50",
};

export const TONE_EDGE: Record<Tone, string> = {
  critical: "border-l-critical-fill",
  caution: "border-l-caution-fill",
  advisory: "border-l-advisory-fill",
  ok: "border-l-ok-fill",
};

export const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  warning: 1,
  info: 2,
  good: 3,
};

export const SEVERITY_LABELS: Record<Severity, string> = {
  critical: "Critical",
  warning: "Warning",
  info: "Info",
  good: "Good",
};

export function scoreTone(score: number): Tone {
  if (score >= 80) return "ok";
  if (score >= 50) return "caution";
  return "critical";
}

export function scoreColour(score: number): string {
  return TONE_VAR[scoreTone(score)];
}

export function gradeTone(grade: string): Tone {
  if (grade === "A" || grade === "B") return "ok";
  if (grade === "C" || grade === "D" || grade === "E") return "caution";
  return "critical";
}

export function gradeColour(grade: string): string {
  return TONE_VAR[gradeTone(grade)];
}

// assessed=false is new in 1.6; before that only `skipped` existed
export function isAssessed(r: AnalyserResult): boolean {
  return !r.skipped && r.assessed !== false;
}

export function isReportAssessed(report: FlightMDReport): boolean {
  if (report.assessed_fraction === 0) return false;
  if (report.letter_grade === "-" || /not assessed/i.test(report.score_label)) return false;
  return true;
}

// log-relative seconds; t_*_s wins, the older *_ms fields are the fallback
export function findingStart(f: Finding): number | null {
  if (isNum(f.t_start_s)) return f.t_start_s;
  return isNum(f.timestamp_start_ms) ? f.timestamp_start_ms / 1000 : null;
}

export function findingEnd(f: Finding): number | null {
  if (isNum(f.t_end_s)) return f.t_end_s;
  return isNum(f.timestamp_end_ms) ? f.timestamp_end_ms / 1000 : null;
}

export function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  // http (no clipboard API): the old textarea trick
  const el = document.createElement("textarea");
  el.value = text;
  el.setAttribute("readonly", "");
  el.style.position = "fixed";
  el.style.opacity = "0";
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
  return Promise.resolve();
}
