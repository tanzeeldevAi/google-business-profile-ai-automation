"use client";

import { useEffect, useState } from "react";
import ActionPage, { Toggle } from "@/components/ActionPage";
import { useApp } from "@/components/Shell";
import { Card, Empty, Chip, Banner } from "@/components/ui";
import { ago, api, Audit, FixPlan } from "@/lib/api";

const FIXERS = [
  ["description", "Business description", "Rewrites it to be compliant and complete, from the profile and the website only."],
  ["holiday_hours", "Holiday hours", "Adds the upcoming public holidays for this country."],
  ["services", "Services from search terms", "Turns the terms the profile never mentions into named services."],
] as const;

export default function FixPage() {
  const { active, running } = useApp();
  const [audit, setAudit] = useState<Audit | null>(null);
  const [plan, setPlan] = useState<FixPlan | null>(null);
  const [only, setOnly] = useState<Record<string, boolean>>({
    description: true, holiday_hours: true, services: true,
  });

  useEffect(() => {
    if (!active) return;
    api.audit(active.location).then((r) => setAudit(r.audit)).catch(() => {});
    // Reloads when a job finishes, so a preview's result appears here by
    // itself rather than needing the log to be read.
    api.fixPlan(active.location).then((r) => setPlan(r.plan)).catch(() => {});
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
            <strong className="text-g-grey900">It never invents a fact.</strong> The
            description is built from what is already on the profile, the business&apos;s
            own website, and the facts you list in Settings. It will not claim a
            founding year, a certification or a price it was not given.
          </p>
        </>
      }
      controls={
        <div className="rounded-lg bg-g-grey100 p-3.5">
          <div className="text-xs uppercase tracking-wider text-g-grey600 mb-2.5">
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
      {plan && plan.fixes.length > 0 && (
        <Card
          title="What the preview would change"
          subtitle={`Previewed ${ago(new Date(plan.planned_at * 1000).toISOString())}.`
                + " Nothing has been written."}
        >
          <div className="space-y-5">
            {plan.fixes.map((f) => (
              <div key={f.key}>
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-sm font-medium text-g-grey900">{f.title}</span>
                  <Chip>{f.key}</Chip>
                </div>

                {f.proposed.length > 0 ? (
                  <>
                    <Banner tone="yellow" title={`${f.proposed.length} services would be added`}>
                      A search term proves people looked for something. It does not prove
                      this business offers it. Read each one — a service on a profile is
                      a promise.
                    </Banner>
                    <div className="mt-3 space-y-2">
                      {f.proposed.map((s, i) => (
                        <div key={i} className="rounded-g border border-g-grey300 p-3">
                          <div className="text-sm font-medium text-g-grey900">{s.name}</div>
                          <p className="mt-1 text-[13px] leading-relaxed text-g-grey700">
                            {s.description}
                          </p>
                          <div className="mt-2 flex flex-wrap gap-1">
                            {s.terms.map((term) => (
                              <span
                                key={term}
                                className="rounded-pill bg-g-grey100 px-2 py-0.5
                                  text-[11px] text-g-grey600"
                              >
                                {term}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="grid gap-3 md:grid-cols-2">
                    <BeforeAfter label="Now" text={f.before} tone="before" />
                    <BeforeAfter label="After" text={f.after} tone="after" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title={`Waiting to be fixed (${pending.length})`}>
        {pending.length === 0 ? (
          <Empty>
            {audit ? "Nothing the automatic fixers can help with." : "Run an audit first."}
          </Empty>
        ) : (
          <div className="space-y-2">
            {pending.map((f) => (
              <div key={f.rule_id} className="p-3 rounded-lg bg-g-grey100">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-medium text-sm">{f.title}</span>
                  <Chip tone="green">auto</Chip>
                </div>
                <div className="text-xs text-g-grey600">{f.detail}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Before anything is written">
        <ul className="text-sm text-g-grey700 space-y-1.5 list-disc pl-5">
          <li>Preview shows the exact before and after for every change.</li>
          <li>
            Services are <strong className="text-g-grey900">proposals</strong>. A search term
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


/** One side of a change, so the difference can be read at a glance. */
function BeforeAfter({ label, text, tone }: {
  label: string; text: string; tone: "before" | "after";
}) {
  return (
    <div
      className={`rounded-g border p-3 ${
        tone === "after"
          ? "border-g-green/40 bg-g-greenLight/40"
          : "border-g-grey300 bg-g-grey50"
      }`}
    >
      <div className="mb-1.5 text-[11px] uppercase tracking-wider text-g-grey600">
        {label}
      </div>
      <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-g-grey900">
        {text || "(empty)"}
      </p>
    </div>
  );
}
