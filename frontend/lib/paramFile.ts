import type { FlightMDReport, ParamRecommendation } from "./types";
import { fmtParam } from "./format";

export type ParamFormat = "missionplanner" | "qgc";

// ArduPilot -> Mission Planner .param, PX4 -> QGroundControl .params. A .tlog can be
// either, so fall back to the parameter names themselves.
export function guessAutopilot(report: FlightMDReport): "ardupilot" | "px4" | null {
  const m = report.metadata;
  const fw = `${m.firmware_version ?? ""} ${m.vehicle_type ?? ""}`.toLowerCase();
  const name = report.file_name.toLowerCase();
  if (m.px4_version || /px4/.test(fw) || /\.ulo?g$/.test(name)) return "px4";
  if (/ardu|copter|plane|rover|sub\b/.test(fw) || name.endsWith(".bin")) return "ardupilot";
  const names = report.param_change_sheet.map((p) => p.param_name);
  if (names.some((n) => /^(ATC_|INS_|PSC_|MOT_|BATT_|EK3_)/.test(n))) return "ardupilot";
  if (names.some((n) => /^(MC_|MPC_|EKF2_|IMU_|COM_)/.test(n))) return "px4";
  return null;
}

export function defaultFormat(report: FlightMDReport): ParamFormat {
  return guessAutopilot(report) === "px4" ? "qgc" : "missionplanner";
}

// Mission Planner reads NAME,VALUE per line and skips # comments
function missionPlanner(params: ParamRecommendation[]): string {
  return [
    "# FlightMD suggested changes",
    ...params.map((p) => `${p.param_name},${fmtParam(p.suggested_value)}`),
  ].join("\n") + "\n";
}

// QGC wants its own header and a MAV_PARAM_TYPE per row; it rejects a row whose type
// doesn't match the vehicle's. We don't know the real type, so whole numbers on both
// sides are written as INT32 (6) and everything else as REAL32 (9).
// TODO ship a PX4 param type table; a float that happens to be whole (MPC_XY_VEL_MAX 12) gets INT32 today
function qgc(params: ParamRecommendation[]): string {
  const rows = params.map((p) => {
    const isInt = Number.isInteger(p.suggested_value) && Number.isInteger(p.current_value);
    return `1\t1\t${p.param_name}\t${fmtParam(p.suggested_value)}\t${isInt ? 6 : 9}`;
  });
  return [
    "# Onboard parameters for Vehicle 1",
    "#",
    "# FlightMD suggested changes",
    "#",
    "# Vehicle-Id Component-Id Name Value Type",
    ...rows,
  ].join("\n") + "\n";
}

export function paramFile(params: ParamRecommendation[], format: ParamFormat): string {
  return format === "qgc" ? qgc(params) : missionPlanner(params);
}

export function paramLine(p: ParamRecommendation, format: ParamFormat): string {
  return format === "qgc"
    ? `${p.param_name}\t${fmtParam(p.suggested_value)}`
    : `${p.param_name},${fmtParam(p.suggested_value)}`;
}

// display names are in messages ("params.formats")
export const FORMAT_FILE: Record<ParamFormat, { name: string }> = {
  missionplanner: { name: "flightmd_changes.param" },
  qgc: { name: "flightmd_changes.params" },
};
