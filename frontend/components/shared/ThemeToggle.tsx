"use client";

import { Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { setTheme, useTheme } from "@/lib/theme";

export function ThemeToggle() {
  const t = useTranslations("theme");
  const theme = useTheme();
  const next = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      onClick={() => setTheme(next)}
      className="btn border-transparent bg-transparent px-2"
      aria-label={next === "light" ? t("toLight") : t("toDark")}
      title={next === "light" ? t("lightTitle") : t("darkTitle")}
    >
      {theme === "dark" ? <Sun aria-hidden className="h-4 w-4" /> : <Moon aria-hidden className="h-4 w-4" />}
    </button>
  );
}
