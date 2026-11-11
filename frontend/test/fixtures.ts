import type { Finding, FlightMDReport, ParamRecommendation } from "@/lib/types";

export function finding(over: Partial<Finding> = {}): Finding {
  return {
    id: "f1",
    category: "battery",
    severity: "warning",
    title: "Battery sag",
    technical_summary: "",
    plain_english: "",
    recommendation: "",
    confidence: 0.9,
    timestamp_start_ms: null,
    timestamp_end_ms: null,
    chart_data: null,
    param_changes: [],
    ...over,
  };
}

export function param(over: Partial<ParamRecommendation> = {}): ParamRecommendation {
  return {
    param_name: "MC_ROLLRATE_P",
    current_value: 0.15000000596046448,
    suggested_value: 0.12,
    unit: null,
    change_direction: "decrease",
    reason: "roll oscillation",
    ...over,
  };
}

export function report(over: Partial<FlightMDReport> = {}, meta: Partial<FlightMDReport["metadata"]> = {}): FlightMDReport {
  return {
    report_id: "r1",
    schema_version: "1.7",
    overall_score: 72,
    score_label: "Caution",
    letter_grade: "C",
    executive_summary: "",
    findings: [],
    param_change_sheet: [],
    analyser_results: [],
    processing_time_ms: 1000,
    file_name: "flight.tlog",
    file_size_bytes: 1000,
    ...over,
    metadata: {
      duration_seconds: 300,
      firmware_version: null,
      hardware_id: null,
      airframe_id: null,
      airframe_name: null,
      vehicle_type: null,
      log_start_utc: null,
      arm_count: 1,
      flight_modes_used: [],
      max_altitude_m: null,
      max_speed_ms: null,
      total_distance_m: null,
      px4_version: null,
      available_topics: [],
      ...meta,
    },
  };
}
