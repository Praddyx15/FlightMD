"use client";

import { useMemo, useRef, useState } from "react";
import { FlightMDReport } from "../../lib/types";
import { Compass, RotateCcw, Map, Wind, Radio } from "lucide-react";
import {
  FlightPathScene, type FlightPathCameraHandle, type PathColorMode,
} from "@/components/three/FlightPathScene";

interface PathPlotterProps {
  report: FlightMDReport;
}

const COLOR_MODE_LEGEND: Record<Exclude<PathColorMode, "standard">, { label: string; low: string; high: string }> = {
  wind:   { label: "Wind Speed", low: "Calm", high: "Strong" },
  signal: { label: "GPS Signal Quality", low: "Good", high: "Poor" },
};

export default function PathPlotter({ report }: PathPlotterProps) {
  const gpsPath = report.metadata.gps_path;
  const cameraApi = useRef<FlightPathCameraHandle | null>(null);
  const [colorMode, setColorMode] = useState<PathColorMode>("standard");

  const hasWindData = useMemo(
    () => (report.metadata.gps_path_wind_speed_ms ?? []).some((v) => v !== null && v !== undefined),
    [report.metadata.gps_path_wind_speed_ms]
  );
  const hasSignalData = useMemo(
    () => (report.metadata.gps_path_hdop ?? []).some((v) => v !== null && v !== undefined),
    [report.metadata.gps_path_hdop]
  );

  if (!gpsPath || gpsPath.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 text-center text-slate-500 text-sm">
        No flight path data available (missing GPS coordinates in log file).
      </div>
    );
  }

  const alts = gpsPath.map((p) => p[2]);
  const maxAlt = Math.max(...alts) - Math.min(...alts);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center space-x-2">
          <Map className="w-5 h-5 text-indigo-400" />
          <h3 className="font-semibold text-slate-100">Flight Path</h3>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {(hasWindData || hasSignalData) && (
            <div className="flex bg-slate-850 rounded-lg p-1 border border-slate-800 gap-1">
              <button
                onClick={() => setColorMode("standard")}
                title="Standard colouring"
                className={`px-2.5 py-1.5 rounded-md text-xs font-semibold transition-all ${colorMode === "standard" ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
              >
                Standard
              </button>
              {hasWindData && (
                <button
                  onClick={() => setColorMode("wind")}
                  title="Colour path by wind speed"
                  className={`px-2.5 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center gap-1 ${colorMode === "wind" ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
                >
                  <Wind className="w-3.5 h-3.5" />
                  Wind
                </button>
              )}
              {hasSignalData && (
                <button
                  onClick={() => setColorMode("signal")}
                  title="Colour path by GPS signal quality"
                  className={`px-2.5 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center gap-1 ${colorMode === "signal" ? "bg-slate-700 text-slate-100" : "text-slate-400 hover:text-slate-200"}`}
                >
                  <Radio className="w-3.5 h-3.5" />
                  Signal
                </button>
              )}
            </div>
          )}
          <div className="flex bg-slate-850 rounded-lg p-1 border border-slate-800 gap-1">
            <button
              onClick={() => cameraApi.current?.top()}
              title="Top-down view"
              className="px-3 py-1.5 rounded-md text-xs font-semibold transition-all text-slate-400 hover:text-slate-200 flex items-center gap-1.5"
            >
              <Compass className="w-3.5 h-3.5" />
              Top View
            </button>
            <button
              onClick={() => cameraApi.current?.reset()}
              title="Reset to default orbit view"
              className="px-3 py-1.5 rounded-md text-xs font-semibold transition-all text-slate-400 hover:text-slate-200 flex items-center gap-1.5"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reset View
            </button>
          </div>
        </div>
      </div>

      <div className="relative bg-slate-950 rounded-xl overflow-hidden border border-slate-850 h-[380px]">
        <FlightPathScene
          gpsPath={gpsPath}
          className="w-full h-full"
          cameraApiRef={cameraApi}
          colorMode={colorMode}
          windSpeedPath={report.metadata.gps_path_wind_speed_ms}
          signalQualityPath={report.metadata.gps_path_hdop}
        />

        {/* Legend */}
        <div className="absolute bottom-4 left-4 bg-slate-900/90 border border-slate-800 rounded-lg px-3 py-2 text-xxs text-slate-300 font-mono space-y-1 backdrop-blur-sm pointer-events-none">
          {colorMode === "standard" ? (
            <>
              <div className="flex items-center space-x-2">
                <span className="w-2.5 h-2.5 bg-[#0DD97C] rounded-full inline-block" />
                <span>Launch Point</span>
              </div>
              <div className="flex items-center space-x-2">
                <span className="w-2.5 h-2.5 bg-[#f43f5e] rounded-full inline-block" />
                <span>Land/Stop Point</span>
              </div>
            </>
          ) : (
            <div className="flex items-center space-x-2">
              <span className="text-slate-400">{COLOR_MODE_LEGEND[colorMode].label}:</span>
              <span className="w-16 h-2 rounded-full inline-block" style={{
                background: colorMode === "wind"
                  ? "linear-gradient(90deg, #1c52d9, #e6bf1a, #f22626)"
                  : "linear-gradient(90deg, #0dd973, #e6bf1a, #f22626)",
              }} />
              <span className="text-slate-500">{COLOR_MODE_LEGEND[colorMode].low} → {COLOR_MODE_LEGEND[colorMode].high}</span>
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="absolute top-4 right-4 bg-slate-900/90 border border-slate-800 rounded-lg px-3 py-2 text-xxs text-slate-300 font-mono space-y-1 backdrop-blur-sm pointer-events-none">
          <div>Max Altitude: <span className="text-emerald-400">{maxAlt.toFixed(1)} m</span></div>
          {report.metadata.total_distance_m && (
            <div>Distance: <span className="text-indigo-400">{report.metadata.total_distance_m.toFixed(0)} m</span></div>
          )}
        </div>

        {/* Interaction hint */}
        <div className="absolute bottom-4 right-4 text-xxs text-slate-500 pointer-events-none">
          Drag to orbit · Scroll to zoom
        </div>
      </div>
    </div>
  );
}
