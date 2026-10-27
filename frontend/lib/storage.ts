// Everything kept in the browser: recent uploads and airframe tokens. localStorage can
// throw (private mode, blocked site data), so every access goes through these two.

function read<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage full or blocked: the app works without it
  }
}

const RECENT_KEY = "flightmd.recent";
const TOKENS_KEY = "flightmd.airframeTokens";
const MAX_RECENT = 20;

export interface RecentReport {
  id: string;
  fileName: string;
  uploadedAt: number; // ms epoch
  airframeLabel?: string | null;
  score?: number | null;
  grade?: string | null;
  scoreLabel?: string | null;
  flightStart?: string | null;
  vehicle?: string | null;
  firmware?: string | null;
}

export function getRecentReports(): RecentReport[] {
  const list = read<RecentReport[]>(RECENT_KEY, []);
  return Array.isArray(list) ? list.filter((r) => r && typeof r.id === "string") : [];
}

export function addRecentReport(r: RecentReport) {
  const rest = getRecentReports().filter((x) => x.id !== r.id);
  write(RECENT_KEY, [r, ...rest].slice(0, MAX_RECENT));
}

// only touches ids this browser uploaded; a shared link opened here is not added
export function updateRecentReport(id: string, patch: Partial<RecentReport>) {
  const list = getRecentReports();
  const i = list.findIndex((r) => r.id === id);
  if (i < 0) return;
  list[i] = { ...list[i], ...patch };
  write(RECENT_KEY, list);
}

export function removeRecentReport(id: string) {
  write(RECENT_KEY, getRecentReports().filter((r) => r.id !== id));
}

export function clearRecentReports() {
  write(RECENT_KEY, []);
}

// labels are case-insensitive on the server, so key tokens the same way
const labelKey = (label: string) => label.trim().toLowerCase();

export function getAirframeToken(label: string): string | null {
  const all = read<Record<string, string>>(TOKENS_KEY, {});
  return all[labelKey(label)] ?? null;
}

export function setAirframeToken(label: string, token: string) {
  const all = read<Record<string, string>>(TOKENS_KEY, {});
  all[labelKey(label)] = token.trim();
  write(TOKENS_KEY, all);
}

export function forgetAirframeToken(label: string) {
  const all = read<Record<string, string>>(TOKENS_KEY, {});
  delete all[labelKey(label)];
  write(TOKENS_KEY, all);
}
