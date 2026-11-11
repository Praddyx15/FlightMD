"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getReport, getStatus } from "./api";
import type { FlightMDReport } from "./types";

export type ReportState =
  | { phase: "queued" | "processing"; progress: number; message: string; eta: number | null }
  | { phase: "done"; report: FlightMDReport }
  | { phase: "failed"; error: string | null } // null: the server gave no reason
  | { phase: "expired" }
  | { phase: "error"; error: unknown } // network trouble, retries used up
  | { phase: "stopped" }; // gave up waiting; user can resume

export interface PollOptions {
  firstDelay?: number;
  maxDelay?: number;
  maxWaitMs?: number;
}

const MAX_NET_FAILURES = 5;

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    });
  });

// Status polling with backoff. 202 from /report (status says complete but the file isn't
// written yet) keeps polling instead of failing; 404 means expired and stops for good.
// Resolves once it reaches a final state or the signal aborts.
export async function pollReport(
  id: string,
  signal: AbortSignal,
  onState: (s: ReportState) => void,
  { firstDelay = 1000, maxDelay = 5000, maxWaitMs = 10 * 60_000 }: PollOptions = {}
): Promise<void> {
  const started = Date.now();
  let delay = firstDelay;
  let netFailures = 0;

  while (!signal.aborted) {
    if (Date.now() - started > maxWaitMs) {
      onState({ phase: "stopped" });
      return;
    }
    try {
      const st = await getStatus(id, signal);
      netFailures = 0;
      if (st.status === "failed") {
        onState({ phase: "failed", error: st.error || null });
        return;
      }
      if (st.status === "complete") {
        const report = await getReport(id, signal);
        if (report) {
          onState({ phase: "done", report });
          return;
        }
      } else {
        onState({
          phase: st.progress > 0 ? "processing" : "queued",
          progress: st.progress,
          message: st.message,
          eta: typeof st.eta_seconds === "number" && st.eta_seconds >= 0 ? st.eta_seconds : null,
        });
      }
    } catch (e) {
      if (signal.aborted) return;
      if (e instanceof ApiError && e.status === 404) {
        onState({ phase: "expired" });
        return;
      }
      if (e instanceof ApiError && (e.status === 422 || e.status === 500)) {
        onState({ phase: "failed", error: e.code ? null : e.message });
        return;
      }
      netFailures++;
      if (netFailures >= MAX_NET_FAILURES) {
        onState({ phase: "error", error: e });
        return;
      }
    }
    // TODO pause while the tab is hidden, it keeps polling in the background now
    await sleep(delay, signal);
    delay = Math.min(maxDelay, Math.round(delay * 1.5));
  }
}

export function useReport(id: string | undefined) {
  const [state, setState] = useState<ReportState>({ phase: "queued", progress: 0, message: "", eta: null });
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (!id) return;
    const ctrl = new AbortController();
    setState({ phase: "queued", progress: 0, message: "", eta: null });
    pollReport(id, ctrl.signal, (s) => {
      if (!ctrl.signal.aborted) setState(s);
    });
    return () => ctrl.abort();
  }, [id, run]);

  const retry = useCallback(() => setRun((n) => n + 1), []);
  return { state, retry };
}
