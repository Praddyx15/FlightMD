// @vitest-environment node
// Node's fetch rejects jsdom's AbortSignal, and the poller always passes one, so this
// file runs without a DOM and drives pollReport (the state machine behind useReport).
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { API_URL } from "@/lib/api";
import { pollReport, type PollOptions, type ReportState } from "@/lib/useReport";
import { report } from "./fixtures";

const server = setupServer();
const FAST = { firstDelay: 1, maxDelay: 1 };

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

async function run(id = "r1", opts: PollOptions = FAST) {
  const states: ReportState[] = [];
  await pollReport(id, new AbortController().signal, (s) => states.push(s), opts);
  return states;
}

const status = (body: object, init?: ResponseInit) =>
  http.get(`${API_URL}/status/:id`, () => HttpResponse.json(body, init));

describe("pollReport", () => {
  it("goes from queued through processing to done", async () => {
    const steps = [
      { status: "processing", progress: 0, message: "" },
      { status: "processing", progress: 40, message: "Parsing", eta_seconds: 12 },
      { status: "complete", progress: 100, message: "" },
    ];
    let n = 0;
    server.use(
      http.get(`${API_URL}/status/:id`, () => HttpResponse.json(steps[Math.min(n++, steps.length - 1)])),
      http.get(`${API_URL}/report/:id`, () => HttpResponse.json(report()))
    );

    const states = await run();
    expect(states.map((s) => s.phase)).toEqual(["queued", "processing", "done"]);
    expect(states[1]).toMatchObject({ progress: 40, message: "Parsing", eta: 12 });
    expect(states[2]).toMatchObject({ phase: "done", report: { report_id: "r1" } });
  });

  it("reports an expired report on 404", async () => {
    server.use(status({ detail: "Report not found or expired." }, { status: 404 }));
    expect(await run()).toEqual([{ phase: "expired" }]);
  });

  it("keeps polling when the report is still being written (202 after complete)", async () => {
    let reportCalls = 0;
    server.use(
      status({ status: "complete", progress: 100, message: "" }),
      http.get(`${API_URL}/report/:id`, () => {
        reportCalls++;
        return reportCalls === 1
          ? HttpResponse.json({ detail: "Analysis still in progress." }, { status: 202 })
          : HttpResponse.json(report());
      })
    );

    const states = await run();
    expect(reportCalls).toBe(2);
    expect(states.map((s) => s.phase)).toEqual(["done"]);
  });

  it("fails with the server's reason when the report answers 422", async () => {
    server.use(
      status({ status: "complete", progress: 100, message: "" }),
      http.get(`${API_URL}/report/:id`, () => HttpResponse.json({ detail: "Not a flight log" }, { status: 422 }))
    );
    expect(await run()).toEqual([{ phase: "failed", error: "Not a flight log" }]);
  });

  it("fails when the status says failed", async () => {
    server.use(status({ status: "failed", progress: 0, message: "", error: "Corrupt header" }));
    expect(await run()).toEqual([{ phase: "failed", error: "Corrupt header" }]);
  });

  it("stops after five network errors in a row", async () => {
    let calls = 0;
    server.use(
      http.get(`${API_URL}/status/:id`, () => {
        calls++;
        return HttpResponse.error();
      })
    );

    const states = await run();
    expect(calls).toBe(5);
    expect(states).toHaveLength(1);
    expect(states[0].phase).toBe("error");
  });

  it("gives up after the wait cap", async () => {
    server.use(status({ status: "processing", progress: 10, message: "" }));
    expect(await run("r1", { ...FAST, maxWaitMs: -1 })).toEqual([{ phase: "stopped" }]);
  });

  it("stops quietly when aborted", async () => {
    server.use(status({ status: "processing", progress: 10, message: "" }));
    const ctrl = new AbortController();
    const states: ReportState[] = [];
    const done = pollReport("r1", ctrl.signal, (s) => {
      states.push(s);
      ctrl.abort();
    }, FAST);
    await done;
    expect(states).toHaveLength(1);
  });
});
