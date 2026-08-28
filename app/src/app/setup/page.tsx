"use client";

import { useEffect, useState } from "react";
import { useApp } from "@/components/Shell";
import { Banner, Button, Card, Chip, Empty, Skeleton } from "@/components/ui";
import { api, Capabilities } from "@/lib/api";

/**
 * What actually works, and what to press when it does not.
 *
 * This screen exists because of a real failure: a post was published, Google
 * returned 403 because the legacy API was switched off in the Cloud project,
 * the job carried on, and the profile simply had no post on it. Nothing in the
 * app said why. Now the app checks, and hands you the exact button.
 */
export default function SetupPage() {
  const { active, status, refresh } = useApp();
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async (force = false) => {
    if (!active) return;
    setBusy(true);
    try {
      setCaps(await api.capabilities(active.location, force));
    } catch {
      setCaps(null);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [active?.location]);

  if (!active) return <Empty>Pick a business first.</Empty>;

  const blocked = (caps?.capabilities || []).filter((c) => !c.ok);
  const working = (caps?.capabilities || []).filter((c) => c.ok);

  return (
    <div className="max-w-4xl space-y-4">
      {caps && blocked.length > 0 && (
        <Banner tone="red" title={`${blocked.length} thing${blocked.length === 1 ? "" : "s"} will not work yet`}>
          Until these are switched on, the buttons for them do nothing useful —
          Google refuses the call and the profile never changes.
        </Banner>
      )}

      <Card
        title="What this profile can do"
        subtitle={caps?.project ? `Google Cloud project ${caps.project}` : undefined}
        right={
          <Button kind="outlined" onClick={() => load(true)} disabled={busy}>
            {busy ? "Checking…" : "Re-check"}
          </Button>
        }
      >
        {!caps ? (
          <div className="space-y-3">
            {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-14" />)}
          </div>
        ) : (
          <div className="divide-y divide-g-grey200">
            {caps.capabilities.map((c) => (
              <div key={c.key} className="py-4 first:pt-0 last:pb-0">
                <div className="flex items-start gap-3">
                  <span className={`mt-1 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] text-white
                    ${c.ok ? "bg-g-green" : "bg-g-red"}`}>
                    {c.ok ? "✓" : "!"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-g-grey900">{c.label}</span>
                      <Chip tone={c.ok ? "green" : "red"}>
                        {c.ok ? "working" : "blocked"}
                      </Chip>
                    </div>
                    {!c.ok && (
                      <>
                        <p className="mt-1 text-[13px] text-g-grey700">{c.reason}</p>
                        {c.fix && (
                          <p className="mt-0.5 text-[13px] text-g-grey600">{c.fix}</p>
                        )}
                        <p className="mt-1 text-[12px] text-g-grey600">
                          Without it: {c.breaks}.
                        </p>
                      </>
                    )}
                  </div>
                  {!c.ok && c.link && (
                    <a href={c.link} target="_blank" rel="noreferrer" className="shrink-0">
                      <Button kind="filled">Enable in Google Cloud</Button>
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {caps && blocked.some((c) => c.link) && (
        <Card title="After you enable it">
          <ol className="space-y-2 text-sm text-g-grey700 list-decimal pl-5">
            <li>Press <strong>ENABLE</strong> on the Google page that opens.</li>
            <li>Wait about a minute — Google says it takes a moment to propagate.</li>
            <li>Come back and press <strong>Re-check</strong> above.</li>
            <li>Reviews, Posts and Photos start working immediately after that.</li>
          </ol>
        </Card>
      )}

      <Card title="Everything else">
        <ul className="space-y-3 text-sm">
          <Row
            ok={!!status?.google.signed_in}
            label="Google account connected"
            detail={status?.google.signed_in
              ? `Token is ${status.google.token_age_days} days old`
              : "Not signed in"}
          />
          <Row
            ok={!!status?.clock?.ok}
            label="Computer clock accurate"
            detail={status?.clock?.checked
              ? `${status.clock.skew}s from real time`
              : "Could not check"}
          />
          <Row
            ok={!!status?.llm.ready}
            label={`Writing via ${status?.llm.backend ?? "claude"}`}
            detail="Used for descriptions, review replies and posts"
          />
          <Row
            ok={!!status?.dataforseo}
            optional
            label="DataForSEO"
            detail="Optional. Powers competitor comparison and directory checks"
          />
          <Row
            ok={status?.images !== "none"}
            optional
            label="Post images"
            detail="Optional. Without it posts publish as text only"
          />
        </ul>
        <div className="mt-4">
          <Button kind="text" onClick={refresh}>Refresh</Button>
        </div>
      </Card>
    </div>
  );
}

function Row({ ok, label, detail, optional }: {
  ok: boolean; label: string; detail: string; optional?: boolean;
}) {
  return (
    <li className="flex items-start gap-3">
      <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full
        ${ok ? "bg-g-green" : optional ? "bg-g-grey500" : "bg-g-red"}`} />
      <span className="min-w-0">
        <span className="text-g-grey900">{label}</span>
        <span className="block text-[12.5px] text-g-grey600">{detail}</span>
      </span>
      {!ok && optional && (
        <span className="ml-auto"><Chip>optional</Chip></span>
      )}
    </li>
  );
}
