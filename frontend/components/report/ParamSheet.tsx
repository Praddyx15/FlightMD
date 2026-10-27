"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, ListChecks, Copy, Download } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ParamRecommendation } from "@/lib/types";
import { fmtParam } from "@/lib/format";
import { FORMAT_FILE, paramFile, paramLine, type ParamFormat } from "@/lib/paramFile";
import { AirframeAuthError, recordAppliedChanges } from "@/lib/api";
import { useErrorText } from "@/lib/errors";
import { getRecentReports } from "@/lib/storage";
import { cn, copyToClipboard } from "@/lib/utils";

interface Props {
  reportId: string;
  params: ParamRecommendation[];
  defaultFormat?: ParamFormat;
  autopilotGuess?: string | null;
}

type Applied =
  | { phase: "idle" }
  | { phase: "saving" }
  | { phase: "saved"; label: string; count: number }
  | { phase: "error"; message: string; locked?: string };

export function ParamSheet({ reportId, params, defaultFormat = "missionplanner", autopilotGuess }: Props) {
  const t = useTranslations("params");
  const errText = useErrorText();
  const [format, setFormat] = useState<ParamFormat>(defaultFormat);
  const [copied, setCopied] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [applied, setApplied] = useState<Applied>({ phase: "idle" });

  // the report itself doesnt carry its airframe label; this browser knows it if it did the upload
  useEffect(() => {
    const known = getRecentReports().find((r) => r.id === reportId)?.airframeLabel;
    if (known) setLabel(known);
  }, [reportId]);

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

  function toggle(name: string) {
    setSelected((prev) => (prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name]));
    setApplied({ phase: "idle" });
  }

  async function markApplied() {
    const af = label.trim();
    if (!af || selected.length === 0) return;
    setApplied({ phase: "saving" });
    try {
      await recordAppliedChanges(af, {
        report_id: reportId,
        applied_by: "user",
        changes: params
          .filter((p) => selected.includes(p.param_name))
          .map((p) => ({ name: p.param_name, from_value: p.current_value, to_value: p.suggested_value })),
      });
      setApplied({ phase: "saved", label: af, count: selected.length });
      setSelected([]);
    } catch (e) {
      setApplied({ phase: "error", message: errText(e, "changesSave"), locked: e instanceof AirframeAuthError ? af : undefined });
    }
  }

  const allSelected = selected.length === params.length;

  return (
    <section id="params" aria-labelledby="params-h" className="scroll-mt-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="params-h" className="text-base font-semibold">
          {t("title")} <span className="num font-normal text-fg-muted">({params.length})</span>
        </h2>
        <div className="no-print ml-auto flex flex-wrap items-center gap-2">
          <div role="group" aria-label={t("format")} className="flex rounded border p-0.5">
            {(Object.keys(FORMAT_FILE) as ParamFormat[]).map((f) => (
              <button
                key={f}
                type="button"
                aria-pressed={format === f}
                onClick={() => setFormat(f)}
                className={cn(
                  "min-h-7 rounded-sm px-2 text-xs pointer-coarse:min-h-11",
                  format === f ? "bg-accent-solid text-on-accent" : "text-fg-muted hover:text-fg"
                )}
              >
                {t(`formats.${f}`)}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => copy("__all__", paramFile(params, format))} className="btn text-xs">
            {copied === "__all__" ? <Check aria-hidden className="h-4 w-4 text-ok" /> : <Copy aria-hidden className="h-4 w-4" />}
            {copied === "__all__" ? t("copied") : t("copyAll")}
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
              <th scope="col" className="no-print w-8 px-3 py-2">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => setSelected(allSelected ? [] : params.map((p) => p.param_name))}
                  aria-label={t("selectAll")}
                  className="h-4 w-4 accent-[var(--accent)] pointer-coarse:h-6 pointer-coarse:w-6"
                />
              </th>
              <th scope="col" className="label px-3 py-2">{t("parameter")}</th>
              <th scope="col" className="label px-3 py-2 text-right">{t("current")}</th>
              <th scope="col" className="label px-3 py-2 text-right">{t("suggested")}</th>
              <th scope="col" className="label hidden px-3 py-2 md:table-cell">{t("reason")}</th>
              <th scope="col" className="no-print px-3 py-2"><span className="sr-only">{t("copy")}</span></th>
            </tr>
          </thead>
          <tbody>
            {params.map((p) => (
              <tr key={p.param_name} className="border-b align-top last:border-b-0">
                <td className="no-print px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(p.param_name)}
                    onChange={() => toggle(p.param_name)}
                    aria-label={t("select", { name: p.param_name })}
                    className="h-4 w-4 accent-[var(--accent)] pointer-coarse:h-6 pointer-coarse:w-6"
                  />
                </td>
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
                  <span className="sr-only"> ({t(`direction.${p.change_direction}`)})</span>
                </td>
                <td className="hidden px-3 py-2 text-xs text-fg-muted md:table-cell">{p.reason}</td>
                <td className="no-print px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => copy(p.param_name, paramLine(p, format))}
                    className="btn px-2 text-xs"
                    aria-label={t("copyOne", { name: p.param_name })}
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
        {format === "qgc" ? t("hintQgc") : t("hintMp")}
        {autopilotGuess ? ` ${t("pickedFor", { autopilot: autopilotGuess })}` : ""}
      </p>

      <div className="no-print panel space-y-2 p-3">
        <p className="text-xs text-fg-muted">{t("applyHelp")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="apply-label" className="sr-only">{t("airframe")}</label>
          <input
            id="apply-label"
            type="text"
            value={label}
            maxLength={40}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t("airframe")}
            className="input w-40"
          />
          <button
            type="button"
            onClick={markApplied}
            disabled={selected.length === 0 || !label.trim() || applied.phase === "saving"}
            className="btn-primary"
          >
            <ListChecks aria-hidden className="h-4 w-4" />
            {t("markApplied", { count: selected.length })}
          </button>
        </div>
        <div aria-live="polite" className="text-xs">
          {applied.phase === "saved" && (
            <p className="text-ok">
              {t.rich("applied", {
                count: applied.count,
                label: applied.label,
                link: (chunks) => <Link href={`/airframe/${encodeURIComponent(applied.label)}`}>{chunks}</Link>,
              })}
            </p>
          )}
          {applied.phase === "error" && (
            <p role="alert" className="text-critical">
              {applied.message}
              {applied.locked && (
                <>
                  {" "}
                  {t.rich("needsToken", {
                    link: (chunks) => <Link href={`/airframe/${encodeURIComponent(applied.locked ?? "")}`}>{chunks}</Link>,
                  })}
                </>
              )}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
