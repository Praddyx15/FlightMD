import type {
  AirframeConfigResponse,
  AlertRule,
  AnalyseResponse,
  ChangeRecord,
  DiffResponse,
  FlightMDReport,
  NewChangeRecord,
  StatusResponse,
  TrendsResponse,
} from "./types";
import { getAirframeToken, setAirframeToken } from "./storage";

// Without NEXT_PUBLIC_API_URL an https page would call http://localhost and get blocked
// as mixed content; same-origin at least fails with a readable 404.
export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  (typeof window !== "undefined" && window.location.protocol === "https:" ? "" : "http://localhost:8000")
).replace(/\/$/, "");

const TIMEOUT_MS = 20_000;

// `message` is the server's own text when it sent one. Otherwise `code` names our text,
// a key under "errors" in messages/*.json, and the message is only the code, for the console.
export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string | null, code?: string) {
    super(message || code || `HTTP ${status}`);
    this.status = status;
    this.code = message ? undefined : code;
  }
}

// 401/403 on anything airframe-scoped. `unclaimed` = nobody holds a token yet.
export class AirframeAuthError extends ApiError {
  unclaimed: boolean;
  constructor(status: number, message: string | null, code?: string) {
    super(status, message, code);
    this.unclaimed = /not claimed/i.test(message ?? "");
  }
}

async function detail(res: Response): Promise<string | null> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
    // fastapi validation errors come as a list
    if (Array.isArray(body?.detail) && body.detail[0]?.msg) return String(body.detail[0].msg);
  } catch {
    // not json
  }
  return null;
}

async function request(path: string, init: RequestInit = {}, timeout = TIMEOUT_MS): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  const outer = init.signal;
  const onAbort = () => ctrl.abort();
  outer?.addEventListener("abort", onAbort);
  try {
    return await fetch(`${API_URL}${path}`, { ...init, signal: ctrl.signal });
  } catch (e) {
    if (outer?.aborted) throw e;
    if (ctrl.signal.aborted) throw new ApiError(0, null, "timeout");
    throw new ApiError(0, null, "network");
  } finally {
    clearTimeout(timer);
    outer?.removeEventListener("abort", onAbort);
  }
}

// fallback is an "errors" key, used when the server sent no detail of its own
async function fail(res: Response, fallback: string): Promise<never> {
  throw new ApiError(res.status, await detail(res), fallback);
}

async function json<T>(res: Response, fallback: string): Promise<T> {
  if (!res.ok) await fail(res, fallback);
  return res.json() as Promise<T>;
}

function airframeHeaders(label: string, extra: Record<string, string> = {}): Record<string, string> {
  const token = getAirframeToken(label);
  return token ? { ...extra, "X-Airframe-Token": token } : extra;
}

function keepToken(label: string, body: unknown) {
  const t = (body as { airframe_token?: unknown } | null)?.airframe_token;
  if (typeof t === "string" && t) setAirframeToken(label, t);
}

async function airframeRequest<T>(label: string, path: string, init: RequestInit, fallback: string): Promise<T> {
  const res = await request(path, {
    ...init,
    headers: airframeHeaders(label, (init.headers as Record<string, string>) ?? {}),
  });
  if (res.status === 401 || res.status === 403) {
    throw new AirframeAuthError(res.status, await detail(res), res.status === 401 ? "airframeNeedsToken" : "airframeWrongToken");
  }
  const body = await json<T>(res, fallback);
  keepToken(label, body);
  return body;
}

const af = (label: string) => encodeURIComponent(label);

export interface UploadOptions {
  airframeLabel?: string;
  contribute?: boolean;
  planningBrief?: string; // AeroAtlas brief hash, 64 hex
  signal?: AbortSignal;
}

export function uploadLog(
  file: File,
  onProgress: (pct: number) => void,
  { airframeLabel, contribute, planningBrief, signal }: UploadOptions = {}
): Promise<AnalyseResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    const label = airframeLabel?.trim() || "";
    form.append("file", file);
    if (label) form.append("airframe_label", label);
    if (contribute) form.append("contribute_to_dataset", "true");
    if (planningBrief) form.append("planning_brief_sha256", planningBrief.toLowerCase());

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    });

    const serverDetail = () => {
      try {
        const d = JSON.parse(xhr.responseText)?.detail;
        return typeof d === "string" ? d : null;
      } catch {
        return null;
      }
    };

    xhr.addEventListener("load", () => {
      if (xhr.status === 200 || xhr.status === 202) {
        try {
          const body = JSON.parse(xhr.responseText) as AnalyseResponse;
          if (label) keepToken(label, body);
          resolve(body);
        } catch {
          reject(new ApiError(xhr.status, null, "invalidResponse"));
        }
        return;
      }
      const d = serverDetail();
      if (xhr.status === 401 || xhr.status === 403) {
        reject(new AirframeAuthError(xhr.status, d, "airframeBelongs"));
      } else if (xhr.status === 413) {
        reject(new ApiError(413, d, "tooLarge"));
      } else if (xhr.status === 429) {
        reject(new ApiError(429, d, "uploadLimit"));
      } else if (xhr.status === 503) {
        reject(new ApiError(503, null, "busy"));
      } else {
        reject(new ApiError(xhr.status, d, "server"));
      }
    });

    xhr.addEventListener("error", () => reject(new ApiError(0, null, "network")));
    xhr.addEventListener("timeout", () => reject(new ApiError(0, null, "uploadTimeout")));
    xhr.addEventListener("abort", () => reject(new ApiError(0, null, "uploadCancelled")));
    signal?.addEventListener("abort", () => xhr.abort());

    xhr.open("POST", `${API_URL}/analyse`);
    xhr.timeout = 10 * 60_000;
    if (label) {
      const token = getAirframeToken(label);
      if (token) xhr.setRequestHeader("X-Airframe-Token", token);
    }
    xhr.send(form);
  });
}

