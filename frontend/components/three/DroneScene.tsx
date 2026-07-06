"use client";

import { Suspense, type MutableRefObject } from "react";
import { Canvas } from "@react-three/fiber";
import { ContactShadows } from "@react-three/drei";
import { DroneModel } from "./DroneModel";

interface DroneSceneProps {
  className?: string;
  /** See DroneModel — written externally by a GSAP ScrollTrigger, read each frame. */
  scrollProgress?: MutableRefObject<number>;
}

/**
 * Full <Canvas> scene hosting the procedural drone model — lighting and
 * camera tuned for a moody, professional "product shot" read rather than
 * flat cartoon lighting: a cool key light, a warm amber rim light echoing
 * the app's accent colour, and soft environment reflections on the
 * chassis's semi-metallic material.
 */
export function DroneScene({ className, scrollProgress }: DroneSceneProps) {
  return (
    <div className={className}>
      <Canvas
        shadows
        camera={{ position: [3.1, 2.0, 3.4], fov: 32 }}
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 2]}
      >
        {/*
          No <Environment> (drei's IBL presets fetch an HDRI from a CDN) —
          keeping this fully self-contained matches the rest of the app,
          which works entirely offline, and avoids a network-dependent
          Suspense boundary hiding the drone if that fetch stalls. A fuller
          fixed light rig stands in for image-based reflections instead.
        */}
        <ambientLight intensity={0.45} />
        <directionalLight
          position={[3, 4, 2]}
          intensity={1.3}
          color="#EAF0FF"
          castShadow
        />
        <directionalLight
          position={[-3, 1, -2]}
          intensity={0.8}
          color="#B89642"
        />
        <pointLight position={[0, 2, -3]} intensity={0.4} color="#3A9CF8" />
        <DroneModel position={[0, 0.1, 0]} scrollProgress={scrollProgress} />
        <Suspense fallback={null}>
          <ContactShadows
            position={[0, -0.55, 0]}
            opacity={0.45}
            scale={6}
            blur={2.2}
            far={2}
            color="#000814"
          />
        </Suspense>
      </Canvas>
    </div>
  );
}
