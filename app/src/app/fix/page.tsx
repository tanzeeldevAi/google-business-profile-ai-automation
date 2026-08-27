"use client";

import { useEffect, useState } from "react";
import ActionPage, { Toggle } from "@/components/ActionPage";
import { useApp } from "@/components/Shell";
import { Card, Empty, Pill } from "@/components/ui";
import { api, Audit } from "@/lib/api";

const FIXERS = [
  ["description", "Business description", "Rewrites it to be compliant and complete, from the profile and the website only."],
  ["holiday_hours", "Holiday hours", "Adds the upcoming public holidays for this country."],
  ["services", "Services from search terms", "Turns the terms the profile never mentions into named services."],
] as const;

export default function FixPage() {
  const { active, running } = useApp();
  const [audit, setAudit] = useState<Audit | null>(null);
  const [only, setOnly] = useState<Record<string, boolean>>({
    description: true, holiday_hours: true, services: true,
  });

  useEffect(() => {
    if (!active) return;
    api.audit(active.location).then((r) => setAudit(r.audit)).catch(() => {});
  }, [active, running]);

  const chosen = FIXERS.map(([k]) => k).filter((k) => only[k]);
  const all = chosen.length === FIXERS.length;
  const pending = (audit?.findings || []).filter((f) => !f.passed && f.fixable);

  return (
    <ActionPage
      title="Fix what can be fixed"
      command="fix"
      writes
      options={all ? {} : { only: chosen.join(",") }}
      disabled={chosen.length === 0}
      disabledWhy={chosen.length === 0 ? "Pick at least one thing to fix." : undefined}
      lead={
        <>
          <p>
            Three things can be changed through the API. Everything else in the audit
            needs a person, either because Google gives no write access or because the
            honest answer is a judgement about the business.
          </p>
          <p>
            <strong className="text-ink">It never invents a fact.</strong> The
            description is built from what is already on the profile, the business&apos;s
            own website, and the facts you list in Settings. It will not claim a
            founding year, a certification or a price it was not given.
          </p>
        </>
      }
      controls={
        <div className="rounded-lg bg-panel-2 p-3.5">
          <div className="text-xs uppercase tracking-wider text-ink-3 mb-2.5">
            What to include
          </div>
          {FIXERS.map(([key, label, hint]) => (
            <Toggle
              key={key}
              label={label}
              hint={hint}
              checked={!!only[key]}
              onChange={(v) => setOnly((o) => ({ ...o, [key]: v }))}
            />
          ))}
        </div>
      }
    >
      <Card title={`Waiting to be fixed (${pending.length})`}>
        {pending.length === 0 ? (
          <Empty>
            {audit ? "Nothing the automatic fixers can help with." : "Run an audit first."}
          </Empty>
        ) : (
          <div className="space-y-2">
            {pending.map((f) => (
              <div key={f.rule_id} className="p-3 rounded-lg bg-panel-2">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm">{f.title}</span>
                  <Pill tone="good">auto</Pill>
                </div>
                <div className="text-xs text-ink-3">{f.detail}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Before anything is written">
        <ul className="text-sm text-ink-2 space-y-1.5 list-disc pl-5">
          <li>Preview shows the exact before and after for every change.</li>
          <li>
            Services are <strong className="text-ink">proposals</strong>. A search term
            proves people looked for something; it does not prove this business offers
            it. Read them before applying.
          </li>
          <li>Holiday hours default to closed. Check the ones you actually trade on.</li>
          <li>Each change writes a narrow update, so a description edit cannot blank the phone number.</li>
        </ul>
      </Card>
    </ActionPage>
  );
}
