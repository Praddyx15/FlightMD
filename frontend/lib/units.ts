"use client";

import { useEffect, useState } from "react";
import { isUnitSystem, type UnitSystem } from "./format";
import { getUnitSystem, setUnitSystem } from "./storage";

const UNITS_EVENT = "flightmd-units";

export function setUnits(sys: UnitSystem) {
  setUnitSystem(sys);
  window.dispatchEvent(new Event(UNITS_EVENT));
}

// Starts as metric on the server and the first client render, then switches to the
// stored choice, so hydration never sees two different numbers.
export function useUnits(): UnitSystem {
  const [sys, set] = useState<UnitSystem>("metric");
  useEffect(() => {
    const sync = () => {
      const stored = getUnitSystem();
      set(isUnitSystem(stored) ? stored : "metric");
    };
    sync();
    window.addEventListener(UNITS_EVENT, sync);
    return () => window.removeEventListener(UNITS_EVENT, sync);
  }, []);
  return sys;
}
