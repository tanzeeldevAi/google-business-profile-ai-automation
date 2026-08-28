"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, Capabilities, Profile, Status } from "@/lib/api";
import JobDrawer from "./JobDrawer";
import { Banner, Button, Chip, Progress } from "./ui";

type Ctx = {
  status: Status | null;
  profiles: Profile[];
  active: Profile | null;
  caps: Capabilities | null;
  can: (key: string) => boolean;
  blockedReason: (key: string) => { reason: string; fix: string; link: string } | null;
  refresh: () => Promise<void>;
  run: (command: string, options?: Record<string, unknown>, apply?: boolean) => Promise<void>;
  jobId: string | null;
  running: boolean;
};

const AppCtx = createContext<Ctx>({
  status: null, profiles: [], active: null, caps: null,
  can: () => true, blockedReason: () => null,
  refresh: async () => {}, run: async () => {}, jobId: null, running: false,
});

export const useApp = () => useContext(AppCtx);

const NAV = [
  ["/", "Overview"],
  ["/audit", "Audit"],
  ["/fix", "Fix"],
  ["/reviews", "Reviews"],
  ["/posts", "Posts"],
  ["/keywords", "Search terms"],
  ["/competitors", "Competitors"],
  ["/setup", "Setup"],
  ["/settings", "Settings"],
] as const;

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [status, setStatus] = useState<Status | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api.status(), api.profiles()]);
      setStatus(s);
      setProfiles(p.profiles);
      setError("");
      if (s.job?.running) { setJobId(s.job.id); setRunning(true); }
      if (s.active) {
        api.capabilities(s.active).then(setCaps).catch(() => setCaps(null));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const active = profiles.find((p) => p.location === status?.active) || null;

  // "Can we actually do this?" is asked by every screen before it offers a
  // button. Unknown counts as yes, so a slow probe never blocks the UI.
  const can = useCallback((key: string) => {
    const c = caps?.capabilities.find((x) => x.key === key);
    return c ? c.ok : true;
  }, [caps]);

  const blockedReason = useCallback((key: string) => {
    const c = caps?.capabilities.find((x) => x.key === key);
    return c && !c.ok ? { reason: c.reason, fix: c.fix, link: c.link } : null;
  }, [caps]);

  const jobDone = useCallback(() => { setRunning(false); refresh(); }, [refresh]);

  const run = useCallback(
    async (command: string, options: Record<string, unknown> = {}, apply = false) => {
      try {
        const job = await api.run(command, options, apply);
        setJobId(job.id);
        setRunning(true);
        setError("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    }, []);

  const blocked = (caps?.capabilities || []).filter((c) => !c.ok && c.link);

  return (
    <AppCtx.Provider value={{ status, profiles, active, caps, can, blockedReason,
                              refresh, run, jobId, running }}>
      <div className="min-h-screen flex flex-col">
        {/* Google's app bar: white, one hairline, progress rides the top edge. */}
        <header className="sticky top-0 z-30 bg-white border-b border-g-grey300">
          {running && <div className="absolute inset-x-0 top-0"><Progress /></div>}

          <div className="mx-auto max-w-[1400px] px-6 h-16 flex items-center gap-4">
            <Link href="/" className="flex items-center gap-2.5 shrink-0">
              <GoogleMark />
              <span className="font-sans text-[21px] text-g-grey700 leading-none">
                Business&nbsp;<span className="text-g-grey900 font-medium">Autopilot</span>
              </span>
            </Link>

            <ProfilePicker
              profiles={profiles}
              active={active}
              onSelect={async (loc) => { await api.select(loc); await refresh(); }}
            />

            <div className="ml-auto flex items-center gap-2">
              {status?.google.signed_in ? (
                <Chip tone="green">Connected</Chip>
              ) : (
                <Link href="/connect"><Button kind="filled">Sign in</Button></Link>
              )}
            </div>
          </div>

          <nav className="mx-auto max-w-[1400px] px-6 flex gap-1 overflow-x-auto scroll-slim">
            {NAV.map(([href, label]) => {
              const on = path === href;
              return (
                <Link
                  key={href}
                  href={href}
                  className={`relative shrink-0 px-4 h-12 flex items-center text-sm font-sans
                    transition-colors duration-150
                    ${on ? "text-g-blue font-medium" : "text-g-grey600 hover:text-g-grey900"}`}
                >
                  {label}
                  <span
                    className={`absolute inset-x-2 bottom-0 h-[3px] rounded-t-full bg-g-blue
                      transition-transform duration-200 origin-center
                      ${on ? "scale-x-100" : "scale-x-0"}`}
                    style={{ transitionTimingFunction: "cubic-bezier(.4,0,.2,1)" }}
                  />
                </Link>
              );
            })}
          </nav>
        </header>

        <main className="mx-auto w-full max-w-[1400px] flex-1 px-6 py-6 space-y-4">
          {status?.clock && !status.clock.ok && (
            <Banner tone="red" title="This computer's clock is wrong">
              Sign-in will fail with <code>invalid_grant</code> until it is fixed.
              Google signs its codes against real time.
            </Banner>
          )}

          {status && !status.google.signed_in && !loading && (
            <Banner
              tone="red"
              title="Not signed in to Google"
              action={<Link href="/connect"><Button kind="filled">Connect</Button></Link>}
            >
              Connect the account that manages the Business Profile to begin.
            </Banner>
          )}

          {blocked.length > 0 && path !== "/setup" && (
            <Banner
              tone="yellow"
              title={`${blocked.length} feature${blocked.length === 1 ? "" : "s"} switched off in Google Cloud`}
              action={<Link href="/setup"><Button kind="tonal">Fix this</Button></Link>}
            >
              {blocked.map((c) => c.label).join(", ")} will not work until the API is
              enabled — which is why a published post can silently never appear.
            </Banner>
          )}

          {status?.google.expiring_soon && (
            <Banner tone="yellow" title="This Google login expires soon">
              It is {status.google.token_age_days} days old. While your OAuth consent
              screen is in Testing, Google expires it every 7 days — publish the app
              in Cloud Console to stop that.
            </Banner>
          )}

          {error && <Banner tone="red" title="Something went wrong">{error}</Banner>}

          {loading ? <Loading /> :
            status && profiles.length === 0 ? <NoProfiles /> : children}
        </main>

        <JobDrawer jobId={jobId} running={running} onDone={jobDone} />
      </div>
    </AppCtx.Provider>
  );
}

function GoogleMark() {
  // Four dots in Google's colours: recognisable without borrowing the logo.
  return (
    <span className="grid grid-cols-2 gap-[3px]" aria-hidden>
      {["#4285f4", "#ea4335", "#fbbc04", "#34a853"].map((c) => (
        <span key={c} className="h-2 w-2 rounded-full" style={{ background: c }} />
      ))}
    </span>
  );
}

function Loading() {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-40 rounded-g bg-white border border-g-grey300 animate-pulse" />
      ))}
    </div>
  );
}

