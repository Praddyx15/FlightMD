import {
  Activity, BatteryCharging, Compass, Cpu, Fan, Plug, Rocket, Satellite, SlidersHorizontal, Vibrate,
  type LucideIcon,
} from "lucide-react";
import type { Category } from "@/lib/types";

const ICONS: Record<Category, LucideIcon> = {
  oscillation:    Activity,
  vibration:      Vibrate,
  ekf:            Compass,
  battery:        BatteryCharging,
  gps:            Satellite,
  parameters:     SlidersHorizontal,
  motors:         Fan,
  ascent_profile: Rocket,
  power:          Plug,
  system:         Cpu,
};

export function CategoryIcon({ category, className = "h-4 w-4" }: { category: Category; className?: string }) {
  const Icon = ICONS[category] ?? Cpu;
  return <Icon aria-hidden className={`shrink-0 text-fg-muted ${className}`} />;
}
