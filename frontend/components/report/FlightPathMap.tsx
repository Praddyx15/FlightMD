"use client";

import { useEffect, useMemo, useRef } from "react";
import { MapContainer, TileLayer, Polyline, Marker, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { buildPathColors, type PathColorMode } from "@/components/three/flightPathGeometry";

interface Props {
  gpsPath: [number, number, number][];
  colorMode: PathColorMode;
  windSpeedPath?: (number | null)[] | null;
  signalQualityPath?: (number | null)[] | null;
  className?: string;
}

function rgbCss([r, g, b]: [number, number, number]): string {
  return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
}

function bearingDeg(a: [number, number], b: [number, number]): number {
  const lat1 = (a[0] * Math.PI) / 180;
  const lat2 = (b[0] * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180;
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x = Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  return (Math.atan2(y, x) * 180) / Math.PI;
}

function dotIcon(colour: string, size = 14) {
  return L.divIcon({
    className: "",
    html: `<div style="width:${size}px;height:${size}px;border-radius:9999px;background:${colour};border:2px solid #0A0A0A;box-shadow:0 0 6px ${colour}99;"></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function arrowIcon(rotationDeg: number, colour: string) {
  return L.divIcon({
    className: "",
    html: `<div style="transform:rotate(${rotationDeg}deg);width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:10px solid ${colour};filter:drop-shadow(0 0 2px #0A0A0A);"></div>`,
    iconSize: [10, 10],
    iconAnchor: [5, 5],
  });
}

function FitBounds({ positions }: { positions: [number, number][] }) {
  const map = useMap();
  useEffect(() => {
    if (positions.length === 0) return;
    const bounds = L.latLngBounds(positions);
    map.fitBounds(bounds, { padding: [30, 30] });
  }, [positions, map]);
  return null;
}

export function FlightPathMap({
  gpsPath, colorMode, windSpeedPath, signalQualityPath, className,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  const positions = useMemo<[number, number][]>(
    () => gpsPath.map(([lat, lon]) => [lat, lon]),
    [gpsPath]
  );

  const colours = useMemo(() => {
    const values = colorMode === "wind" ? windSpeedPath : colorMode === "signal" ? signalQualityPath : null;
    return buildPathColors(colorMode, values);
  }, [colorMode, windSpeedPath, signalQualityPath]);

  // Direction-of-flight arrows at ~10 evenly spaced points along the path.
  const arrowPoints = useMemo(() => {
    if (positions.length < 2) return [];
    const step = Math.max(1, Math.floor(positions.length / 10));
    const pts: { pos: [number, number]; rotation: number }[] = [];
    for (let i = step; i < positions.length - 1; i += step) {
      pts.push({ pos: positions[i], rotation: bearingDeg(positions[i - 1], positions[i]) });
    }
    return pts;
  }, [positions]);

  if (positions.length === 0) return null;

  const segments: { pos: [number, number][]; colour: string }[] = [];
  if (colours) {
    for (let i = 0; i < positions.length - 1; i++) {
      segments.push({ pos: [positions[i], positions[i + 1]], colour: rgbCss(colours[i]) });
    }
  }

  return (
    <div ref={containerRef} className={className}>
      <MapContainer
        center={positions[0]}
        zoom={16}
        scrollWheelZoom={true}
        style={{ width: "100%", height: "100%", background: "#0A0A0A" }}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitBounds positions={positions} />

        {colours ? (
          segments.map((seg, i) => (
            <Polyline key={i} positions={seg.pos} pathOptions={{ color: seg.colour, weight: 4 }} />
          ))
        ) : (
          <Polyline positions={positions} pathOptions={{ color: "#B89642", weight: 4 }} />
        )}

        {arrowPoints.map((a, i) => (
          <Marker key={i} position={a.pos} icon={arrowIcon(a.rotation, "#E7C25B")} interactive={false} />
        ))}

        <Marker position={positions[0]} icon={dotIcon("#0DD97C")} />
        <Marker position={positions[positions.length - 1]} icon={dotIcon("#f43f5e")} />
      </MapContainer>
    </div>
  );
}
