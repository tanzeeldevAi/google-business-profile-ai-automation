"use client";

import { useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/Shell";
import { Button, Card, Dial, Empty, Pill } from "@/components/ui";
import {
  ago, api, Audit, CATEGORY_LABELS, Finding, SEVERITY_ORDER, SEVERITY_STYLE,
} from "@/lib/api";

export default function AuditPage() {
  const { active, run, running } = useApp();
  const [audit, setAudit] = useState<Audit | null>(null);
  const [tab, setTab] = useState<"issues" | "passed" | "skipped">("issues");

  useEffect(() => {
    if (!active) return;
    api.audit(active.location).then((r) => setAudit(r.audit)).catch(() => {});
  }, [active, running]);

  const groups = useMemo(() => {
    const f = audit?.findings || [];
    return {
      issues: f
        .filter((x) => !x.passed && !x.informational)
        .sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]),
      passed: f.filter((x) => x.passed && !x.informational),
      skipped: f.filter((x) => x.informational),
    };
  }, [audit]);

  if (!active) return <Empty>Pick a business first.</Empty>;

  return (
    <div className="space-y-5">
      <Card title="Audit">
        <div className="flex items-center gap-5 flex-wrap">
          {audit && <Dial score={audit.score} />}
          <div>
            <div className="text-xl font-semibold">{audit?.grade || "Not audited yet"}</div>
            {audit && (
              <div className="text-sm text-ink-2">
                {groups.issues.length} issues · {groups.passed.length} already correct ·{" "}
                {groups.skipped.length} not checked · {ago(audit.when)}
              </div>
            )}
          </div>
          <div className="ml-auto">
            <Button kind="primary" disabled={running} onClick={() => run("audit")}>
              Re-run the audit
            </Button>
          </div>
        </div>
      </Card>

      <div className="flex gap-2 flex-wrap">
        {(["issues", "passed", "skipped"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-3 py-1.5 rounded-lg text-sm border transition ${
              tab === t ? "bg-panel-2 border-accent" : "border-line text-ink-2 hover:text-ink"
            }`}
          >
            {t === "issues"
              ? `To fix (${groups.issues.length})`
              : t === "passed"
              ? `Already correct (${groups.passed.length})`
              : `Not checked (${groups.skipped.length})`}
          </button>
        ))}
      </div>

      {tab === "issues" &&
        (groups.issues.length === 0 ? (
          <Empty>{audit ? "Nothing failed on this profile." : "Run an audit to see findings."}</Empty>
        ) : (
          <div className="space-y-3">
            {groups.issues.map((f) => (
              <FindingCard key={f.rule_id} f={f} />
            ))}
          </div>
        ))}

      {tab === "passed" && (
        <Card>
          <ul className="grid sm:grid-cols-2 gap-x-8 gap-y-1.5 text-sm text-ink-2">
            {groups.passed.map((f) => (
              <li key={f.rule_id} className="flex gap-2">
                <span className="text-good shrink-0">✓</span>
                {f.title}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {tab === "skipped" && (
        <Card>
          <p className="text-sm text-ink-3 mb-3">
            These were not counted against the score. A section that could not be read
            is never reported as a failure.
          </p>
          <ul className="text-sm space-y-1.5">
            {groups.skipped.map((f) => (
              <li key={f.rule_id}>
                <span className="text-ink">{f.title}</span>
                <span className="text-ink-3"> — {f.detail}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function FindingCard({ f }: { f: Finding }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-4">
      <div className="flex items-center gap-2.5 flex-wrap mb-2">
        <span
          className={`text-[10.5px] uppercase tracking-wider px-2 py-0.5 rounded border ${SEVERITY_STYLE[f.severity]}`}
        >
          {f.severity}
        </span>
        <h3 className="font-semibold">{f.title}</h3>
        {f.fixable && <Pill tone="good">automated</Pill>}
        <span className="ml-auto text-xs text-ink-3">
          {CATEGORY_LABELS[f.category] || f.category}
        </span>
      </div>
      <p className="text-sm font-medium mb-2">{f.detail}</p>
      <p className="text-sm text-ink-2 mb-1.5">
        <strong className="text-ink">Why it matters.</strong> {f.why}
      </p>
      <p className="text-sm text-ink-2">
        <strong className="text-ink">What to do.</strong> {f.fix}
      </p>
      {f.command && (
        <p className="text-xs text-ink-3 mt-2">
          Handled by <code>{f.command}</code>
        </p>
      )}
    </div>
  );
}
