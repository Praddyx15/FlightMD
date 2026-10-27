"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, getReport, getStatus } from "./api";
import type { FlightMDReport } from "./types";

export type ReportState =
  | { phase: "queued" | "processing"; progress: number; message: string }
  | { phase: "done"; report: FlightMDReport }
  | { phase: "failed"; error: string }
  | { phase: "expired" }
  | { phase: "error"; error: string } // network trouble, retries used up
  | { phase: "stopped" }; // gave up waiting; user can resume

const FIRST_DELAY = 1000;
const MAX_DELAY = 5000;
const MAX_WAIT_MS = 10 * 60_000;
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
export function useReport(id: string | undefined) {
  const [state, setState] = useState<ReportState>({ phase: "queued", progress: 0, message: "" });
  const [run, setRun] = useState(0);

  useEffect(() => {
    if (!id) return;
    const ctrl = new AbortController();
    const { signal } = ctrl;
    setState({ phase: "queued", progress: 0, message: "" });

    (async () => {
      const started = Date.now();
      let delay = FIRST_DELAY;
      let netFailures = 0;

      while (!signal.aborted) {
        if (Date.now() - started > MAX_WAIT_MS) {
          setState({ phase: "stopped" });
          return;
        }
        try {
          const st = await getStatus(id, signal);
          netFailures = 0;
          if (st.status === "failed") {
            setState({ phase: "failed", error: st.error || "The log could not be analysed." });
            return;
          }
          if (st.status === "complete") {
            const report = await getReport(id, signal);
            if (report) {
              setState({ phase: "done", report });
              return;
            }
          } else {
            setState({
              phase: st.progress > 0 ? "processing" : "queued",
              progress: st.progress,
              message: st.message,
            });
          }
        } catch (e) {
          if (signal.aborted) return;
          if (e instanceof ApiError && e.status === 404) {
            setState({ phase: "expired" });
            return;
          }
          if (e instanceof ApiError && (e.status === 422 || e.status === 500)) {
            setState({ phase: "failed", error: e.message });
            return;
          }
          netFailures++;
          if (netFailures >= MAX_NET_FAILURES) {
            setState({ phase: "error", error: e instanceof Error ? e.message : "Could not reach the server." });
            return;
          }
        }
        // TODO pause while the tab is hidden, it keeps polling in the background now
        await sleep(delay, signal);
        delay = Math.min(MAX_DELAY, Math.round(delay * 1.5));
      }
    })();

    return () => ctrl.abort();
  }, [id, run]);

  const retry = useCallback(() => setRun((n) => n + 1), []);
  return { state, retry };
}
