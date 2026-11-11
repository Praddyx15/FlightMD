"use client";

import { useEffect, useState } from "react";
import { THEME_EVENT, THEME_KEY } from "./themeScript";

export type Theme = "dark" | "light";

export function currentTheme(): Theme {
  return document.documentElement.classList.contains("light") ? "light" : "dark";
}

export function setTheme(t: Theme) {
  document.documentElement.classList.toggle("light", t === "light");
  try {
    localStorage.setItem(THEME_KEY, t);
  } catch {
    // private mode: the choice just won't stick
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

export function useTheme(): Theme {
  const [theme, set] = useState<Theme>("dark");
  useEffect(() => {
    const sync = () => set(currentTheme());
    sync();
    window.addEventListener(THEME_EVENT, sync);
    return () => window.removeEventListener(THEME_EVENT, sync);
  }, []);
  return theme;
}

// Canvas/WebGL can't read var(--x); resolve the hex when the theme changes.
export function useCssVars(names: string[]): Record<string, string> {
  const theme = useTheme();
  const [vals, setVals] = useState<Record<string, string>>({});
  const joined = names.join(",");
  useEffect(() => {
    const cs = getComputedStyle(document.documentElement);
    const out: Record<string, string> = {};
    for (const n of joined.split(",")) out[n] = cs.getPropertyValue(`--${n}`).trim();
    setVals(out);
  }, [theme, joined]);
  return vals;
}
