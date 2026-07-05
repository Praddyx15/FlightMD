import type { Category } from "@/lib/types";

const ICONS: Record<Category, string> = {
  oscillation:    "〰️",
  vibration:      "📳",
  ekf:            "🔭",
  battery:        "🔋",
  gps:            "📡",
  parameters:     "⚙️",
  motors:         "🔄",
  ascent_profile: "🚀",
  system:         "💻",
};

export function CategoryIcon({ category }: { category: Category }) {
  return <span title={category}>{ICONS[category] ?? "🔍"}</span>;
}
