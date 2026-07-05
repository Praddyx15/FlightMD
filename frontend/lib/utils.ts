import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { Severity } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const SEVERITY_COLOURS: Record<Severity, string> = {
  critical: "#FF3D3D",
  warning:  "#FF7A2F",
  info:     "#3A9CF8",
  good:     "#0DD97C",
};

export const SEVERITY_BG: Record<Severity, string> = {
  critical: "bg-[#FF3D3D]/15 border-[#FF3D3D]/40",
  warning:  "bg-[#FF7A2F]/15 border-[#FF7A2F]/40",
  info:     "bg-[#3A9CF8]/15 border-[#3A9CF8]/40",
  good:     "bg-[#0DD97C]/15 border-[#0DD97C]/40",
};

export const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  warning:  1,
  info:     2,
  good:     3,
};

export function scoreColour(score: number): string {
  if (score >= 90) return "#0DD97C";
  if (score >= 75) return "#3A9CF8";
  if (score >= 60) return "#E8A020";
  if (score >= 40) return "#FF7A2F";
  return "#FF3D3D";
}

// Letter grades map onto the same five-colour scale as scoreColour() and
// SEVERITY_COLOURS — one severity/score language used identically
// everywhere in the report, rather than a separate palette per component.
const GRADE_COLOURS: Record<string, string> = {
  A: "#0DD97C",
  B: "#3A9CF8",
  C: "#E8A020",
  D: "#FF7A2F",
  E: "#FF7A2F",
  F: "#FF3D3D",
};

export function gradeColour(grade: string): string {
  return GRADE_COLOURS[grade] ?? "#FF3D3D";
}

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatMs(ms: number | null): string {
  if (ms === null) return "—";
  const s = ms / 1000;
  const min = Math.floor(s / 60);
  const sec = s % 60;
  return `${min.toString().padStart(2, "0")}:${sec.toFixed(1).padStart(4, "0")}`;
}

export function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) return navigator.clipboard.writeText(text);
  // fallback
  const el = document.createElement("textarea");
  el.value = text;
  document.body.appendChild(el);
  el.select();
  document.execCommand("copy");
  document.body.removeChild(el);
  return Promise.resolve();
}
