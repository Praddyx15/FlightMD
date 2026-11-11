import type { AbstractIntlMessages } from "next-intl";
import { fmtNum, fmtQty, isNum, toUnit, type Quantity, type UnitSystem } from "./format";

// Display names live in messages/*.json ("modules", "metrics.<module>.<name>"); this file
// only knows units and precision. Keys come from the report as "module.metric".

interface MetricMeta {
  unit: string;
  digits: number;
  qty?: Quantity; // converted with the unit preference
  suffix?: string;
}

const METRIC_META: Record<string, MetricMeta> = {
  "oscillation.roll_peak_hz":   { unit: "Hz", digits: 1 },
  "oscillation.pitch_peak_hz":  { unit: "Hz", digits: 1 },
  "oscillation.yaw_peak_hz":    { unit: "Hz", digits: 1 },
  "oscillation.roll_norm_amp":  { unit: "", digits: 2 },
  "oscillation.pitch_norm_amp": { unit: "", digits: 2 },
  "oscillation.yaw_norm_amp":   { unit: "", digits: 2 },
  "vibration.max_imu_rms":      { unit: "m/s²", digits: 1 },
  "vibration.total_clip_count": { unit: "", digits: 0 },
  "vibration.vibration_vs_limit": { unit: "", digits: 2 },
  "vibration.max_accel_vibration_metric": { unit: "m/s²", digits: 2 },
  "vibration.max_gyro_vibration_metric":  { unit: "rad/s", digits: 3 },
  "power.min_vcc_v":            { unit: "V", digits: 2 },
  "power.vcc_range_v":          { unit: "V", digits: 2 },
  "battery.sag_per_cell_v":     { unit: "V", digits: 2 },
  "ekf.max_innovation_ratio":   { unit: "", digits: 2 },
  "gps.max_hdop":               { unit: "", digits: 1 },
  "gps.min_satellites":         { unit: "", digits: 0 },
  "motors.motor_balance_index": { unit: "", digits: 2 },
  "parameters.anomaly_count":   { unit: "", digits: 0 },
  "ascent_profile.apogee_altitude_m":                { unit: "m AGL", digits: 0, qty: "altitude", suffix: " AGL" },
  "ascent_profile.time_to_apogee_s":                 { unit: "s", digits: 1 },
  "ascent_profile.peak_boost_g":                     { unit: "g", digits: 1 },
  "ascent_profile.boost_duration_s":                 { unit: "s", digits: 1 },
  "ascent_profile.parachute_deployment_altitude_m":  { unit: "m AGL", digits: 0, qty: "altitude", suffix: " AGL" },
  "ascent_profile.time_from_apogee_to_deployment_s": { unit: "s", digits: 1 },
};

type Node = AbstractIntlMessages | string | undefined;

function lookup(messages: Node, path: string[]): string | undefined {
  let cur = messages;
  for (const p of path) {
    if (!cur || typeof cur === "string") return undefined;
    cur = cur[p];
  }
  return typeof cur === "string" ? cur : undefined;
}

function splitKey(key: string): [string, string] {
  const i = key.indexOf(".");
  return i < 0 ? ["", key] : [key.slice(0, i), key.slice(i + 1)];
}

export interface MetricInfo {
  label: string;
  unit: string;
  digits: number;
}

export interface Labels {
  module: (key: string) => string;
  metric: (key: string, sys?: UnitSystem) => MetricInfo;
  format: (key: string, value: number | null | undefined, sys?: UnitSystem) => string;
  // value in the unit metric() reports for the same system
  convert: (key: string, value: number | null, sys?: UnitSystem) => number | null;
}

export function makeLabels(messages: AbstractIntlMessages): Labels {
  const meta = (key: string): MetricMeta => {
    if (METRIC_META[key]) return METRIC_META[key];
    const counts = /count|satellites|_n$|num_/.test(splitKey(key)[1]);
    return { unit: "", digits: counts ? 0 : 2 };
  };

  return {
    module: (key) => lookup(messages, ["modules", key]) ?? key,

    // Unknown keys get a humanised label so a new metric never renders blank.
    metric(key, sys = "metric") {
      const [mod, name] = splitKey(key);
      const m = meta(key);
      const label = lookup(messages, ["metrics", mod, name]) ??
        name.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
      const unit = m.qty ? `${toUnit(0, m.qty, sys).unit}${m.suffix ?? ""}` : m.unit;
      return { label, unit, digits: m.digits };
    },

    format(key, value, sys = "metric") {
      const m = meta(key);
      if (m.qty) {
        const s = fmtQty(value, m.qty, sys, m.digits);
        return isNum(value) ? `${s}${m.suffix ?? ""}` : s;
      }
      return fmtNum(value, m.digits, m.unit || undefined);
    },

    convert(key, value, sys = "metric") {
      const m = meta(key);
      return m.qty && isNum(value) ? toUnit(value, m.qty, sys).value : value;
    },
  };
}
