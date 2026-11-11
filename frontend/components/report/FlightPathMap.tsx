"use client";

import { useEffect, useMemo } from "react";
import { MapContainer, Marker, Polyline, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  normaliseValues, rampColour, rgbCss, sampleIndices, type PathColorMode,
} from "@/components/three/flightPathGeometry";

interface Props {
  gpsPath: [number, number, number][];
  colorMode: PathColorMode;
  windSpeedPath?: (number | null)[] | null;
  signalQualityPath?: (number | null)[] | null;
  // log-relative seconds per gps_path point (schema 1.7), for highlighting a finding
  times?: number[] | null;
  highlight?: { start: number; end: number | null } | null;
  labels: { launch: string; land: string };
  className?: string;
}

// todo: a bundled basemap so the map works offline; the env var covers self-hosted tiles for now
const TILE_URL = process.env.NEXT_PUBLIC_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION = process.env.NEXT_PUBLIC_TILE_ATTRIBUTION ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const BINS = 8;

function bearingDeg(a: [number, number], b: [number, number]): number {
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180;
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

// launch = hollow circle, land = filled square: told apart by shape, not colour
const launchIcon = L.divIcon({
  className: "",
  html: '<div style="width:14px;height:14px;border-radius:9999px;border:3px solid var(--accent);background:var(--surface)"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

const landIcon = L.divIcon({
  className: "",
  html: '<div style="width:12px;height:12px;background:var(--text);border:2px solid var(--surface)"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

const spotIcon = L.divIcon({
  className: "",
  html: '<div style="width:16px;height:16px;border-radius:9999px;border:3px solid var(--accent);background:transparent"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

function arrowIcon(rotationDeg: number) {
  return L.divIcon({
    className: "",
    html: `<div style="transform:rotate(${rotationDeg}deg);width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:10px solid var(--text)"></div>`,
    iconSize: [10, 10],
    iconAnchor: [5, 5],
  });
}

function FitBounds({ positions }: { positions: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length > 0) map.fitBounds(L.latLngBounds(positions), { padding: [30, 30] });
  }, [positions, map]);
  return null;
}

export function FlightPathMap({
  gpsPath, colorMode, windSpeedPath, signalQualityPath, times, highlight, labels, className,
}: Props) {
  // <= 1000 points; the values arrays are indexed the same way as gpsPath
  const idx = useMemo(() => sampleIndices(gpsPath.length), [gpsPath]);
  const positions = useMemo<[number, number][]>(() => idx.map((i) => [gpsPath[i][0], gpsPath[i][1]]), [idx, gpsPath]);

  // Consecutive points in the same colour bin merge into one polyline, so a coloured
  // path is a handful of layers instead of one per sample.
  const runs = useMemo(() => {
    if (colorMode === "standard") return null;
    const t = normaliseValues(colorMode === "wind" ? windSpeedPath : signalQualityPath);
    if (!t) return null;
    const binOf = (i: number) => {
      const v = t[i];
      return v === null || v === undefined ? -1 : Math.min(BINS - 1, Math.floor(v * BINS));
    };
    const out: { bin: number; from: number; pos: [number, number][] }[] = [];
    idx.forEach((src, k) => {
      const bin = binOf(src);
      const last = out[out.length - 1];
      if (last && last.bin === bin) last.pos.push(positions[k]);
      else out.push({ bin, from: k, pos: last ? [last.pos[last.pos.length - 1], positions[k]] : [positions[k]] });
    });
    return out;
  }, [colorMode, windSpeedPath, signalQualityPath, idx, positions]);

  // the stretch of path flown during the active finding; a single spot for an instant one
  const marked = useMemo(() => {
    if (!highlight || !times || times.length !== gpsPath.length) return null;
    const { start, end } = highlight;
    if (end !== null && end > start) {
      const pos = positions.filter((_, k) => times[idx[k]] >= start && times[idx[k]] <= end);
      if (pos.length >= 2) return { line: pos, spot: null };
    }
    let best = 0;
    idx.forEach((src, k) => {
      if (Math.abs(times[src] - start) < Math.abs(times[idx[best]] - start)) best = k;
    });
    return { line: null, spot: positions[best] };
  }, [highlight, times, gpsPath.length, idx, positions]);

  const arrows = useMemo(() => {
    if (positions.length < 2) return [];
    const step = Math.max(1, Math.floor(positions.length / 8));
    const pts: { at: number; pos: [number, number]; rotation: number }[] = [];
    for (let i = step; i < positions.length - 1; i += step) {
      pts.push({ at: i, pos: positions[i], rotation: bearingDeg(positions[i - 1], positions[i]) });
    }
    return pts;
  }, [positions]);

  if (positions.length === 0) return null;

  return (
    <div className={className}>
      <MapContainer center={positions[0]} zoom={16} scrollWheelZoom={false} style={{ width: "100%", height: "100%" }}>
        <TileLayer attribution={TILE_ATTRIBUTION} url={TILE_URL} />
        <FitBounds positions={positions} />

        {runs ? (
          runs.map((r) => (
            <Polyline
              key={r.from}
              positions={r.pos}
              pathOptions={{ color: r.bin < 0 ? "rgb(115,120,128)" : rgbCss(rampColour((r.bin + 0.5) / BINS)), weight: 4 }}
            />
          ))
        ) : (
          <Polyline positions={positions} pathOptions={{ color: "var(--series-1)", weight: 4 }} />
        )}

        {marked?.line && <Polyline positions={marked.line} pathOptions={{ color: "var(--accent)", weight: 8, opacity: 0.55 }} />}
        {marked?.spot && <Marker position={marked.spot} icon={spotIcon} interactive={false} keyboard={false} />}

        {arrows.map((a) => (
          <Marker key={a.at} position={a.pos} icon={arrowIcon(a.rotation)} interactive={false} keyboard={false} />
        ))}
        <Marker position={positions[0]} icon={launchIcon} title={labels.launch} />
        <Marker position={positions[positions.length - 1]} icon={landIcon} title={labels.land} />
      </MapContainer>
    </div>
  );
}
