import { describe, expect, it } from "vitest";
import { defaultFormat, guessAutopilot, paramFile, paramLine } from "@/lib/paramFile";
import { param, report } from "./fixtures";

describe("guessAutopilot", () => {
  it("reads PX4 from the version or a .ulg name", () => {
    expect(guessAutopilot(report({}, { px4_version: "v1.14.0" }))).toBe("px4");
    expect(guessAutopilot(report({ file_name: "log_12.ulg" }))).toBe("px4");
  });

  it("reads ArduPilot from the firmware or a .bin name", () => {
    expect(guessAutopilot(report({}, { firmware_version: "ArduCopter V4.5.1" }))).toBe("ardupilot");
    expect(guessAutopilot(report({ file_name: "00000042.BIN" }))).toBe("ardupilot");
  });

  it("falls back to the parameter names for a tlog", () => {
    expect(guessAutopilot(report({ param_change_sheet: [param({ param_name: "ATC_RAT_RLL_P" })] }))).toBe("ardupilot");
    expect(guessAutopilot(report({ param_change_sheet: [param({ param_name: "MC_ROLLRATE_P" })] }))).toBe("px4");
    expect(guessAutopilot(report())).toBeNull();
  });

  it("defaults PX4 to QGroundControl and everything else to Mission Planner", () => {
    expect(defaultFormat(report({ file_name: "a.ulg" }))).toBe("qgc");
    expect(defaultFormat(report())).toBe("missionplanner");
  });
});

describe("paramFile", () => {
  const params = [param(), param({ param_name: "MPC_XY_VEL_MAX", current_value: 12, suggested_value: 10 })];

  it("writes Mission Planner NAME,VALUE lines", () => {
    expect(paramFile(params, "missionplanner")).toBe(
      "# FlightMD suggested changes\nMC_ROLLRATE_P,0.12\nMPC_XY_VEL_MAX,10\n"
    );
  });

  it("writes QGroundControl rows with a type per value", () => {
    const lines = paramFile(params, "qgc").trimEnd().split("\n");
    expect(lines[0]).toBe("# Onboard parameters for Vehicle 1");
    expect(lines).toContain("1\t1\tMC_ROLLRATE_P\t0.12\t9");
    expect(lines).toContain("1\t1\tMPC_XY_VEL_MAX\t10\t6");
  });

  it("copies single lines in the chosen format", () => {
    expect(paramLine(params[0], "missionplanner")).toBe("MC_ROLLRATE_P,0.12");
    expect(paramLine(params[0], "qgc")).toBe("MC_ROLLRATE_P\t0.12");
  });
});
