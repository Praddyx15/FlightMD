"use client";

import { Ruler } from "lucide-react";
import { useTranslations } from "next-intl";
import { UNIT_SYSTEMS, isUnitSystem } from "@/lib/format";
import { setUnits, useUnits } from "@/lib/units";

export function UnitsToggle() {
  const t = useTranslations("units");
  const units = useUnits();
  return (
    <label className="flex items-center gap-1 text-fg-muted">
      <Ruler aria-hidden className="h-4 w-4" />
      <span className="sr-only">{t("label")}</span>
      <select
        value={units}
        onChange={(e) => {
          if (isUnitSystem(e.target.value)) setUnits(e.target.value);
        }}
        className="input border-transparent bg-transparent px-1 text-xs"
        title={t("label")}
      >
        {UNIT_SYSTEMS.map((u) => (
          <option key={u} value={u}>{t(u)}</option>
        ))}
      </select>
    </label>
  );
}
