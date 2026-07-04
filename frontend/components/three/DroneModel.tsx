"use client";

import { useRef, type MutableRefObject } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import * as THREE from "three";

/**
 * Procedurally-built quadcopter — no external model file. Built entirely
 * from primitive geometry, styled to match the app's instrument-panel
 * identity: matte carbon-dark chassis, amber accent rings (echoing the
 * severity/score palette used everywhere else), restrained proportions.
 * Deliberately avoids rounded "toy" shapes and bright flat colours — the
 * chamfered edges and low-roughness material read as machined hardware,
 * not a cartoon mascot.
 */

const CHASSIS_COLOUR = "#141C35";
const ARM_COLOUR = "#0E1428";
const ACCENT_COLOUR = "#E8A020";
const PROP_COLOUR = "#3A4560";

const ARM_ANGLES = [45, 135, 225, 315]; // degrees — X configuration
const ARM_LENGTH = 1.55;

function Arm({ angleDeg }: { angleDeg: number }) {
  const rad = (angleDeg * Math.PI) / 180;
  const x = Math.cos(rad) * ARM_LENGTH;
  const z = Math.sin(rad) * ARM_LENGTH;
  const midX = x / 2;
  const midZ = z / 2;

  return (
    <group>
      {/* Arm boom */}
      <group position={[midX, 0, midZ]} rotation={[0, -rad, 0]}>
        <RoundedBox args={[ARM_LENGTH, 0.09, 0.16]} radius={0.035} smoothness={4}>
          <meshStandardMaterial color={ARM_COLOUR} roughness={0.55} metalness={0.35} />
        </RoundedBox>
      </group>

      {/* Motor nacelle */}
      <group position={[x, 0.02, z]}>
        <mesh castShadow>
          <cylinderGeometry args={[0.16, 0.19, 0.16, 24]} />
          <meshStandardMaterial color={CHASSIS_COLOUR} roughness={0.45} metalness={0.4} />
        </mesh>
        {/* Accent ring — instrument-panel amber, subtle emissive glow */}
        <mesh position={[0, 0.09, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.15, 0.012, 12, 32]} />
          <meshStandardMaterial
            color={ACCENT_COLOUR}
            emissive={ACCENT_COLOUR}
            emissiveIntensity={0.55}
            roughness={0.3}
            metalness={0.2}
          />
        </mesh>
        {/* Propeller hub */}
        <mesh position={[0, 0.13, 0]}>
          <cylinderGeometry args={[0.03, 0.03, 0.06, 12]} />
          <meshStandardMaterial color="#080D1A" roughness={0.4} metalness={0.6} />
        </mesh>
        {/* Propeller — abstracted as a thin translucent disc suggesting a spin blur,
            not literal blade geometry (reads as "product visualization", not a toy). */}
        <mesh position={[0, 0.14, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.62, 0.62, 0.012, 32]} />
          <meshStandardMaterial
            color={PROP_COLOUR}
            transparent
            opacity={0.16}
            roughness={0.6}
            metalness={0.1}
            side={THREE.DoubleSide}
          />
        </mesh>
      </group>
    </group>
  );
}

function Leg({ angleDeg }: { angleDeg: number }) {
  const rad = (angleDeg * Math.PI) / 180;
  const x = Math.cos(rad) * 0.5;
  const z = Math.sin(rad) * 0.5;

  return (
    <group position={[x, -0.22, z]} rotation={[0.35, -rad, 0]}>
      <mesh>
        <cylinderGeometry args={[0.018, 0.018, 0.5, 8]} />
        <meshStandardMaterial color={ARM_COLOUR} roughness={0.6} metalness={0.3} />
      </mesh>
    </group>
  );
}

type DroneModelProps = JSX.IntrinsicElements["group"] & {
  /**
   * Shared mutable ref in [0, 1], written by a GSAP ScrollTrigger elsewhere
   * (see DroneScene) and read here each frame. Keeping scroll control as a
   * plain ref read inside useFrame — rather than forwarding a Three.js ref
   * out through the Canvas boundary for GSAP to tween directly — avoids
   * fighting the component's own idle-rotation animation for ownership of
   * the same object, and is the idiomatic react-three-fiber pattern for
   * letting DOM-driven state affect a scene.
   */
  scrollProgress?: MutableRefObject<number>;
};

export function DroneModel({ scrollProgress, ...props }: DroneModelProps) {
  const groupRef = useRef<THREE.Group>(null);

  // Slow continuous idle rotation, blended with an extra scroll-driven turn
  // and a gentle tilt so the drone feels inspected as you scroll past it.
  useFrame((_, delta) => {
    if (!groupRef.current) return;
    const progress = scrollProgress?.current ?? 0;
    groupRef.current.rotation.y += delta * 0.12;
    groupRef.current.rotation.x = THREE.MathUtils.lerp(
      groupRef.current.rotation.x,
      progress * 0.35,
      0.06
    );
    groupRef.current.position.y = THREE.MathUtils.lerp(
      groupRef.current.position.y,
      0.1 - progress * 0.25,
      0.06
    );
  });

  return (
    <group ref={groupRef} {...props}>
      {/* Central chassis */}
      <RoundedBox args={[0.85, 0.22, 0.85]} radius={0.09} smoothness={4} castShadow>
        <meshStandardMaterial color={CHASSIS_COLOUR} roughness={0.4} metalness={0.45} />
      </RoundedBox>

      {/* Top plate accent line */}
      <mesh position={[0, 0.115, 0]}>
        <boxGeometry args={[0.5, 0.006, 0.06]} />
        <meshStandardMaterial
          color={ACCENT_COLOUR}
          emissive={ACCENT_COLOUR}
          emissiveIntensity={0.6}
          roughness={0.3}
        />
      </mesh>

      {/* Camera gimbal, slung beneath the front of the body */}
      <group position={[0, -0.22, 0.32]}>
        <mesh>
          <cylinderGeometry args={[0.05, 0.05, 0.14, 12]} />
          <meshStandardMaterial color="#080D1A" roughness={0.35} metalness={0.5} />
        </mesh>
        <mesh position={[0, -0.09, 0.02]}>
          <sphereGeometry args={[0.075, 20, 16]} />
          <meshStandardMaterial color={CHASSIS_COLOUR} roughness={0.25} metalness={0.6} />
        </mesh>
        <mesh position={[0, -0.09, 0.09]}>
          <sphereGeometry args={[0.028, 12, 12]} />
          <meshStandardMaterial
            color="#3A9CF8"
            emissive="#3A9CF8"
            emissiveIntensity={0.5}
            roughness={0.2}
          />
        </mesh>
      </group>

      {/* Arms + motors + props */}
      {ARM_ANGLES.map((angle) => (
        <Arm key={angle} angleDeg={angle} />
      ))}

      {/* Landing legs */}
      {ARM_ANGLES.map((angle) => (
        <Leg key={`leg-${angle}`} angleDeg={angle} />
      ))}
    </group>
  );
}
