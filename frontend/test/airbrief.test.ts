import { describe, expect, it } from "vitest";
import { airbriefAuditUrl } from "@/lib/api";

describe("airbriefAuditUrl", () => {
  it("opens AirBrief's flight audit with the report's share link", () => {
    const url = airbriefAuditUrl("r 1", "https://flightmd.example", "https://airbrief.example");
    expect(url).toBe(
      "https://airbrief.example/w/view?m=flight-audit&report_url=" +
        encodeURIComponent("https://flightmd.example/report/r%201"),
    );
  });

  it("is null when no AirBrief address is set", () => {
    expect(airbriefAuditUrl("r1", "https://flightmd.example", "")).toBeNull();
  });
});
