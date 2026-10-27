"use client";

import { useEffect, useState } from "react";
import { fmtDateTime, fmtUtc } from "@/lib/format";

// UTC on the server and in the first client render, local time added after mount:
// the server can't know the viewer's zone, and a mismatch would break hydration.
export function FlightTime({ iso }: { iso: string }) {
  const [local, setLocal] = useState<string | null>(null);
  useEffect(() => setLocal(fmtDateTime(new Date(iso))), [iso]);
  const utc = fmtUtc(new Date(iso));
  return (
    <time dateTime={iso}>
      {local ? <>{local} <span className="num">({utc})</span></> : <span className="num">{utc}</span>}
    </time>
  );
}
