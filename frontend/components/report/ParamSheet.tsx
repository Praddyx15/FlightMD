"use client";

import { useState } from "react";
import type { ParamRecommendation } from "@/lib/types";
import { copyToClipboard } from "@/lib/utils";

export function ParamSheet({ params }: { params: ParamRecommendation[] }) {
  const [copied, setCopied] = useState<string | null>(null);

  async function handleCopy(param: ParamRecommendation) {
    await copyToClipboard(`${param.param_name}=${param.suggested_value}`);
    setCopied(param.param_name);
    setTimeout(() => setCopied(null), 1500);
  }

  async function handleCopyAll() {
    const text = params
      .map((p) => `${p.param_name}=${p.suggested_value}`)
      .join("\n");
    await copyToClipboard(text);
    setCopied("__all__");
    setTimeout(() => setCopied(null), 1500);
  }

  return (
    <section>
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-lg font-bold text-white/80">
          Parameter Changes <span className="text-white/30 font-normal">({params.length})</span>
        </h2>
        <button
          onClick={handleCopyAll}
          className="ml-auto text-xs px-3 py-1.5 rounded-lg transition-all"
          style={{
            background: copied === "__all__" ? "rgba(13,217,124,0.15)" : "var(--bg-elevated)",
            color: copied === "__all__" ? "#0DD97C" : "var(--accent)",
            border: "1px solid",
            borderColor: copied === "__all__" ? "#0DD97C55" : "var(--accent)",
          }}
        >
          {copied === "__all__" ? "✓ Copied!" : "Copy All (.param format)"}
        </button>
      </div>

      <div
        className="rounded-2xl border border-border overflow-hidden bg-card/85 backdrop-blur-md shadow-lg"
      >
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-elevated border-b border-border">
              <th className="text-left px-4 py-3 text-white/40 font-medium text-xs uppercase tracking-wider">
                Parameter
              </th>
              <th className="text-right px-4 py-3 text-white/40 font-medium text-xs uppercase tracking-wider">
                Current
              </th>
              <th className="text-right px-4 py-3 text-white/40 font-medium text-xs uppercase tracking-wider">
                Suggested
              </th>
              <th className="text-right px-4 py-3 text-white/40 font-medium text-xs uppercase tracking-wider hidden sm:table-cell">
                Direction
              </th>
              <th className="text-left px-4 py-3 text-white/40 font-medium text-xs uppercase tracking-wider hidden md:table-cell">
                Reason
              </th>
              <th className="px-4 py-3 w-20" />
            </tr>
          </thead>
          <tbody>
            {params.map((p, i) => (
              <tr
                key={p.param_name}
                style={{
                  borderBottom: i < params.length - 1 ? "1px solid var(--border)" : "none",
                  background: i % 2 === 1 ? "rgba(255,255,255,0.015)" : "transparent",
                }}
              >
                <td className="px-4 py-3">
                  <span className="mono font-bold text-white/80 text-xs">{p.param_name}</span>
                </td>
                <td className="px-4 py-3 text-right mono text-white/40 text-xs">
                  {p.current_value}
                  {p.unit ? ` ${p.unit}` : ""}
                </td>
                <td className="px-4 py-3 text-right">
                  <span className="mono font-bold text-xs" style={{ color: "var(--accent)" }}>
                    {p.suggested_value}
                    {p.unit ? ` ${p.unit}` : ""}
                  </span>
                </td>
                <td className="px-4 py-3 text-right text-white/35 text-xs capitalize hidden sm:table-cell">
                  {p.change_direction}
                </td>
                <td className="px-4 py-3 text-white/40 text-xs leading-relaxed hidden md:table-cell">
                  {p.reason}
                </td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => handleCopy(p)}
                    className="text-xs px-2 py-1 rounded transition-all"
                    style={{
                      background: copied === p.param_name ? "#0DD97C22" : "#1A2540",
                      color: copied === p.param_name ? "#0DD97C" : "rgba(255,255,255,0.4)",
                      border: "1px solid rgba(255,255,255,0.1)",
                    }}
                  >
                    {copied === p.param_name ? "✓" : "Copy"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-white/25 mt-2">
        Copy All generates Mission Planner / QGroundControl compatible PARAM_NAME=VALUE format.
      </p>
    </section>
  );
}
