import { LineChart as LineChartIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import type { Finding } from "@/lib/types";
import { fmtClock, fmtParam } from "@/lib/format";
import { findingEnd, findingStart } from "@/lib/utils";

// Small pieces shared by the single and grouped finding cards.

export function FindingTime({ finding }: { finding: Finding }) {
  const start = findingStart(finding);
  if (start === null) return null;
  const end = findingEnd(finding);
  return (
    <span className="num text-xs text-fg-muted">
      t {fmtClock(start)}
      {end !== null && end > start ? `–${fmtClock(end)}` : ""}
    </span>
  );
}

export function Confidence({ finding }: { finding: Finding }) {
  const t = useTranslations("findings");
  const level = finding.confidence_level;
  const num = (chunks: React.ReactNode) => <span className="num">{chunks}</span>;
  const pct = Math.round(finding.confidence * 100);
  return (
    <span className="text-xs text-fg-muted">
      {level
        ? t.rich("confidenceLevel", { num, pct, level: t(`level.${level}`) })
        : t.rich("confidence", { num, pct })}
    </span>
  );
}

export function ShowOnChart({ finding, onShow }: { finding: Finding; onShow?: (id: string) => void }) {
  const t = useTranslations("findings");
  if (!onShow) return null;
  return (
    <button type="button" onClick={() => onShow(finding.id)} className="btn no-print px-2 text-xs">
      <LineChartIcon aria-hidden className="h-3.5 w-3.5" />
      {t("showOnChart")}
    </button>
  );
}

export function ParamChanges({ finding }: { finding: Finding }) {
  const t = useTranslations("params");
  if (finding.param_changes.length === 0) return null;
  return (
    <div>
      <h4 className="label mb-1">{t("title")}</h4>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-fg-muted">
            <th scope="col" className="pb-1 font-normal">{t("parameter")}</th>
            <th scope="col" className="pb-1 text-right font-normal">{t("current")}</th>
            <th scope="col" className="pb-1 text-right font-normal">{t("suggested")}</th>
          </tr>
        </thead>
        <tbody>
          {finding.param_changes.map((pc) => (
            <tr key={pc.param_name} className="border-t">
              <td className="num py-1 font-medium">{pc.param_name}</td>
              <td className="num py-1 text-right text-fg-muted">{fmtParam(pc.current_value)}</td>
              <td className="num py-1 text-right font-semibold text-accent-text">
                {fmtParam(pc.suggested_value)}
                {pc.unit ? ` ${pc.unit}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FindingBody({ finding }: { finding: Finding }) {
  const t = useTranslations("findings");
  return (
    <div className="space-y-3">
      <div className="rounded border-l-2 border-accent bg-elevated px-3 py-2">
        <h4 className="label mb-0.5">{t("whatToDo")}</h4>
        <p className="text-sm">{finding.recommendation}</p>
      </div>
      <div>
        <h4 className="label mb-0.5">{t("whatHappened")}</h4>
        <p className="text-sm">{finding.plain_english}</p>
      </div>
      <div>
        <h4 className="label mb-0.5">{t("technical")}</h4>
        <p className="num text-xs text-fg-muted">{finding.technical_summary}</p>
      </div>
      <ParamChanges finding={finding} />
    </div>
  );
}
