"use client";

import { useState } from "react";
import { useApp } from "@/components/Shell";
import { Button, Card, Empty } from "@/components/ui";
import { api } from "@/lib/api";

export default function Connect() {
  const { status, profiles, refresh } = useApp();
  const [found, setFound] = useState<{ location: string; title: string; city: string }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState("");

  /**
   * Sign in through a real OAuth redirect.
   *
   * The old version shelled out to `run.py login`, which blocks on its own
   * local server and — if a valid token already existed — returned instantly
   * without ever opening a browser. Clicking "sign in" appeared to do nothing,
   * and signing in as a DIFFERENT account was impossible.
   *
   * Now: get the consent URL, open it, and poll until the callback has saved a
   * token. Popup blocked? Fall back to a link the user can click.
   */
  const signIn = async () => {
    setBusy(true);
    setError("");
    try {
      const { url } = await api.authStart();
      const win = window.open(url, "gbp-signin", "width=520,height=680");
      if (!win) {
        setError("Your browser blocked the sign-in window. Allow pop-ups for this page, or open the link that just copied to your clipboard.");
        await navigator.clipboard?.writeText(url).catch(() => {});
        setBusy(false);
        return;
      }
      setWaiting(true);

      // Poll rather than trusting the popup to talk back: it ends up on
      // Google's origin, so we cannot read from it.
      const started = Date.now();
      const timer = setInterval(async () => {
        try {
          const s = await api.status();
          if (s.google.signed_in && (s.google.token_age_days ?? 99) < 0.02) {
            clearInterval(timer);
            setWaiting(false);
            setBusy(false);
            win.close();
            await refresh();
            await discover();
          }
        } catch { /* the API may be briefly busy; keep waiting */ }
        if (Date.now() - started > 4 * 60 * 1000) {
          clearInterval(timer);
          setWaiting(false);
          setBusy(false);
          setError("Timed out waiting for Google. Try again.");
        }
      }, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  const discover = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.discover();
      setFound(r.found);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-5">
      <Card title="Step 1 — sign in to Google">
        <p className="text-sm text-ink-2 mb-4">
          Opens a browser window on this machine. Sign in with the account that
          <strong className="text-ink"> owns or manages</strong> the Business
          Profile. The login is saved locally and reused, so you only do this once.
        </p>
        <div className="flex items-center gap-3 flex-wrap">
          <Button kind="primary" disabled={busy} onClick={signIn}>
            {waiting
              ? "Waiting for Google…"
              : status?.google.signed_in
              ? "Sign in with a different account"
              : "Sign in to Google"}
          </Button>
          {status?.google.signed_in && !waiting && (
            <>
              <span className="text-sm text-good">
                Signed in · token {status.google.token_age_days} days old
              </span>
              <button
                className="text-xs text-ink-3 hover:text-bad"
                onClick={async () => {
                  if (!confirm("Sign out?\n\nThe connected businesses stay in the list; you just have to sign in again to act on them.")) return;
                  await api.signOut();
                  await refresh();
                }}
              >
                sign out
              </button>
            </>
          )}
        </div>
        {waiting && (
          <p className="text-sm text-warn mt-3">
            A Google window opened. Pick the account, approve access, and this
            page will carry on by itself.
          </p>
        )}
        <p className="text-xs text-ink-3 mt-4 leading-relaxed">
          If your OAuth consent screen is still in Testing mode, Google expires the
          login every 7 days. Publishing the app in Cloud Console stops that, and you
          do not need Google to verify it for your own use.
        </p>
      </Card>

      <Card title="Step 2 — find the businesses">
        <p className="text-sm text-ink-2 mb-4">
          Asks Google what this account manages. Every profile it finds becomes
          selectable from the menu at the top of the page.
        </p>
        <Button onClick={discover} disabled={busy || !status?.google.signed_in}>
          {busy ? "Looking…" : "Find my business profiles"}
        </Button>
        {error && <p className="text-sm text-bad mt-3">{error}</p>}

        {found && (
          <div className="mt-4">
            {found.length === 0 ? (
              <Empty>This account manages no Business Profiles.</Empty>
            ) : (
              <>
                <p className="text-sm text-good mb-2">Found {found.length}:</p>
                <ul className="text-sm space-y-1">
                  {found.map((f) => (
                    <li key={f.location} className="flex gap-2">
                      <span className="font-medium">{f.title}</span>
                      <span className="text-ink-3">{f.city}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </Card>

      <Card title={`Connected businesses (${profiles.length})`}>
        {profiles.length === 0 ? (
          <Empty>None yet.</Empty>
        ) : (
          <div className="space-y-2">
            {profiles.map((p) => (
              <div key={p.location} className="flex items-center gap-3 p-3 rounded-lg bg-panel-2">
                <div className="min-w-0">
                  <div className="font-medium truncate">{p.title || p.location}</div>
                  <div className="text-xs text-ink-3 truncate">
                    {p.city} · <code>{p.location}</code>
                  </div>
                </div>
                <div className="ml-auto flex items-center gap-3 shrink-0">
                  {p.score != null && <span className="text-sm font-semibold">{p.score}</span>}
                  <button
                    className="text-xs text-ink-3 hover:text-bad"
                    onClick={async () => {
                      if (!confirm(`Remove ${p.title} from the list?\n\nIts audit history is kept.`)) return;
                      await api.forget(p.location);
                      await refresh();
                    }}
                  >
                    remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
