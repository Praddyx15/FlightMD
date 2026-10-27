"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowLeftRight, Clock, TrendingUp, X } from "lucide-react";
import { clearRecentReports, getRecentReports, removeRecentReport, type RecentReport } from "@/lib/storage";
import { fmtDate, fmtScore, parseIsoDate } from "@/lib/format";
import { TONE_CLASSES, gradeTone } from "@/lib/utils";

const HOUR = 3600_000;

function when(r: RecentReport): number {
  return parseIsoDate(r.flightStart)?.getTime() ?? r.uploadedAt;
}

export function RecentReports() {
  const router = useRouter();
  const [items, setItems] = useState<RecentReport[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    setItems(getRecentReports());
  }, []);

  function toggle(id: string) {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      return prev.length >= 2 ? [prev[1], id] : [...prev, id];
    });
  }

  function remove(id: string) {
    removeRecentReport(id);
    setItems(getRecentReports());
    setSelected((prev) => prev.filter((x) => x !== id));
  }

  function compare() {
    if (!items) return;
    // older flight first, whatever order they were ticked in
    const [a, b] = selected
      .map((id) => items.find((r) => r.id === id)!)
      .sort((x, y) => when(x) - when(y));
    router.push(`/compare?a=${encodeURIComponent(a.id)}&b=${encodeURIComponent(b.id)}`);
  }

  if (items === null) return null;

  return (
    <section aria-labelledby="recent-h" className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="recent-h" className="text-base font-semibold">Recent on this device</h2>
        <div className="ml-auto flex gap-2">
          {selected.length === 2 && (
            <button type="button" onClick={compare} className="btn-primary">
              <ArrowLeftRight aria-hidden className="h-4 w-4" />
              Compare selected
            </button>
          )}
          {items.length > 0 && (
            <button
              type="button"
              className="btn"
              onClick={() => {
                clearRecentReports();
                setItems([]);
                setSelected([]);
              }}
            >
              Clear list
            </button>
          )}
        </div>
      </div>

      {items.length === 0 ? (
        <p className="panel px-4 py-6 text-sm text-fg-muted">
          Logs you analyse in this browser are listed here. Nothing is shared with other visitors.
        </p>
      ) : (
        <ul className="panel divide-y">
          {items.map((r) => {
            const stale = !r.airframeLabel && Date.now() - r.uploadedAt > HOUR;
            const flight = parseIsoDate(r.flightStart);
            return (
              <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 sm:flex-nowrap">
                <input
                  type="checkbox"
                  id={`cmp-${r.id}`}
                  checked={selected.includes(r.id)}
                  onChange={() => toggle(r.id)}
                  className="h-4 w-4 shrink-0 accent-[var(--accent)] pointer-coarse:h-6 pointer-coarse:w-6"
                />
                <label htmlFor={`cmp-${r.id}`} className="sr-only">Select {r.fileName} to compare</label>

                <div className="min-w-0 flex-1">
                  <Link href={`/report/${encodeURIComponent(r.id)}`} className="block truncate font-medium text-fg hover:underline">
                    {r.fileName}
                  </Link>
                  <div className="flex flex-wrap items-center gap-x-3 text-xs text-fg-muted">
                    <span>{flight ? `Flown ${fmtDate(flight)}` : `Uploaded ${fmtDate(new Date(r.uploadedAt))}`}</span>
                    {r.vehicle && <span>{r.vehicle}</span>}
                    {stale && (
                      <span className="flex items-center gap-1">
                        <Clock aria-hidden className="h-3.5 w-3.5" /> probably expired
                      </span>
                    )}
                    {r.airframeLabel && (
                      <Link href={`/airframe/${encodeURIComponent(r.airframeLabel)}`} className="flex items-center gap-1">
                        <TrendingUp aria-hidden className="h-3.5 w-3.5" />
                        {r.airframeLabel}
                      </Link>
                    )}
                  </div>
                </div>

                {r.grade === "-" ? (
                  <span className="shrink-0 rounded-sm border px-1.5 py-px text-xs text-fg-muted">Not assessed</span>
                ) : r.grade && r.score != null ? (
                  <span className={`num shrink-0 rounded-sm border px-1.5 py-px text-xs font-semibold ${TONE_CLASSES[gradeTone(r.grade)]}`}>
                    {r.grade} · {fmtScore(r.score)}
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={() => remove(r.id)}
                  className="btn shrink-0 border-transparent bg-transparent px-2 text-fg-muted"
                  aria-label={`Remove ${r.fileName} from this list`}
                >
                  <X aria-hidden className="h-4 w-4" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
