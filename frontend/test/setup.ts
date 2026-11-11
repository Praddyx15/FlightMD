import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(() => {
  cleanup();
  // the MSW polling tests run in the node environment, without a window
  if (typeof window !== "undefined") window.localStorage.clear();
});