function NoProfiles() {
  return (
    <div className="mx-auto max-w-md text-center py-20 animate-fade-up">
      <h1 className="font-sans text-2xl text-g-grey900 mb-2">
        No business connected yet
      </h1>
      <p className="text-g-grey600 mb-6 text-sm leading-relaxed">
        Sign in with the Google account that manages the Business Profile. Every
        profile that account manages appears here.
      </p>
      <Link href="/connect"><Button kind="filled">Connect a Google account</Button></Link>
    </div>
  );
}

function ProfilePicker({
  profiles, active, onSelect,
}: {
  profiles: Profile[];
  active: Profile | null;
  onSelect: (location: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!profiles.length) return null;

  const initials = (t: string) =>
    t.split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

  /**
   * Only the businesses this Google sign-in can actually act on.
   *
   * One OAuth token covers one Google account, so a profile connected under a
   * different account is not something you can audit, fix or post to right
   * now. Listing it greyed out was noise: it made a one-client menu look like
   * a four-client menu. It is hidden rather than forgotten -- sign in with the
   * other account and it comes straight back.
   *
   * The active profile always stays in the list even if it is unreachable, so
   * the menu can never disagree with the name in the button above it.
   */
  const shown = profiles.filter(
    (p) => p.reachable || p.location === active?.location);
  const hidden = profiles.length - shown.length;

  // Google will happily report two separate listings with the same name in the
  // same city -- real duplicates on the account, not a bug here. Tell them
  // apart by id, but only for the names that actually collide.
  const nameKey = (p: Profile) => `${p.title}|${p.city}`;
  const counts = new Map<string, number>();
  for (const p of shown) counts.set(nameKey(p), (counts.get(nameKey(p)) ?? 0) + 1);
  const ambiguous = new Set(
    [...counts.entries()].filter(([, n]) => n > 1).map(([k]) => k));

  return (
    <div className="relative min-w-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2.5 rounded-pill border border-g-grey300 bg-white
          pl-1.5 pr-3 h-10 max-w-[22rem] hover:bg-g-grey50 hover:shadow-e1
          transition-all duration-200"
        style={{ transitionTimingFunction: "cubic-bezier(.4,0,.2,1)" }}
      >
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full
          bg-g-blueLight text-[11px] font-medium text-g-blue">
          {active ? initials(active.title || "?") : "?"}
        </span>
        <span className="min-w-0 text-left">
          <span className="block truncate text-[13px] font-medium text-g-grey900 leading-tight">
            {active?.title || "Pick a business"}
          </span>
          {active?.city && (
            <span className="block truncate text-[11px] text-g-grey600 leading-tight">
              {active.city}
            </span>
          )}
        </span>
        <svg width="18" height="18" viewBox="0 0 24 24" className="shrink-0 fill-g-grey600">
          <path d="M7 10l5 5 5-5z" />
        </svg>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute z-50 mt-2 w-[22rem] max-h-[26rem] overflow-auto scroll-slim
            rounded-g border border-g-grey300 bg-white shadow-e3 py-2 animate-fade-up">
            {shown.map((p) => (
              <button
                key={p.location}
                disabled={!p.reachable}
                title={p.reachable ? undefined
                  : "Connected under a different Google account. Sign in with that account to use it."}
                onClick={() => { onSelect(p.location); setOpen(false); }}
                className={`flex w-full items-center gap-3 px-4 py-2.5 text-left
                  ${p.reachable ? "hover:bg-g-grey100" : "opacity-45 cursor-not-allowed"}
                  ${p.location === active?.location ? "bg-g-blueLight/60" : ""}`}
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full
                  bg-g-grey100 text-[11px] font-medium text-g-grey700">
                  {initials(p.title || "?")}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-g-grey900">
                    {p.title || p.location}
                  </span>
                  <span className="block truncate text-[11px] text-g-grey600">
                    {p.city}
                    {ambiguous.has(nameKey(p)) &&
                      ` · id …${p.location.slice(-4)}`}
                    {!p.reachable && " · other Google account"}
                  </span>
                </span>
                {p.score != null && (
                  <Chip tone={p.score >= 75 ? "green" : p.score >= 50 ? "yellow" : "red"}>
                    {String(p.score)}
                  </Chip>
                )}
              </button>
            ))}
            <div className="mt-1 border-t border-g-grey200 pt-1">
              {hidden > 0 && (
                <p className="px-4 pb-1.5 pt-1 text-[11px] leading-snug text-g-grey600">
                  {hidden} more {hidden === 1 ? "business is" : "businesses are"} connected
                  under a different Google account. Sign in with that account to see
                  {hidden === 1 ? " it" : " them"}.
                </p>
              )}
              <Link
                href="/connect"
                onClick={() => setOpen(false)}
                className="block px-4 py-2.5 text-[13px] text-g-blue hover:bg-g-grey100"
              >
                Connect another account
              </Link>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
