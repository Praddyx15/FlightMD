"use client";

import { useState } from "react";
import { Check, Copy, Download } from "lucide-react";
import type { ParamRecommendation } from "@/lib/types";
import { fmtParam } from "@/lib/format";
import { FORMAT_FILE, paramFile, paramLine, type ParamFormat } from "@/lib/paramFile";
import { cn, copyToClipboard } from "@/lib/utils";

interface Props {
  params: ParamRecommendation[];
  defaultFormat?: ParamFormat;
  autopilotGuess?: string | null;
}

export function ParamSheet({ params, defaultFormat = "missionplanner", autopilotGuess }: Props) {
  const [format, setFormat] = useState<ParamFormat>(defaultFormat);
  const [copied, setCopied] = useState<string | null>(null);

  async function copy(key: string, text: string) {
    try {
      await copyToClipboard(text);
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      setCopied(null);
    }
  }

  function download() {
    const blob = new Blob([paramFile(params, format)], { type: "text/plain" });
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = FORMAT_FILE[format].name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
  }

  return (
    <section id="params" aria-labelledby="params-h" className="scroll-mt-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="params-h" className="text-base font-semibold">
          Parameter changes <span className="num font-normal text-fg-muted">({params.length})</span>
        </h2>
        <div className="no-print ml-auto flex flex-wrap items-center gap-2">
          <div role="group" aria-label="File format" className="flex rounded border p-0.5">
            {(Object.keys(FORMAT_FILE) as ParamFormat[]).map((f) => (
              <button
                key={f}
                type="button"
                aria-pressed={format === f}
                onClick={() => setFormat(f)}
                className={cn(
                  "min-h-[28px] rounded-sm px-2 text-xs pointer-coarse:min-h-[44px]",
                  format === f ? "bg-accent-solid text-on-accent" : "text-fg-muted hover:text-fg"
                )}
              >
                {f === "qgc" ? "QGroundControl" : "Mission Planner"}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => copy("__all__", paramFile(params, format))} className="btn text-xs">
            {copied === "__all__" ? <Check aria-hidden className="h-4 w-4 text-ok" /> : <Copy aria-hidden className="h-4 w-4" />}
            {copied === "__all__" ? "Copied" : "Copy all"}
          </button>
          <button type="button" onClick={download} className="btn text-xs">
            <Download aria-hidden className="h-4 w-4" />
            {FORMAT_FILE[format].name}
          </button>
        </div>
      </div>

      <div className="panel overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-elevated text-left">
              <th scope="col" className="label px-3 py-2">Parameter</th>
              <th scope="col" className="label px-3 py-2 text-right">Current</th>
              <th scope="col" className="label px-3 py-2 text-right">Suggested</th>
              <th scope="col" className="label hidden px-3 py-2 md:table-cell">Reason</th>
              <th scope="col" className="no-print px-3 py-2"><span className="sr-only">Copy</span></th>
            </tr>
          </thead>
          <tbody>
            {params.map((p) => (
              <tr key={p.param_name} className="border-b last:border-b-0 align-top">
                <td className="px-3 py-2">
                  <span className="num font-semibold">{p.param_name}</span>
                  {/* reason moves under the name on narrow screens instead of disappearing */}
                  <p className="mt-0.5 text-xs text-fg-muted md:hidden">{p.reason}</p>
                </td>
                <td className="num px-3 py-2 text-right text-fg-muted">
                  {fmtParam(p.current_value)}
                  {p.unit ? ` ${p.unit}` : ""}
                </td>
                <td className="num px-3 py-2 text-right font-semibold text-accent-text">
                  {fmtParam(p.suggested_value)}
                  {p.unit ? ` ${p.unit}` : ""}
                  <span className="sr-only"> ({p.change_direction})</span>
                </td>
                <td className="hidden px-3 py-2 text-xs text-fg-muted md:table-cell">{p.reason}</td>
                <td className="no-print px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => copy(p.param_name, paramLine(p, format))}
                    className="btn px-2 text-xs"
                    aria-label={`Copy ${p.param_name}`}
                  >
                    {copied === p.param_name ? <Check aria-hidden className="h-4 w-4 text-ok" /> : <Copy aria-hidden className="h-4 w-4" />}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-fg-muted">
        {format === "qgc"
          ? "QGroundControl: Parameters → Tools → Load from file. Whole-number values are written as INT32, the rest as REAL32; QGC skips a row whose type doesn't match the vehicle."
          : "Mission Planner: Config → Full Parameter List → Load from file, then Write Params."}
        {autopilotGuess ? ` Format picked for ${autopilotGuess}.` : ""}
      </p>
    </section>
  );
}
