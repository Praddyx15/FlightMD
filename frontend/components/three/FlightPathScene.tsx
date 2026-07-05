"use client";

import { useRef, useMemo, type MutableRefObject } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Line, OrbitControls, Grid } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import {
  buildFlightPathScene, buildPathColors, type PathColorMode, type ScenePoint,
} from "./flightPathGeometry";

export type { PathColorMode };

/** Imperative camera presets — set by CameraRig (inside the Canvas), called
 * by the parent's toolbar buttons (outside the Canvas). */
export interface FlightPathCameraHandle {
  reset: () => void;
  top: () => void;
}

interface FlightPathSceneProps {
  gpsPath: [number, number, number][];
  className?: string;
  cameraApiRef?: MutableRefObject<FlightPathCameraHandle | null>;
  colorMode?: PathColorMode;
  windSpeedPath?: (number | null)[] | null;
  signalQualityPath?: (number | null)[] | null;
}

const DEFAULT_CAMERA: [number, number, number] = [3.4, 2.6, 3.4];
const TOP_CAMERA: [number, number, number] = [0.01, 5.5, 0.01];

function PathLine({ points, vertexColors }: { points: ScenePoint[]; vertexColors: [number, number, number][] | null }) {
  const vertices = useMemo<[number, number, number][]>(
    () => points.map((p) => [p.x, p.y, p.z]),
    [points]
  );
  // vertexColors requires the base `color` to be white so the per-vertex
  // values aren't tinted — see drei's Line implementation.
  return vertexColors ? (
    <Line points={vertices} vertexColors={vertexColors} color="white" lineWidth={3} />
  ) : (
    <Line points={vertices} color="#E8A020" lineWidth={2.5} />
  );
}

function Marker({ point, color }: { point: ScenePoint; color: string }) {
  return (
    <mesh position={[point.x, point.y, point.z]}>
      <sphereGeometry args={[0.05, 16, 16]} />
      <meshStandardMaterial
        color={color}
        emissive={color}
        emissiveIntensity={0.5}
        roughness={0.4}
      />
    </mesh>
  );
}

function CameraRig({ apiRef }: { apiRef?: MutableRefObject<FlightPathCameraHandle | null> }) {
  const { camera } = useThree();
  const controlsRef = useRef<OrbitControlsImpl>(null);

  if (apiRef) {
    apiRef.current = {
      reset: () => {
        camera.position.set(...DEFAULT_CAMERA);
        controlsRef.current?.target.set(0, 0.3, 0);
        controlsRef.current?.update();
      },
      top: () => {
        camera.position.set(...TOP_CAMERA);
        controlsRef.current?.target.set(0, 0, 0);
        controlsRef.current?.update();
      },
    };
  }

  return (
    <OrbitControls
      ref={controlsRef}
      enableDamping
      dampingFactor={0.08}
      minDistance={1.5}
      maxDistance={9}
      target={[0, 0.3, 0]}
    />
  );
}

export function FlightPathScene({
  gpsPath, className, cameraApiRef, colorMode = "standard", windSpeedPath, signalQualityPath,
}: FlightPathSceneProps) {
  const scene = useMemo(() => buildFlightPathScene(gpsPath), [gpsPath]);
  const vertexColors = useMemo(
    () => buildPathColors(colorMode, colorMode === "wind" ? windSpeedPath : signalQualityPath),
    [colorMode, windSpeedPath, signalQualityPath]
  );

  if (!scene || scene.points.length === 0) return null;

  const start = scene.points[0];
  const end = scene.points[scene.points.length - 1];

  return (
    <div className={className}>
      <Canvas
        camera={{ position: DEFAULT_CAMERA, fov: 42 }}
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 2]}
      >
        <ambientLight intensity={0.55} />
        <directionalLight position={[3, 4, 2]} intensity={1.0} color="#EAF0FF" />
        <directionalLight position={[-3, 1, -2]} intensity={0.5} color="#E8A020" />

        <Grid
          position={[0, -0.01, 0]}
          args={[10, 10]}
          cellSize={0.4}
          cellColor="#1e293b"
          sectionSize={2}
          sectionColor="#334155"
          fadeDistance={12}
          fadeStrength={1.5}
          infiniteGrid
        />

        <PathLine points={scene.points} vertexColors={vertexColors} />
        <Marker point={start} color="#0DD97C" />
        <Marker point={end} color="#f43f5e" />

        <CameraRig apiRef={cameraApiRef} />
      </Canvas>
    </div>
  );
}
