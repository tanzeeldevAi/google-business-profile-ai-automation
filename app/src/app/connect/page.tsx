"use client";

import { useState } from "react";
import { useApp } from "@/components/Shell";
import { Button, Card, Empty } from "@/components/ui";
import { api } from "@/lib/api";

export default function Connect() {
  const { status, profiles, refresh, run, running } = useApp();
  const [found, setFound] = useState<{ location: string; title: string; city: string }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
          <Button kind="primary" disabled={running} onClick={() => run("login")}>
            {status?.google.signed_in ? "Sign in again" : "Sign in to Google"}
          </Button>
          {status?.google.signed_in && (
            <span className="text-sm text-good">
              Signed in · token {status.google.token_age_days} days old
            </span>
          )}
        </div>
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
