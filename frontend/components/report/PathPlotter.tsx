"use client";

import { useMemo, useRef, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { Box, Compass, Map as MapIcon, Radio, RotateCcw, Wind } from "lucide-react";
import type { FlightMDReport } from "@/lib/types";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { RAMP_CSS, minMax, type PathColorMode } from "@/components/three/flightPathGeometry";
import type { FlightPathCameraHandle } from "@/components/three/FlightPathScene";

const FlightPathMap = dynamic(() => import("./FlightPathMap").then((m) => m.FlightPathMap), {
  ssr: false,
  loading: () => <Placeholder text="Loading map" />,
});

// three.js is the biggest chunk in the app; only fetched when someone opens 3D
const FlightPathScene = dynamic(() => import("@/components/three/FlightPathScene").then((m) => m.FlightPathScene), {
  ssr: false,
  loading: () => <Placeholder text="Loading 3D view" />,
});

function Placeholder({ text }: { text: string }) {
  return <div className="flex h-full items-center justify-center text-xs text-fg-muted">{text}…</div>;
}

const LEGEND: Record<Exclude<PathColorMode, "standard">, { label: string; low: string; high: string }> = {
  wind: { label: "Wind speed", low: "calm", high: "strong" },
  signal: { label: "GPS HDOP", low: "good", high: "poor" },
};

function Toggle({ pressed, onClick, children, title }: { pressed: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      title={title}
      className={cn(
        "flex min-h-[28px] items-center gap-1 rounded-sm px-2 text-xs pointer-coarse:min-h-[44px]",
        pressed ? "bg-accent-solid text-on-accent" : "text-fg-muted hover:text-fg"
      )}
    >
      {children}
    </button>
  );
}

export default function PathPlotter({ report }: { report: FlightMDReport }) {
  const m = report.metadata;
  const gpsPath = m.gps_path;
  const cameraApi = useRef<FlightPathCameraHandle | null>(null);
  const [colorMode, setColorMode] = useState<PathColorMode>("standard");
  const [viewMode, setViewMode] = useState<"map" | "3d">("map");

  const hasWind = useMemo(() => (m.gps_path_wind_speed_ms ?? []).some((v) => v != null), [m.gps_path_wind_speed_ms]);
  const hasSignal = useMemo(() => (m.gps_path_hdop ?? []).some((v) => v != null), [m.gps_path_hdop]);
  const altRange = useMemo(() => {
    if (!gpsPath || gpsPath.length === 0) return null;
    const [lo, hi] = minMax(gpsPath.map((p) => p[2]));
    return hi - lo;
  }, [gpsPath]);

  if (!gpsPath || gpsPath.length === 0) {
    return (
      <section aria-labelledby="path-h" className="space-y-3">
        <h2 id="path-h" className="text-base font-semibold">Flight path</h2>
        <p className="panel p-4 text-sm text-fg-muted">No GPS positions in this log, so there is no path to draw.</p>
      </section>
    );
  }

  return (
    <section aria-labelledby="path-h" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="path-h" className="text-base font-semibold">Flight path</h2>
        <div className="no-print ml-auto flex flex-wrap items-center gap-2">
          <div role="group" aria-label="View" className="flex gap-0.5 rounded border p-0.5">
            <Toggle pressed={viewMode === "map"} onClick={() => setViewMode("map")}>
              <MapIcon aria-hidden className="h-3.5 w-3.5" /> Map
            </Toggle>
            <Toggle pressed={viewMode === "3d"} onClick={() => setViewMode("3d")}>
              <Box aria-hidden className="h-3.5 w-3.5" /> 3D
            </Toggle>
          </div>
          {(hasWind || hasSignal) && (
            <div role="group" aria-label="Path colour" className="flex gap-0.5 rounded border p-0.5">
              <Toggle pressed={colorMode === "standard"} onClick={() => setColorMode("standard")}>Plain</Toggle>
              {hasWind && (
                <Toggle pressed={colorMode === "wind"} onClick={() => setColorMode("wind")} title="Colour by wind speed">
                  <Wind aria-hidden className="h-3.5 w-3.5" /> Wind
                </Toggle>
              )}
              {hasSignal && (
                <Toggle pressed={colorMode === "signal"} onClick={() => setColorMode("signal")} title="Colour by GPS HDOP">
                  <Radio aria-hidden className="h-3.5 w-3.5" /> HDOP
                </Toggle>
              )}
            </div>
          )}
          {viewMode === "3d" && (
            <div className="flex gap-1">
              <button type="button" onClick={() => cameraApi.current?.top()} className="btn px-2 text-xs">
                <Compass aria-hidden className="h-3.5 w-3.5" /> Top
              </button>
              <button type="button" onClick={() => cameraApi.current?.reset()} className="btn px-2 text-xs">
                <RotateCcw aria-hidden className="h-3.5 w-3.5" /> Reset
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="panel relative h-[300px] overflow-hidden sm:h-[380px]">
        <ErrorBoundary what={viewMode === "map" ? "Map" : "3D view"}>
          {viewMode === "map" ? (
            <FlightPathMap
              gpsPath={gpsPath}
              className="h-full w-full"
              colorMode={colorMode}
              windSpeedPath={m.gps_path_wind_speed_ms}
              signalQualityPath={m.gps_path_hdop}
            />
          ) : (
            <FlightPathScene
              gpsPath={gpsPath}
              className="h-full w-full"
              cameraApiRef={cameraApi}
              colorMode={colorMode}
              windSpeedPath={m.gps_path_wind_speed_ms}
              signalQualityPath={m.gps_path_hdop}
            />
          )}
        </ErrorBoundary>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-muted">
        {colorMode === "standard" ? (
          <>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-3 w-3 rounded-full border-[3px] border-accent" /> Launch
            </span>
            <span className="flex items-center gap-1.5">
              <span aria-hidden className="inline-block h-2.5 w-2.5 bg-fg" /> Land / log end
            </span>
          </>
        ) : (
          <span className="flex items-center gap-1.5">
            {LEGEND[colorMode].label}: {LEGEND[colorMode].low}
            <span aria-hidden className="inline-block h-2 w-16 rounded-sm" style={{ background: RAMP_CSS }} />
            {LEGEND[colorMode].high}; grey = no reading
          </span>
        )}
        <span className="num">Altitude range (GPS): {fmtNum(altRange, 1, "m")}</span>
        <span className="num">Distance: {fmtNum(m.total_distance_m, 0, "m")}</span>
        {viewMode === "3d" && <span>Drag to orbit, scroll to zoom. Height ×3.</span>}
      </div>
    </section>
  );
}
