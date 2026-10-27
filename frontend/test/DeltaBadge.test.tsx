import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { DeltaBadge } from "@/components/shared/DeltaBadge";
import { renderWithIntl } from "./intl";

describe("DeltaBadge", () => {
  it("shows a dash when there is no delta", () => {
    renderWithIntl(<DeltaBadge delta={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("treats less than half a point as no change", () => {
    renderWithIntl(<DeltaBadge delta={0.4} />);
    expect(screen.getByText("no change")).toBeInTheDocument();
  });

  it("marks a higher score as better", () => {
    renderWithIntl(<DeltaBadge delta={5.2} />);
    expect(screen.getByText("+5 better")).toHaveClass("text-ok");
  });

  it("marks a lower score as worse, with a word as well as a colour", () => {
    renderWithIntl(<DeltaBadge delta={-3} />);
    expect(screen.getByText("−3 worse")).toHaveClass("text-caution");
  });
});
