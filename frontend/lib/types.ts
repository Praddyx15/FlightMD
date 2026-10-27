// Mirrors flightmd_core/models (schema 1.7). Fields added after 1.5 are optional so
// older stored reports still render.

export type Severity = "critical" | "warning" | "info" | "good";

export type Category =
  | "oscillation"
  | "vibration"
  | "ekf"
  | "battery"
  | "gps"
  | "parameters"
  | "motors"
  | "ascent_profile"
  | "power"
  | "system";

export interface ParamRecommendation {
  param_name: string;
  current_value: number;
  suggested_value: number;
  unit: string | null;
  change_direction: "increase" | "decrease" | "set";
  reason: string;
}

export interface Finding {
  id: string;
  category: Category;
  severity: Severity;
  title: string;
  technical_summary: string;
  plain_english: string;
  recommendation: string;
  confidence: number; // 0-1
  confidence_level?: "high" | "medium" | "low" | null;
  timestamp_start_ms: number | null;
  timestamp_end_ms: number | null;
  t_start_s?: number | null;
  t_end_s?: number | null;
  chart_data: Record<string, unknown> | null;
  param_changes: ParamRecommendation[];
  params?: string[]; // 1.7: parameter names the recommendation touches
}

export interface AnalyserResult {
  analyser: string;
  display_name: string;
  findings: Finding[];
  health_score: number;
  skipped: boolean;
  skip_reason: string | null;
  assessed?: boolean;
  processing_ms: number;
  key_metrics: Record<string, number>;
}

export interface FlightMetadata {
  duration_seconds: number;
  firmware_version: string | null;
  hardware_id: string | null;
  airframe_id: number | null;
  airframe_name: string | null;
  vehicle_type: string | null;
  log_start_utc: string | null;
  arm_count: number;
  flight_modes_used: string[];
  max_altitude_m: number | null;
  max_speed_ms: number | null;
  total_distance_m: number | null;
  px4_version: string | null;
  available_topics: string[];
  weather?: {
    temperature_max_c: number | null;
    temperature_min_c: number | null;
    wind_speed_max_ms: number | null;
    rain_sum_mm: number | null;
    description: string;
  } | null;
  location_name?: string | null;
  gps_path?: [number, number, number][] | null;
  gps_path_wind_speed_ms?: (number | null)[] | null;
  gps_path_hdop?: (number | null)[] | null;
  parse_warnings?: string[] | null;
  armed_windows?: [number, number][] | null; // log-relative seconds
  // 1.7
  gps_path_t_s?: number[] | null; // same order as gps_path
  source_format?: string | null; // detector id, e.g. "px4_ulog"
  log_sha256?: string | null;
  planning_brief_sha256?: string | null; // AeroAtlas brief the flight was planned with
}

export interface FlightMDReport {
  report_id: string;
  schema_version: string;
  overall_score: number;
  score_label: string;
  letter_grade: string;
  executive_summary: string;
  metadata: FlightMetadata;
  findings: Finding[];
  param_change_sheet: ParamRecommendation[];
  analyser_results: AnalyserResult[];
  assessed_fraction?: number | null;
  processing_time_ms: number;
  file_name: string;
  file_size_bytes: number;
  generated_at?: string | null; // 1.7, ISO
}

export type JobStatus = "processing" | "complete" | "failed";

export interface StatusResponse {
  status: JobStatus;
  progress: number;
  message: string;
  error?: string;
  eta_seconds?: number | null;
}

export interface AnalyseResponse {
  report_id: string;
  status: "processing" | "complete";
  estimated_seconds: number;
  airframe_token?: string;
  deduplicated?: boolean; // same bytes as an earlier upload: report_id is that one
  contribution_id?: string; // with contribute_to_dataset; DELETE /dataset/{id} withdraws it
}

export interface TrendFlight {
  report_id: string;
  file_name: string;
  created_at: number;
  overall_score: number;
  letter_grade: string;
  // null (or missing) = module skipped / not assessed on that flight
  module_scores: Record<string, number | null>;
  key_metrics: Record<string, number>;
}

export interface TrendsResponse {
  airframe_label: string;
  flight_count: number;
  flights: TrendFlight[];
}

export interface DiffFlightSummary {
  report_id: string;
  file_name: string;
  overall_score: number;
  letter_grade: string;
  score_label: string;
}

export interface DiffModuleScoreDelta {
  a: number | null;
  b: number | null;
  delta: number | null;
}

export interface DiffKeyMetricDelta {
  a: number | null;
  b: number | null;
  delta: number | null;
}

export interface DiffPersistingCategory {
  category: Category;
  severity_a: Severity;
  severity_b: Severity;
}

export interface DiffResponse {
  a: DiffFlightSummary;
  b: DiffFlightSummary;
  overall_score_delta: number;
  module_score_deltas: Record<string, DiffModuleScoreDelta>;
  key_metric_deltas: Record<string, DiffKeyMetricDelta>;
  findings_diff: {
    resolved: string[];
    new: string[];
    persisting_categories: DiffPersistingCategory[];
  };
}

export interface MaintenanceEntry {
  date: string;
  maintenance_type: string;
  notes: string;
}

export interface AlertRule {
  metric: string;
  comparison: "lt" | "gt";
  threshold: number;
  label: string;
}

export interface AirframeConfigResponse {
  airframe_label: string;
  checklist_items: string[];
  maintenance_log: MaintenanceEntry[];
  maintenance_interval_hours: number | null;
  alert_rules: AlertRule[];
  webhook_url: string | null;
  total_flight_hours: number;
  hours_since_maintenance: number;
  maintenance_due: boolean;
  flight_count: number;
  airframe_token?: string;
}

// tune, fly, verify: parameter changes marked as applied on an airframe
export interface AppliedParam {
  name: string;
  from_value: number;
  to_value: number;
}

export type VerifyStatus = "pending" | "improved" | "unchanged" | "worse" | "mixed";

export interface ChangeVerify {
  status: VerifyStatus;
  next_report_id: string | null;
  findings_resolved: string[];
  findings_new: string[];
  metric_deltas: Record<string, number | null>;
}

export interface ChangeRecord {
  id: string;
  report_id: string;
  changes: AppliedParam[];
  applied_by: "user" | "uaop";
  note?: string | null;
  created_at: string | number;
  verify: ChangeVerify;
}

export interface NewChangeRecord {
  report_id: string;
  changes: AppliedParam[];
  applied_by: "user" | "uaop";
  note?: string;
}
