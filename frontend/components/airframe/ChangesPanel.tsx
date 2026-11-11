"use client";

import Link from "next/link";
import { AlertTriangle, ArrowLeftRight, ArrowRight, CheckCircle2, Clock, GitCompare, Info, Minus, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ChangeRecord, VerifyStatus } from "@/lib/types";
import { DASH, fmtDateTime, fmtParam, isNum } from "@/lib/format";
import { useLabels } from "@/lib/useLabels";
import { useUnits } from "@/lib/units";
import { TONE_CLASSES, cn } from "@/lib/utils";

const NEUTRAL = "text-fg-muted bg-elevated border-border";

// every status gets an icon and a word, never colour alone
const STATUS: Record<VerifyStatus, { Icon: LucideIcon; cls: string }> = {
  pending: { Icon: Clock, cls: NEUTRAL },
  improved: { Icon: CheckCircle2, cls: TONE_CLASSES.ok },
  unchanged: { Icon: Minus, cls: NEUTRAL },
  worse: { Icon: AlertTriangle, cls: TONE_CLASSES.caution },
  mixed: { Icon: Info, cls: TONE_CLASSES.advisory },
};

// created_at: epoch seconds like the trends endpoint, or an ISO string
function toDate(v: string | number): Date | null {
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

const signed = (v: number, text: string) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${text}`;

export function ChangesPanel({ changes }: { changes: ChangeRecord[] }) {
  const t = useTranslations("changes");
  const labels = useLabels();
  const units = useUnits();

  function deltaRow(key: string, v: number | null): [string, string] {
    if (key === "overall_score") return [t("overall"), isNum(v) ? signed(v, String(Math.round(Math.abs(v)))) : DASH];
    // module scores come as "module.gps" or a bare module name
    const mod = key.startsWith("module.") ? key.slice(7) : key.includes(".") ? null : key;
    if (mod) return [t("moduleScore", { module: labels.module(mod) }), isNum(v) ? signed(v, String(Math.round(Math.abs(v)))) : DASH];
    const label = labels.metric(key, units).label;
    return [label, isNum(v) ? signed(v, labels.format(key, Math.abs(v), units)) : DASH];
  }

  return (
    <section aria-labelledby="changes-h" className="space-y-3">
      <h2 id="changes-h" className="flex items-center gap-2 text-base font-semibold">
        <GitCompare aria-hidden className="h-4 w-4 text-accent" />
        {t("title")}
      </h2>
      <p className="text-xs text-fg-muted">{t("help")}</p>

      {changes.length === 0 ? (
        <p className="panel p-4 text-sm text-fg-muted">{t("empty")}</p>
      ) : (
        <ul className="space-y-3">
          {changes.map((c) => {
            const v = c.verify;
            const { Icon, cls } = STATUS[v.status] ?? STATUS.pending;
            const when = toDate(c.created_at);
            const deltas = Object.entries(v.metric_deltas ?? {});
            return (
              <li key={c.id} className="panel space-y-3 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={cn("inline-flex items-center gap-1 rounded-sm border px-1.5 py-px text-xs font-semibold", cls)}>
                    <Icon aria-hidden className="h-3.5 w-3.5" />
                    {t(`status.${v.status}`)}
                  </span>
                  <span className="text-xs text-fg-muted">
                    {t(c.applied_by === "uaop" ? "appliedByUaop" : "appliedByUser", { when: when ? fmtDateTime(when) : DASH })}
                  </span>
                </div>

                <table className="w-full text-xs">
                  <caption className="sr-only">{t("tableCaption")}</caption>
                  <thead>
                    <tr className="text-left text-fg-muted">
                      <th scope="col" className="pb-1 font-normal">{t("parameter")}</th>
                      <th scope="col" className="pb-1 text-right font-normal">{t("from")}</th>
                      <th scope="col" className="pb-1 text-right font-normal">{t("to")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.changes.map((p) => (
                      <tr key={p.name} className="border-t">
                        <td className="num py-1 font-medium">{p.name}</td>
                        <td className="num py-1 text-right text-fg-muted">{fmtParam(p.from_value)}</td>
                        <td className="num py-1 text-right font-semibold">{fmtParam(p.to_value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {c.note && <p className="text-xs text-fg-muted">{c.note}</p>}

                {v.status === "pending" ? (
                  <p className="text-xs text-fg-muted">{t("pendingHelp")}</p>
                ) : (
                  <div className="grid gap-3 text-xs sm:grid-cols-3">
                    <TitleList title={t("resolved")} items={v.findings_resolved} empty={t("noneResolved")} />
                    <TitleList title={t("new")} items={v.findings_new} empty={t("noneNew")} />
                    <div>
                      <h3 className="label mb-1">{t("deltas")}</h3>
                      {deltas.length === 0 ? (
                        <p className="text-fg-muted">{DASH}</p>
                      ) : (
                        <dl className="space-y-0.5">
                          {deltas.map(([key, d]) => {
                            const [label, text] = deltaRow(key, d);
                            return (
                              <div key={key} className="flex justify-between gap-2">
                                <dt>{label}</dt>
                                <dd className="num">{text}</dd>
                              </div>
                            );
                          })}
                        </dl>
                      )}
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap gap-2 text-xs">
                  <Link href={`/report/${encodeURIComponent(c.report_id)}`} className="btn text-xs">
                    {t("appliedOn")}
                  </Link>
                  {v.next_report_id && (
                    <>
                      <Link href={`/report/${encodeURIComponent(v.next_report_id)}`} className="btn text-xs">
                        <ArrowRight aria-hidden className="h-3.5 w-3.5" />
                        {t("verifiedBy")}
                      </Link>
                      <Link
                        href={`/compare?a=${encodeURIComponent(c.report_id)}&b=${encodeURIComponent(v.next_report_id)}`}
                        className="btn text-xs"
                      >
                        <ArrowLeftRight aria-hidden className="h-3.5 w-3.5" />
                        {t("compare")}
                      </Link>
                    </>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function TitleList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  const unique = Array.from(new Set(items));
  return (
    <div>
      <h3 className="label mb-1">{title}</h3>
      {unique.length === 0 ? (
        <p className="text-fg-muted">{empty}</p>
      ) : (
        <ul className="list-disc space-y-0.5 pl-4">
          {unique.map((x) => <li key={x}>{x}</li>)}
        </ul>
      )}
    </div>
  );
}
