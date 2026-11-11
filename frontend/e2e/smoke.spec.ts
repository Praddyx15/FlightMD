import path from "node:path";
import { expect, test } from "@playwright/test";

const SAMPLE = path.resolve(__dirname, "../../tests/sample_logs/sample_flawed.ulg");

test.use({ permissions: ["clipboard-read", "clipboard-write"] });

test("upload a log, read the report, copy the parameter changes", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Find out why your drone flew badly");

  await page.getByLabel("Flight log file").setInputFiles(SAMPLE);

  await page.waitForURL(/\/report\/[^/]+$/);
  // the analysis takes a while; the report header carries the file name
  await expect(page.getByRole("heading", { level: 1, name: "sample_flawed.ulg" })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("heading", { name: /^Findings/ })).toBeVisible();

  const params = page.locator("#params");
  await expect(params).toBeVisible();
  await params.getByRole("button", { name: "Mission Planner", exact: true }).click();
  await params.getByRole("button", { name: "Copy all" }).click();
  await expect(params.getByRole("button", { name: "Copied" })).toBeVisible();

  const text = await page.evaluate(() => navigator.clipboard.readText());
  const lines = text.replace(/\r\n/g, "\n").trim().split("\n");
  expect(lines[0]).toBe("# FlightMD suggested changes");
  expect(lines.length).toBeGreaterThan(1);
  for (const line of lines.slice(1)) expect(line).toMatch(/^[A-Z0-9_]+,-?\d+(\.\d+)?$/);
});
