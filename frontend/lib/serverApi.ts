import type { FlightMDReport } from "./types";

// Server-side only. API_URL is the API as the Next server reaches it (a service name in
// docker compose); the browser keeps using NEXT_PUBLIC_API_URL.
const SERVER_API_URL = (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type ServerReport =
  | { kind: "done"; report: FlightMDReport }
  | { kind: "pending" } // 202, or anything we can't read: the client island takes over
  | { kind: "missing" }
  | { kind: "failed"; error: string | null };

export async function fetchReportOnServer(id: string): Promise<ServerReport> {
  let res: Response;
  try {
    // reports are private by id: never cached
    res = await fetch(`${SERVER_API_URL}/report/${encodeURIComponent(id)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    });
  } catch {
    return { kind: "pending" };
  }

  if (res.status === 404) return { kind: "missing" };
  if (res.status === 422) {
    const body = await res.json().catch(() => null);
    return { kind: "failed", error: typeof body?.detail === "string" ? body.detail : null };
  }
  if (res.status !== 200) return { kind: "pending" };
  try {
    return { kind: "done", report: (await res.json()) as FlightMDReport };
  } catch {
    return { kind: "pending" };
  }
}
