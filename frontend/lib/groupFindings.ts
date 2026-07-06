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

// Splits a title like "EKF Solution Invalid: Gps Available" or
// "ESC Thermal Stress — Motor 2" into a shared prefix ("EKF Solution
// Invalid", "ESC Thermal Stress") and an item-specific suffix. Findings
// that share a category + prefix are the same underlying check repeated
// per sensor/parameter/motor — grouping them turns N nearly-identical
// cards into one card with N rows.
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
  const order: string[] = [];

  for (const f of findings) {
    const split = splitTitle(f.title);
    const key = split ? `${f.category}::${split.prefix}` : `__single__::${f.id}`;
    if (!buckets.has(key)) {
      buckets.set(key, []);
      order.push(key);
    }
    buckets.get(key)!.push(f);
  }

  const result: FindingOrGroup[] = [];
  for (const key of order) {
    const items = buckets.get(key)!;
    if (items.length === 1) {
      result.push(items[0]);
      continue;
    }
    const split = splitTitle(items[0].title)!;
    const worstSeverity = items.reduce<Severity>(
      (worst, f) => (SEVERITY_ORDER[f.severity] < SEVERITY_ORDER[worst] ? f.severity : worst),
      items[0].severity
    );
    result.push({
      isGroup: true,
      groupTitle: split.prefix,
      category: items[0].category,
      worstSeverity,
      items,
    });
  }
  return result;
}

// The suffix after the shared prefix — the part that's specific to this
// item within a group (e.g. "Gps Available", "Motor 2").
export function groupItemLabel(finding: Finding): string {
  const split = splitTitle(finding.title);
  return split ? split.suffix : finding.title;
}
