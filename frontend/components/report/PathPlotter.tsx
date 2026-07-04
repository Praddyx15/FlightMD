"use client";

import { useRef } from "react";
import { FlightMDReport } from "../../lib/types";
import { Compass, RotateCcw, Map } from "lucide-react";
import { FlightPathScene, type FlightPathCameraHandle } from "@/components/three/FlightPathScene";

interface PathPlotterProps {
  report: FlightMDReport;
}

export default function PathPlotter({ report }: PathPlotterProps) {
  const gpsPath = report.metadata.gps_path;
  const cameraApi = useRef<FlightPathCameraHandle | null>(null);

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
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Map className="w-5 h-5 text-indigo-400" />
          <h3 className="font-semibold text-slate-100">Flight Path</h3>
        </div>
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

      <div className="relative bg-slate-950 rounded-xl overflow-hidden border border-slate-850 h-[380px]">
        <FlightPathScene
          gpsPath={gpsPath}
          className="w-full h-full"
          cameraApiRef={cameraApi}
        />

        {/* Legend */}
        <div className="absolute bottom-4 left-4 bg-slate-900/90 border border-slate-800 rounded-lg px-3 py-2 text-xxs text-slate-300 font-mono space-y-1 backdrop-blur-sm pointer-events-none">
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 bg-[#0DD97C] rounded-full inline-block" />
            <span>Launch Point</span>
          </div>
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 bg-[#f43f5e] rounded-full inline-block" />
            <span>Land/Stop Point</span>
          </div>
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