export interface DatasetStats {
  contributed_logs: number;
  total_bytes: number;
}

export async function getDatasetStats(): Promise<DatasetStats> {
  return json(await request("/dataset/stats"), "datasetStats");
}

// 404 means it is already gone, which is what the caller wanted
export async function withdrawContribution(contributionId: string): Promise<void> {
  const res = await request(`/dataset/${encodeURIComponent(contributionId)}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) await fail(res, "withdraw");
}

export async function getStatus(reportId: string, signal?: AbortSignal): Promise<StatusResponse> {
  const res = await request(`/status/${encodeURIComponent(reportId)}`, { signal });
  return json(res, "status");
}

// null while the report file is still being written (202)
export async function getReport(reportId: string, signal?: AbortSignal): Promise<FlightMDReport | null> {
  const res = await request(`/report/${encodeURIComponent(reportId)}`, { signal });
  if (res.status === 202) return null;
  return json(res, "report");
}

export function pdfExportUrl(reportId: string): string {
  return `${API_URL}/export/pdf/${reportId}`;
}

export function jsonExportUrl(reportId: string): string {
  return `${API_URL}/export/json/${reportId}`;
}

export function gpxExportUrl(reportId: string): string {
  return `${API_URL}/export/gpx/${reportId}`;
}

export function kmlExportUrl(reportId: string): string {
  return `${API_URL}/export/kml/${reportId}`;
}

// Cross-origin <a download> ignores the file name, so fetch and save the blob.
export async function downloadFile(url: string, fileName: string, headers?: Record<string, string>) {
  const res = await request(url.startsWith(API_URL) ? url.slice(API_URL.length) : url, { headers }, 60_000);
  if (!res.ok) await fail(res, "download");
  saveBlob(await res.blob(), fileName);
}

function saveBlob(blob: Blob, fileName: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export async function downloadAirframeRecord(label: string) {
  const res = await request(`/export/airframe/${af(label)}/pdf`, { headers: airframeHeaders(label) }, 60_000);
  if (res.status === 401 || res.status === 403) {
    throw new AirframeAuthError(res.status, await detail(res), "airframeNeedsToken");
  }
  if (!res.ok) await fail(res, "download");
  saveBlob(await res.blob(), `flightmd_${label}_record.pdf`);
}

export async function getTrends(airframeLabel: string): Promise<TrendsResponse> {
  return airframeRequest(airframeLabel, `/trends/${af(airframeLabel)}`, {}, "trends");
}

export async function getDiff(a: string, b: string): Promise<DiffResponse> {
  const res = await request(`/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  if (res.status === 404) throw new ApiError(404, null, "diffNotFound");
  return json(res, "diff");
}

export const ASK_MAX_CHARS = 500;

export interface AskResponse {
  configured: boolean;
  answer: string | null;
}

export async function askAI(reportId: string, question: string): Promise<AskResponse> {
  const res = await request(
    `/ask/${encodeURIComponent(reportId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: question.slice(0, ASK_MAX_CHARS) }),
    },
    60_000
  );
  if (res.status === 429) throw new ApiError(429, null, "askLimit");
  return json(res, "ask");
}

export async function getAirframeConfig(airframeLabel: string): Promise<AirframeConfigResponse> {
  return airframeRequest(airframeLabel, `/airframe/${af(airframeLabel)}/config`, {}, "airframeConfig");
}

export interface AirframeConfigUpdate {
  checklist_items?: string[];
  maintenance_interval_hours?: number | null;
  alert_rules?: AlertRule[];
  webhook_url?: string | null;
}

// an empty update on an unclaimed airframe claims it and returns the token
export async function updateAirframeConfig(
  airframeLabel: string,
  update: AirframeConfigUpdate
): Promise<AirframeConfigResponse> {
  return airframeRequest(
    airframeLabel,
    `/airframe/${af(airframeLabel)}/config`,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(update) },
    "airframeUpdate"
  );
}

export async function addMaintenanceEntry(
  airframeLabel: string,
  entry: { date: string; maintenance_type: string; notes?: string }
): Promise<AirframeConfigResponse> {
  return airframeRequest(
    airframeLabel,
    `/airframe/${af(airframeLabel)}/maintenance`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(entry) },
    "maintenance"
  );
}

// tune, fly, verify: which of the suggested changes went onto the vehicle
export async function recordAppliedChanges(airframeLabel: string, body: NewChangeRecord): Promise<ChangeRecord> {
  return airframeRequest(
    airframeLabel,
    `/airframe/${af(airframeLabel)}/changes`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    "changesSave"
  );
}

export async function getAppliedChanges(airframeLabel: string): Promise<ChangeRecord[]> {
  return airframeRequest(airframeLabel, `/airframe/${af(airframeLabel)}/changes`, {}, "changes");
}
