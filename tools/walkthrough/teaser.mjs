/**
 * The teaser: a 30–40 s cut for a LinkedIn post. Same shape as scenes.mjs, fewer and shorter
 * lines: the hook, one upload, the verdict with its worst finding, the fix copied, the link.
 *
 *   node record.mjs --story teaser [--draft]   → out/teaser.mp4 (or out/teaser-draft.mp4)
 */

import { LOGS, openHome, scoreCircle, uploadAndWait } from "./scenes.mjs";

/**
 * @param {{ cta: string, label: string, logsDir: string }} info
 */
export function buildScenes({ cta, label, logsDir }) {
  return [
    {
      id: "hook",
      say: "Your drone flew badly. The log knows why.",
      thumbnail: true,
      tail: 1.2,
      prepare: async ({ s }) => {
        await s.goto("/");
        await s.card({});
      },
      run: async ({ s }) => {
        await s.card({
          wordmark: "FlightMD",
          title: "Your drone flew badly. The log knows why.",
          subtitle: "PX4, ArduPilot, Betaflight and DJI logs, read in plain English.",
        });
      },
    },
    {
      id: "upload",
      say: "Drop the flight log into FlightMD: PX4, ArduPilot, Betaflight or DJI.",
      speak: "Drop the flight log into Flight M D. P X 4, ArduPilot, Betaflight or D J I.",
      prepare: async ({ s, page }) => {
        await openHome(s, page);
        // tagged, so a second render on the same API doesn't get the earlier report back
        await page.getByLabel("Airframe label (optional)").fill(label);
      },
      run: async ({ s, page, ids }) => {
        await s.hold(0.3);
        ids.flawed = await uploadAndWait(s, page, LOGS.flawed, logsDir);
      },
    },
    {
      id: "verdict",
      say: "Seconds later you get a health score, what went wrong, and when it happened.",
      run: async ({ s, page }) => {
        await s.spotlight(scoreCircle(page), "Health score, from the checks that ran");
        await s.hold(1.4);
        await s.spotlight(page.locator("#findings article").first(), "The worst finding, with its time window");
      },
    },
    {
      id: "fix",
      say: "Plus the exact parameter change to make, ready to paste into QGroundControl or Mission Planner.",
      speak: "Plus the exact parameter change to make, ready to paste into Q Ground Control, or Mission Planner.",
      prepare: async ({ page }) => {
        await page.locator("#params").scrollIntoViewIfNeeded();
      },
      run: async ({ s, page }) => {
        const sheet = page.locator("#params");
        await s.hold(0.2);
        await s.spotlight(sheet.getByRole("table"), "Current value, suggested value, and why");
        await s.hold(1.2);
        await s.clearSpotlight();
        await s.click(sheet.getByRole("button", { name: "Copy all" }));
        await s.waitFor(sheet.getByRole("button", { name: "Copied" }), { speedUp: false });
        await s.spotlight(sheet.getByRole("button", { name: "Copied" }), "Copied, in the ground station's format");
      },
    },
    {
      id: "end",
      say: "FlightMD is free and open source, under the MIT licence. Try it on your own logs today.",
      speak: "Flight M D is free and open source, under the M I T licence. Try it on your own logs today.",
      tail: 1.6,
      prepare: async ({ s }) => {
        await s.goto("/");
        await s.card({});
      },
      run: async ({ s }) => {
        await s.card({
          wordmark: "FlightMD",
          title: "Your drone flew badly. The log knows why.",
          cta,
          footnote: "MIT licence. Part of the UAV suite. The log in this video is a synthetic test flight.",
          staggerMs: 80,
        });
      },
    },
  ];
}
