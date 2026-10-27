"use client";

import { useMemo, useRef, type MutableRefObject } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Grid, Line, OrbitControls } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { useCssVars } from "@/lib/theme";
import {
  buildFlightPathScene, buildPathColors, sampleIndices, type PathColorMode, type ScenePoint,
} from "./flightPathGeometry";

export type { PathColorMode };

// set by CameraRig inside the Canvas, called by the toolbar outside it
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

  return <OrbitControls ref={controlsRef} minDistance={1.5} maxDistance={9} target={[0, 0.3, 0]} />;
}

export function FlightPathScene({
  gpsPath, className, cameraApiRef, colorMode = "standard", windSpeedPath, signalQualityPath,
}: FlightPathSceneProps) {
  const vars = useCssVars(["series-1", "accent", "text", "border", "text-subtle"]);

  const idx = useMemo(() => sampleIndices(gpsPath.length), [gpsPath]);
  const scene = useMemo(() => buildFlightPathScene(idx.map((i) => gpsPath[i])), [idx, gpsPath]);
  const vertexColors = useMemo(() => {
    const values = colorMode === "wind" ? windSpeedPath : signalQualityPath;
    return buildPathColors(colorMode, values ? idx.map((i) => values[i] ?? null) : null);
  }, [colorMode, windSpeedPath, signalQualityPath, idx]);
  const vertices = useMemo<[number, number, number][]>(
    () => (scene ? scene.points.map((p: ScenePoint) => [p.x, p.y, p.z]) : []),
    [scene]
  );

  // wait for the resolved theme colours; three can't read CSS variables
  if (!scene || vertices.length < 2 || !vars["series-1"]) return null;

  const start = scene.points[0];
  const end = scene.points[scene.points.length - 1];

  return (
    <div className={className}>
      <Canvas camera={{ position: DEFAULT_CAMERA, fov: 42 }} gl={{ antialias: true, alpha: true }} dpr={[1, 2]} frameloop="demand">
        <ambientLight intensity={0.8} />
        <directionalLight position={[3, 4, 2]} intensity={0.8} />

        <Grid
          position={[0, -0.01, 0]}
          args={[10, 10]}
          cellSize={0.4}
          cellColor={vars.border}
          sectionSize={2}
          sectionColor={vars["text-subtle"]}
          fadeDistance={12}
          infiniteGrid
        />

        {/* vertexColors needs a white base colour or drei tints them */}
        {vertexColors ? (
          <Line points={vertices} vertexColors={vertexColors} color="white" lineWidth={3} />
        ) : (
          <Line points={vertices} color={vars["series-1"]} lineWidth={2.5} />
        )}

        <mesh position={[start.x, start.y, start.z]}>
          <torusGeometry args={[0.05, 0.018, 8, 24]} />
          <meshBasicMaterial color={vars.accent} />
        </mesh>
        <mesh position={[end.x, end.y, end.z]}>
          <boxGeometry args={[0.07, 0.07, 0.07]} />
          <meshBasicMaterial color={vars.text} />
        </mesh>

        <CameraRig apiRef={cameraApiRef} />
      </Canvas>
    </div>
  );
}
