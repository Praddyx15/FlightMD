/**
 * Talking to the running FlightMD before recording: check that the web app and the API answer,
 * and find an airframe label nobody has claimed yet on this instance.
 */

async function getJson(url, init) {
  let response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    throw new Error(`No answer from ${url} (${error.cause?.code ?? error.message}).`);
  }
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  return { status: response.status, ok: response.ok, headers: response.headers, body, text };
}

/** Throws with a fix when the app is not ready to be recorded. Returns the API's /health body. */
export async function preflight({ appUrl, apiUrl }, log) {
  const web = await fetch(new URL("/", appUrl)).catch(() => null);
  if (!web || !web.ok) {
    throw new Error(
      `The web app does not answer at ${appUrl}. Start it first (README.md, "Start FlightMD"): in frontend/, ` +
        `"npm run build && npm start". Set APP_URL if it runs elsewhere.`,
    );
  }
  const origin = new URL(appUrl).origin;
  const health = await getJson(new URL("/health", apiUrl), { headers: { Origin: origin } });
  if (!health.ok || health.body?.status !== "ok") {
    throw new Error(`The API does not answer at ${apiUrl}/health. Start it from the repo root with "python -m uvicorn api.main:app". Set API_URL if it runs elsewhere.`);
  }
  // the browser calls the API cross-origin; without this every upload ends in "Network error"
  const allowed = health.headers.get("access-control-allow-origin");
  if (allowed !== origin && allowed !== "*") {
    log(`warning: the API did not allow ${origin} (CORS). If uploads fail, add it to CORS_ORIGINS and restart the API.`);
  }
  return health.body;
}

/**
 * The first of `${base}-1` … `${base}-20` that nobody has claimed. A label claimed by an earlier
 * render is locked to that browser's token, which went away with it.
 */
export async function freeLabel(apiUrl, base) {
  for (let n = 1; n <= 20; n++) {
    const label = `${base}-${n}`;
    const res = await getJson(new URL(`/airframe/${encodeURIComponent(label)}/config`, apiUrl));
    // console.log(label, res.status, res.body?.detail);
    if (res.status === 401 && /not claimed/i.test(res.body?.detail ?? "")) return label;
  }
  throw new Error(
    `${base}-1 to ${base}-20 are all claimed on this API. Stop it, delete its FLIGHTMD_DATA_DIR and start it again.`,
  );
}
