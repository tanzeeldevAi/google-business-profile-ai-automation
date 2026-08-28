// Everything the UI knows about the backend lives here, so a change to the
// API is one file to update rather than a hunt through components.

export type Finding = {
  rule_id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  category: string;
  passed: boolean;
  detail: string;
  why: string;
  fix: string;
  fixable: boolean;
  informational: boolean;
  command?: string | null;
};

export type Audit = {
  score: number;
  grade: string;
  title: string;
  when: string;
  findings: Finding[];
  previous: number | null;
};

export type Profile = {
  location: string;
  account: string;
  title: string;
  city: string;
  settings: ProfileSettings;
  score: number | null;
  grade: string | null;
  last_audit: string | null;
  history: { score: number; when: string }[];
  alerts: number;
  // False when this profile was connected under a DIFFERENT Google sign-in.
  // One token covers one account, so nothing can act on it until that account
  // is signed in again.
  reachable: boolean;
};

export type ProfileSettings = {
  business?: {
    name?: string;
    city?: string;
    what_we_do?: string;
    facts?: string[];
  };
  website?: { url?: string; service_pages?: string[] };
  competitors?: { keywords?: string[] };
  holidays?: { region_code?: string };
};

export type Capability = {
  key: string;
  label: string;
  ok: boolean;
  reason: string;
  fix: string;
  link: string;
  breaks: string;
};

export type SetupItem = {
  kind: "api" | "consent";
  id: string;
  name: string;
  why: string;
  link: string;
};

export type Capabilities = {
  project: string;
  checked_at: number;
  all_ok: boolean;
  capabilities: Capability[];
  setup: SetupItem[];
};

export type PlannedFix = {
  key: string;
  title: string;
  before: string;
  after: string;
  notes: string[];
  proposed: { name: string; description: string; terms: string[] }[];
  // The exact payload and field mask this fix would send, so the screen can
  // show it, let it be edited, and send back something Google will accept.
  update_mask: string;
  body: Record<string, unknown>;
};

export type FixPlan = {
  location: string;
  planned_at: number;
  fixes: PlannedFix[];
};

export type CategoryRef = { id: string; name: string };

export type ProfileDetails = {
  title: string;
  address_line: string;
  locality: string;
  postal_code: string;
  region: string;
  phone: string;
  website: string;
  primary: CategoryRef;
  additional: CategoryRef[];
  services: { total: number; described: number };
};

export type Review = {
  name: string;
  reviewer: string;
  photo: string;
  stars: number;
  comment: string;
  when: string;
  reply: string | null;
  replied_when: string | null;
};

export type Clock = {
  checked: boolean;
  skew: number | null;
  ok: boolean;
  message: string;
};

export type Status = {
  configured: boolean;
  clock: Clock;
  google: {
    signed_in: boolean;
    token_age_days: number | null;
    expiring_soon: boolean;
  };
  llm: { backend: string; ready: boolean };
  dataforseo: boolean;
  images: string;
  active: string;
  job: Job | null;
};

export type Job = {
  id: string;
  command: string;
  argv: string[];
  location: string;
  running: boolean;
  exit_code: number | null;
  elapsed: number;
  total: number;
  lines: string[];
};

