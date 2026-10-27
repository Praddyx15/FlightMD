import { fmtNum } from "./format";

export const MODULE_LABELS: Record<string, string> = {
  oscillation:    "Oscillation",
  vibration:      "Vibration",
  ekf:            "EKF Health",
  battery:        "Battery",
  gps:            "GPS Quality",
  parameters:     "Parameters",
  motors:         "Motors / ESC",
  ascent_profile: "Ascent & Recovery",
};

interface MetricMeta {
  label: string;
  unit: string;
  digits: number;
}

const METRIC_META: Record<string, MetricMeta> = {
  "oscillation.roll_peak_hz":   { label: "Roll oscillation frequency", unit: "Hz", digits: 1 },
  "oscillation.pitch_peak_hz":  { label: "Pitch oscillation frequency", unit: "Hz", digits: 1 },
  "oscillation.yaw_peak_hz":    { label: "Yaw oscillation frequency", unit: "Hz", digits: 1 },
  "oscillation.roll_norm_amp":  { label: "Roll oscillation amplitude", unit: "", digits: 2 },
  "oscillation.pitch_norm_amp": { label: "Pitch oscillation amplitude", unit: "", digits: 2 },
  "oscillation.yaw_norm_amp":   { label: "Yaw oscillation amplitude", unit: "", digits: 2 },
  "vibration.max_imu_rms":      { label: "Max IMU vibration (RMS)", unit: "m/s²", digits: 1 },
  "vibration.total_clip_count": { label: "IMU clip count", unit: "", digits: 0 },
  "battery.sag_per_cell_v":     { label: "Battery sag per cell", unit: "V", digits: 2 },
  "ekf.max_innovation_ratio":   { label: "Max EKF innovation ratio", unit: "", digits: 2 },
  "gps.max_hdop":               { label: "Max GPS HDOP", unit: "", digits: 1 },
  "gps.min_satellites":         { label: "Min satellites tracked", unit: "", digits: 0 },
  "motors.motor_balance_index": { label: "Motor balance index", unit: "", digits: 2 },
  "parameters.anomaly_count":   { label: "Parameter anomalies", unit: "", digits: 0 },
  "ascent_profile.apogee_altitude_m":                { label: "Apogee altitude", unit: "m AGL", digits: 0 },
  "ascent_profile.time_to_apogee_s":                 { label: "Time to apogee", unit: "s", digits: 1 },
  "ascent_profile.peak_boost_g":                     { label: "Peak boost acceleration", unit: "g", digits: 1 },
  "ascent_profile.boost_duration_s":                 { label: "Boost duration", unit: "s", digits: 1 },
  "ascent_profile.parachute_deployment_altitude_m":  { label: "Parachute deployment altitude", unit: "m AGL", digits: 0 },
  "ascent_profile.time_from_apogee_to_deployment_s": { label: "Apogee to deployment", unit: "s", digits: 1 },
};

// Unknown keys get a humanised label so a new metric never renders blank.
export function humaniseMetricKey(key: string): MetricMeta {
  if (METRIC_META[key]) return METRIC_META[key];
  const metric = key.includes(".") ? key.slice(key.indexOf(".") + 1) : key;
  const label = metric.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  const counts = /count|satellites|_n$|num_/.test(metric);
  return { label, unit: "", digits: counts ? 0 : 2 };
}

export function formatMetric(key: string, value: number | null | undefined): string {
  const { unit, digits } = humaniseMetricKey(key);
  return fmtNum(value, digits, unit || undefined);
}
