"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, Profile, Status } from "@/lib/api";
import JobDrawer from "./JobDrawer";

// One place holds "which business are we on" and "is something running", so
// every screen agrees and no screen has to fetch it again.
type Ctx = {
  status: Status | null;
  profiles: Profile[];
  active: Profile | null;
  refresh: () => Promise<void>;
  run: (command: string, options?: Record<string, unknown>, apply?: boolean) => Promise<void>;
  jobId: string | null;
  running: boolean;
};

const AppCtx = createContext<Ctx>({
  status: null, profiles: [], active: null,
  refresh: async () => {}, run: async () => {},
  jobId: null, running: false,
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
  ["/settings", "Settings"],
] as const;

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [status, setStatus] = useState<Status | null>(null);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [jobId, setJobId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([api.status(), api.profiles()]);
      setStatus(s);
      setProfiles(p.profiles);
      setError("");
      // A job started before this tab was open (or by the CLI) still shows.
      if (s.job?.running) { setJobId(s.job.id); setRunning(true); }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const active = profiles.find((p) => p.location === status?.active) || null;

  // Stable identity. Passed to JobDrawer, which subscribes on it -- an inline
  // arrow here would give the drawer a new prop every render.
  const jobDone = useCallback(() => {
    setRunning(false);
    refresh();
  }, [refresh]);

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
    },
    [],
  );

  return (
    <AppCtx.Provider value={{ status, profiles, active, refresh, run, jobId, running }}>
      <div className="min-h-screen flex flex-col">
        <header className="border-b border-line sticky top-0 z-20 bg-base/95 backdrop-blur">
          <div className="max-w-[1400px] mx-auto px-5 py-3 flex items-center gap-4 flex-wrap">
            <Link href="/" className="font-bold tracking-tight">
              GBP&nbsp;Autopilot
            </Link>

            <ProfilePicker
              profiles={profiles}
              active={active}
              onSelect={async (loc) => { await api.select(loc); await refresh(); }}
            />

            <nav className="flex gap-1 flex-wrap ml-auto text-sm">
              {NAV.map(([href, label]) => (
                <Link
                  key={href}
                  href={href}
                  className={`px-3 py-1.5 rounded-md transition ${
                    path === href
                      ? "bg-panel-2 text-ink"
                      : "text-ink-2 hover:text-ink hover:bg-panel"
                  }`}
                >
                  {label}
                </Link>
              ))}
            </nav>
          </div>

          {status?.clock && !status.clock.ok && (
            <Banner tone="bad">
              <strong>This machine&apos;s clock is wrong.</strong> Sign-in will
              fail with <code>invalid_grant</code> until it is fixed — Google
              signs its codes against real time.
              <span className="block mt-1 opacity-90 whitespace-pre-wrap font-mono text-xs">
                {status.clock.message.split("\n").slice(1).join("\n").trim()}
              </span>
            </Banner>
          )}
          {status && !status.google.signed_in && (
            <Banner tone="bad">
              Not signed in to Google.{" "}
              <Link href="/connect" className="underline">Connect an account</Link> to
              start.
            </Banner>
          )}
          {status?.google.expiring_soon && (
            <Banner tone="warn">
              This Google login is {status.google.token_age_days} days old. While your
              OAuth consent screen is in Testing, Google expires it every 7 days —
              publish the app in Cloud Console to stop that.
            </Banner>
          )}
          {error && <Banner tone="bad">{error}</Banner>}
        </header>

        <main className="flex-1 max-w-[1400px] w-full mx-auto px-5 py-6">
          {status && profiles.length === 0 ? <NoProfiles /> : children}
        </main>

        <JobDrawer
          jobId={jobId}
          onDone={jobDone}
          running={running}
        />
      </div>
    </AppCtx.Provider>
  );
}

function Banner({ tone, children }: { tone: "bad" | "warn"; children: React.ReactNode }) {
  const cls = tone === "bad"
    ? "bg-bad/10 border-bad/30 text-bad"
    : "bg-warn/10 border-warn/30 text-warn";
  return (
    <div className={`border-t px-5 py-2 text-sm ${cls}`}>
      <div className="max-w-[1400px] mx-auto">{children}</div>
    </div>
  );
}

function NoProfiles() {
  return (
    <div className="max-w-lg mx-auto text-center py-20">
      <h1 className="text-2xl font-semibold mb-3">No business connected yet</h1>
      <p className="text-ink-2 mb-6">
        Sign in with the Google account that manages the Business Profile. Every
        profile that account manages will show up here.
      </p>
      <Link
        href="/connect"
        className="inline-block px-5 py-2.5 rounded-lg bg-accent text-base font-medium"
      >
        Connect a Google account
      </Link>
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

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-panel border border-line text-sm hover:border-accent transition"
      >
        <span className="font-medium">{active?.title || "Pick a business"}</span>
        {active?.city && <span className="text-ink-3">{active.city}</span>}
        {active?.score != null && (
          <span
            className="text-xs font-semibold px-1.5 py-0.5 rounded"
            style={{ background: "#1D212A", color: active.score >= 75 ? "#4ADE80" : active.score >= 50 ? "#FBBF24" : "#F87171" }}
          >
            {active.score}
          </span>
        )}
        <span className="text-ink-3">▾</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute z-40 mt-1 w-80 max-h-96 overflow-auto rounded-lg border border-line bg-panel shadow-2xl">
            {profiles.map((p) => (
              <button
                key={p.location}
                disabled={!p.reachable}
                title={p.reachable ? undefined
                  : "Connected under a different Google account. Sign in with that account to use it."}
                onClick={() => { onSelect(p.location); setOpen(false); }}
                className={`w-full text-left px-3 py-2.5 border-b border-line/60 last:border-0 ${
                  !p.reachable ? "opacity-40 cursor-not-allowed"
                    : "hover:bg-panel-2"
                } ${p.location === active?.location ? "bg-panel-2" : ""}`}
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{p.title || p.location}</span>
                  {p.score != null && (
                    <span
                      className="ml-auto text-xs font-semibold"
                      style={{ color: p.score >= 75 ? "#4ADE80" : p.score >= 50 ? "#FBBF24" : "#F87171" }}
                    >
                      {p.score}
                    </span>
                  )}
                </div>
                <div className="text-xs text-ink-3 flex gap-2">
                  {p.city && <span>{p.city}</span>}
                  {p.alerts > 0 && <span className="text-bad">{p.alerts} alert(s)</span>}
                  {!p.reachable && (
                    <span className="text-warn ml-auto">other account</span>
                  )}
                </div>
              </button>
            ))}
            <Link
              href="/connect"
              onClick={() => setOpen(false)}
              className="block px-3 py-2.5 text-sm text-accent hover:bg-panel-2"
            >
              + Connect another account
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
