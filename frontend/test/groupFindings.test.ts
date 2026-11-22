import { describe, expect, it } from "vitest";
import { groupFindings, groupItemLabel, isFindingGroup } from "@/lib/groupFindings";
import { finding } from "./fixtures";

describe("groupFindings", () => {
  // covers: HLR-WEB-006, LLR-WEB-036, LLR-WEB-041
  it("groups the same check repeated per sensor or motor", () => {
    const out = groupFindings([
      finding({ id: "1", category: "ekf", severity: "warning", title: "EKF Solution Invalid: Gps Available" }),
      finding({ id: "2", category: "ekf", severity: "critical", title: "EKF Solution Invalid: Attitude" }),
      finding({ id: "3", category: "battery", title: "Battery sag" }),
    ]);
    expect(out).toHaveLength(2);
    const group = out.find(isFindingGroup);
    expect(group).toMatchObject({ groupTitle: "EKF Solution Invalid", category: "ekf", worstSeverity: "critical" });
    expect(group?.items.map((f) => f.id)).toEqual(["1", "2"]);
  });

  // covers: HLR-WEB-006, LLR-WEB-041
  it("keeps a lone prefixed finding as a plain finding", () => {
    const out = groupFindings([finding({ id: "1", category: "motors", title: "ESC Thermal Stress — Motor 2" })]);
    expect(isFindingGroup(out[0])).toBe(false);
  });

  // covers: HLR-WEB-006, LLR-WEB-041
  it("does not group the same prefix across categories", () => {
    const out = groupFindings([
      finding({ id: "1", category: "gps", title: "Signal: weak" }),
      finding({ id: "2", category: "ekf", title: "Signal: lost" }),
    ]);
    expect(out.some(isFindingGroup)).toBe(false);
  });

  // covers: HLR-WEB-006, LLR-WEB-042
  it("labels group rows by the part after the separator", () => {
    expect(groupItemLabel(finding({ title: "ESC Thermal Stress — Motor 2" }))).toBe("Motor 2");
    expect(groupItemLabel(finding({ title: "Battery sag" }))).toBe("Battery sag");
  });
});