const TOKEN =
  typeof window !== "undefined"
    ? new URLSearchParams(window.location.search).get("t") || ""
    : "";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path + (TOKEN ? (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(TOKEN) : "");
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(TOKEN ? { "X-Token": TOKEN } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    // FastAPI puts the useful message in `detail`. Surfacing that rather than
    // "500" is the difference between a fixable error and a mystery.
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {}
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export const api = {
  status: () => call<Status>("/api/status"),
  capabilities: (location: string, refresh = false) =>
    call<Capabilities>(`/api/capabilities/${location}${refresh ? "?refresh=true" : ""}`),
  details: (location: string) =>
    call<ProfileDetails>(`/api/details/${location}`),
  searchCategories: (q: string) =>
    call<{ region: string; categories: CategoryRef[] }>(
      `/api/categories?q=${encodeURIComponent(q)}`),
  fixPlan: (location: string) =>
    call<{ plan: FixPlan | null }>(`/api/fix/plan/${location}`),
  reviews: (location: string) =>
    call<{ reviews: Review[]; average: number | null; total: number;
           unanswered: number; blocked: string | null }>(`/api/reviews/${location}`),
  replyToReview: (location: string, name: string, comment: string) =>
    call<{ ok: boolean }>(`/api/reviews/${location}/reply`, {
      method: "POST", body: JSON.stringify({ name, comment }),
    }),
  draftReply: (location: string, name: string) =>
    call<{ draft: string; held: boolean; why: string }>(
      `/api/reviews/${location}/draft`, {
        method: "POST", body: JSON.stringify({ name }),
      }),
  authStart: () => call<{ url: string }>("/api/auth/start"),
  signOut: () => call<{ signed_out: boolean }>("/api/auth/signout", { method: "POST" }),
  applyFix: (location: string, key: string, body: Record<string, unknown>) =>
    call<{ ok: boolean; applied: string; update_mask: string }>(
      `/api/fix/apply/${location}`,
      { method: "POST", body: JSON.stringify({ key, body }) }),
  profiles: () => call<{ profiles: Profile[]; active: string }>("/api/profiles"),
  discover: () =>
    call<{ found: { location: string; title: string; city: string }[]; active: string }>(
      "/api/profiles/discover",
      { method: "POST" },
    ),
  select: (location: string) =>
    call<{ active: string }>("/api/profiles/select", {
      method: "POST",
      body: JSON.stringify({ location }),
    }),
  forget: (location: string) =>
    call<{ removed: boolean }>(`/api/profiles/${location}`, { method: "DELETE" }),
  saveSettings: (location: string, settings: ProfileSettings) =>
    call<{ settings: ProfileSettings }>(`/api/profiles/${location}/settings`, {
      method: "PUT",
      body: JSON.stringify({ settings }),
    }),
  audit: (location: string) => call<{ audit: Audit | null }>(`/api/audit/${location}`),
  activity: (location: string) =>
    call<{ actions: { kind: string; target: string; detail: string; dry_run: boolean; when: string }[] }>(
      `/api/activity/${location}`,
    ),
  alerts: (location: string) =>
    call<{ alerts: { severity: string; message: string; when: string }[] }>(`/api/alerts/${location}`),
  ackAlerts: (location: string) =>
    call<{ acknowledged: number }>(`/api/alerts/${location}/ack`, { method: "POST" }),
  reports: () =>
    call<{ reports: { name: string; when: string; size: number }[] }>("/api/reports"),
  reportUrl: (name: string) =>
    `/api/reports/${encodeURIComponent(name)}${TOKEN ? "?t=" + encodeURIComponent(TOKEN) : ""}`,
  run: (command: string, options: Record<string, unknown> = {}, apply = false, location?: string) =>
    call<Job>("/api/run", {
      method: "POST",
      body: JSON.stringify({ command, options, apply, location }),
    }),
  job: (id: string, since = 0) => call<Job>(`/api/jobs/${id}?since=${since}`),
  stop: () => call<{ stopped: boolean }>("/api/jobs/stop", { method: "POST" }),
  streamUrl: (id: string) =>
    `/api/jobs/${id}/stream${TOKEN ? "?t=" + encodeURIComponent(TOKEN) : ""}`,
};

export const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 } as const;

export const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-bad/15 text-bad border-bad/40",
  high: "bg-write/15 text-write border-write/40",
  medium: "bg-accent/15 text-accent border-accent/40",
  low: "bg-ink-3/15 text-ink-2 border-line",
};

export const CATEGORY_LABELS: Record<string, string> = {
  health: "Profile health",
  nap: "Name, address and phone",
  categories: "Categories",
  content: "Description and services",
  hours: "Opening hours",
  media: "Photos and video",
  reviews: "Reviews",
  posts: "Google Posts",
  qanda: "Questions and answers",
  website: "Website",
  keywords: "Search terms",
  competitors: "Against your competitors",
  offpage: "Directory listings",
  performance: "Performance",
};

export function scoreColour(score: number): string {
  if (score >= 75) return "#4ADE80";
  if (score >= 50) return "#FBBF24";
  return "#F87171";
}

export function ago(iso: string): string {
  const then = new Date(iso).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
