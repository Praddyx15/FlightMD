import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UnitsToggle } from "@/components/shared/UnitsToggle";
import { makeLabels } from "@/lib/metricLabels";
import messages from "@/messages/en.json";
import { renderWithIntl } from "./intl";

describe("UnitsToggle", () => {
  it("starts metric and remembers the choice", async () => {
    renderWithIntl(<UnitsToggle />);
    const select = screen.getByRole("combobox", { name: /^Units/ });
    expect(select).toHaveValue("metric");

    await userEvent.selectOptions(select, "imperial");
    expect(select).toHaveValue("imperial");
    expect(window.localStorage.getItem("flightmd.units")).toBe('"imperial"');
  });

  it("picks up a stored choice", () => {
    window.localStorage.setItem("flightmd.units", '"aviation"');
    renderWithIntl(<UnitsToggle />);
    expect(screen.getByRole("combobox", { name: /^Units/ })).toHaveValue("aviation");
  });

  it("ignores a stored value it doesn't know", () => {
    window.localStorage.setItem("flightmd.units", '"cubits"');
    renderWithIntl(<UnitsToggle />);
    expect(screen.getByRole("combobox", { name: /^Units/ })).toHaveValue("metric");
  });
});

describe("metric labels", () => {
  const labels = makeLabels(messages);

  it("names modules and metrics from the messages", () => {
    expect(labels.module("ekf")).toBe("EKF Health");
    expect(labels.metric("gps.max_hdop").label).toBe("Max GPS HDOP");
    expect(labels.format("battery.sag_per_cell_v", 0.4567)).toBe("0.46 V");
  });

  it("humanises a metric it has never seen", () => {
    expect(labels.metric("motors.esc_temp_max_c")).toEqual({ label: "Esc temp max c", unit: "", digits: 2 });
    expect(labels.module("new_module")).toBe("new_module");
  });

  it("converts altitudes with the unit preference", () => {
    expect(labels.metric("ascent_profile.apogee_altitude_m", "imperial").unit).toBe("ft AGL");
    expect(labels.format("ascent_profile.apogee_altitude_m", 100, "imperial")).toBe("328 ft AGL");
    expect(labels.format("ascent_profile.apogee_altitude_m", 100)).toBe("100 m AGL");
    expect(labels.convert("ascent_profile.apogee_altitude_m", 100, "aviation")).toBeCloseTo(328.084, 3);
  });
});
