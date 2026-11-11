import type { Category, Finding, Severity } from "./types";
import { SEVERITY_ORDER } from "./utils";

export interface FindingGroup {
  isGroup: true;
  groupTitle: string;
  category: Category;
  worstSeverity: Severity;
  items: Finding[];
}

export type FindingOrGroup = Finding | FindingGroup;

export function isFindingGroup(x: FindingOrGroup): x is FindingGroup {
  return (x as FindingGroup).isGroup === true;
}

// "EKF Solution Invalid: Gps Available" / "ESC Thermal Stress — Motor 2": same check
// repeated per sensor or motor. Same category + prefix -> one card with N rows.
const GROUP_SEPARATORS = [": ", " — "];

function splitTitle(title: string): { prefix: string; suffix: string } | null {
  for (const sep of GROUP_SEPARATORS) {
    const idx = title.indexOf(sep);
    if (idx > 0) {
      return { prefix: title.slice(0, idx), suffix: title.slice(idx + sep.length) };
    }
  }
  return null;
}

export function groupFindings(findings: Finding[]): FindingOrGroup[] {
  const buckets = new Map<string, Finding[]>();

  for (const f of findings) {
    const split = splitTitle(f.title);
    const key = split ? `${f.category}::${split.prefix}` : `__single__::${f.id}`;
    const b = buckets.get(key);
    if (b) b.push(f);
    else buckets.set(key, [f]);
  }

  const result: FindingOrGroup[] = [];
  buckets.forEach((items) => {
    if (items.length === 1) {
      result.push(items[0]);
      return;
    }
    const worstSeverity = items.reduce<Severity>(
      (worst, f) => (SEVERITY_ORDER[f.severity] < SEVERITY_ORDER[worst] ? f.severity : worst),
      items[0].severity
    );
    result.push({
      isGroup: true,
      groupTitle: splitTitle(items[0].title)!.prefix,
      category: items[0].category,
      worstSeverity,
      items,
    });
  });
  return result;
}

export function groupItemLabel(finding: Finding): string {
  const split = splitTitle(finding.title);
  return split ? split.suffix : finding.title;
}
