import { describe, expect, it } from "vitest";
import { airbriefAuditUrl, airbriefBriefUrl } from "@/lib/api";

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

describe("airbriefBriefUrl", () => {
  const sha = "AB".repeat(32);

  it("opens the brief by its hash", () => {
    expect(airbriefBriefUrl(sha, "https://airbrief.example")).toBe(`https://airbrief.example/w/report?brief=${"ab".repeat(32)}`);
  });

  it("is null without an AirBrief address or with something that is not a hash", () => {
    expect(airbriefBriefUrl(sha, "")).toBeNull();
    expect(airbriefBriefUrl("abc", "https://airbrief.example")).toBeNull();
  });
});
