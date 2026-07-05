import type {
  AirframeConfigResponse,
  AlertRule,
  AnalyseResponse,
  DiffResponse,
  FlightMDReport,
  StatusResponse,
  TrendsResponse,
} from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Upload with progress ─────────────────────────────────────────────────────

export function uploadLog(
  file: File,
  onProgress: (pct: number) => void,
  airframeLabel?: string
): Promise<AnalyseResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    if (airframeLabel && airframeLabel.trim()) {
      form.append("airframe_label", airframeLabel.trim());
    }

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status === 200) {
        try {
          resolve(JSON.parse(xhr.responseText) as AnalyseResponse);
        } catch {
          reject(new Error("Invalid response from server."));
        }
      } else if (xhr.status === 413) {
        reject(new Error("File too large. Maximum size is 50MB."));
      } else if (xhr.status === 400) {
        try {
          const body = JSON.parse(xhr.responseText);
          reject(new Error(body.detail || "Invalid file."));
        } catch {
          reject(new Error("Invalid file."));
        }
      } else if (xhr.status === 429) {
        reject(new Error("Rate limit exceeded. Maximum 10 analyses per hour."));
      } else {
        reject(new Error(`Server error: ${xhr.status}`));
      }
    });

    xhr.addEventListener("error", () =>
      reject(new Error("Network error. Is the API running?"))
    );
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelled.")));

    xhr.open("POST", `${API_URL}/analyse`);
    xhr.send(form);
  });
}

// ── Status polling ───────────────────────────────────────────────────────────

export async function getStatus(reportId: string): Promise<StatusResponse> {
  const res = await fetch(`${API_URL}/status/${reportId}`);
  if (res.status === 404) throw new Error("Report not found or expired.");
  if (!res.ok) throw new Error(`Status error: ${res.status}`);
  return res.json();
}

// ── Full report ──────────────────────────────────────────────────────────────

export async function getReport(reportId: string): Promise<FlightMDReport> {
  const res = await fetch(`${API_URL}/report/${reportId}`);
  if (res.status === 404) throw new Error("Report not found or expired.");
  if (res.status === 202) throw new Error("Analysis still in progress.");
  if (!res.ok) throw new Error(`Report fetch error: ${res.status}`);
  return res.json();
}

// ── Export URLs ──────────────────────────────────────────────────────────────

export function pdfExportUrl(reportId: string): string {
  return `${API_URL}/export/pdf/${reportId}`;
}

export function jsonExportUrl(reportId: string): string {
  return `${API_URL}/export/json/${reportId}`;
}

export function airframeRecordPdfUrl(airframeLabel: string): string {
  return `${API_URL}/export/airframe/${encodeURIComponent(airframeLabel)}/pdf`;
}

export interface ReportSummary {
  report_id: string;
  file_name: string;
  file_size_bytes: number;
  overall_score: number;
  score_label: string;
  letter_grade: string;
  duration_seconds: number;
  firmware_version: string;
  vehicle_type: string;
  weather_desc: string;
  airframe_label: string | null;
  created_at: number;
}

export async function getReports(): Promise<ReportSummary[]> {
  const res = await fetch(`${API_URL}/reports`);
  if (!res.ok) throw new Error(`Reports fetch error: ${res.status}`);
  return res.json();
}

// ── Trends & diff ─────────────────────────────────────────────────────────────

export async function getTrends(airframeLabel: string): Promise<TrendsResponse> {
  const res = await fetch(`${API_URL}/trends/${encodeURIComponent(airframeLabel)}`);
  if (!res.ok) throw new Error(`Trends fetch error: ${res.status}`);
  return res.json();
}

export async function getDiff(a: string, b: string): Promise<DiffResponse> {
  const res = await fetch(
    `${API_URL}/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`
  );
  if (res.status === 400) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "Cannot compare these two flights.");
  }
  if (res.status === 404) throw new Error("One or both reports were not found or have expired.");
  if (!res.ok) throw new Error(`Diff fetch error: ${res.status}`);
  return res.json();
}

// ── Optional AI Q&A ──────────────────────────────────────────────────────────

export interface AskResponse {
  configured: boolean;
  answer: string | null;
}

export async function askAI(
  reportId: string,
  question: string
): Promise<AskResponse> {
  const res = await fetch(`${API_URL}/ask/${reportId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) throw new Error(`AI assistant error: ${res.status}`);
  return res.json();
}

// ── Airframe config: maintenance, checklist, alerts ───────────────────────────

export async function getAirframeConfig(airframeLabel: string): Promise<AirframeConfigResponse> {
  const res = await fetch(`${API_URL}/airframe/${encodeURIComponent(airframeLabel)}/config`);
  if (!res.ok) throw new Error(`Airframe config fetch error: ${res.status}`);
  return res.json();
}

export interface AirframeConfigUpdate {
  checklist_items?: string[];
  maintenance_interval_hours?: number | null;
  alert_rules?: AlertRule[];
  webhook_url?: string | null;
}

export async function updateAirframeConfig(
  airframeLabel: string,
  update: AirframeConfigUpdate
): Promise<AirframeConfigResponse> {
  const res = await fetch(`${API_URL}/airframe/${encodeURIComponent(airframeLabel)}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Airframe config update error: ${res.status}`);
  }
  return res.json();
}

export async function addMaintenanceEntry(
  airframeLabel: string,
  entry: { date: string; maintenance_type: string; notes?: string }
): Promise<AirframeConfigResponse> {
  const res = await fetch(`${API_URL}/airframe/${encodeURIComponent(airframeLabel)}/maintenance`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(entry),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Maintenance entry error: ${res.status}`);
  }
  return res.json();
}
