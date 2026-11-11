import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { useTranslations } from "next-intl";
import { DASH, fmtNum } from "@/lib/format";

// Score change between two flights; higher is better for every score.
export function DeltaBadge({ delta }: { delta: number | null }) {
  const t = useTranslations("delta");
  if (delta === null) return <span className="text-xs text-fg-muted">{DASH}</span>;
  if (Math.abs(delta) < 0.5) {
    return (
      <span className="num inline-flex items-center gap-1 text-xs text-fg-muted">
        <Minus aria-hidden className="h-3 w-3" /> {t("none")}
      </span>
    );
  }
  const better = delta > 0;
  const Icon = better ? ArrowUp : ArrowDown;
  const n = fmtNum(Math.abs(delta), 0);
  return (
    <span className={`num inline-flex items-center gap-1 text-xs font-semibold ${better ? "text-ok" : "text-caution"}`}>
      <Icon aria-hidden className="h-3 w-3" />
      {better ? t("better", { n }) : t("worse", { n })}
    </span>
  );
}
