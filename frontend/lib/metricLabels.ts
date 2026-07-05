export const MODULE_LABELS: Record<string, string> = {
  oscillation: "Oscillation",
  vibration:   "Vibration",
  ekf:         "EKF Health",
  battery:     "Battery",
  gps:         "GPS Quality",
  parameters:  "Parameters",
  motors:      "Motors / ESC",
};

// Known key_metrics get a friendly label + unit; anything else falls back
// to a humanised version of the raw key so new metrics never render blank.
const METRIC_META: Record<string, { label: string; unit: string }> = {
  "oscillation.roll_peak_hz":   { label: "Roll Oscillation Frequency", unit: " Hz" },
  "oscillation.pitch_peak_hz":  { label: "Pitch Oscillation Frequency", unit: " Hz" },
  "oscillation.yaw_peak_hz":    { label: "Yaw Oscillation Frequency", unit: " Hz" },
  "vibration.max_imu_rms":      { label: "Max IMU Vibration (RMS)", unit: " m/s²" },
  "vibration.total_clip_count": { label: "IMU Clip Count", unit: "" },
  "battery.sag_per_cell_v":     { label: "Battery Sag per Cell", unit: " V" },
  "ekf.max_innovation_ratio":   { label: "Max EKF Innovation Ratio", unit: "" },
  "gps.max_hdop":               { label: "Max GPS HDOP", unit: "" },
  "gps.min_satellites":         { label: "Min Satellites Tracked", unit: "" },
  "motors.motor_balance_index": { label: "Motor Balance Index", unit: "" },
  "parameters.anomaly_count":   { label: "Parameter Anomalies", unit: "" },
};

export function humaniseMetricKey(key: string): { label: string; unit: string } {
  if (METRIC_META[key]) return METRIC_META[key];
  const [, metric] = key.split(".");
  const label = (metric || key).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return { label, unit: "" };
}
