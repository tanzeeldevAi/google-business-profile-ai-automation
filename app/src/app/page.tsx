"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useApp } from "@/components/Shell";
import { Button, Card, Chip, Dial, Empty, SEVERITY_TONE, Spark } from "@/components/ui";
import { ago, api, Audit } from "@/lib/api";

export default function Overview() {
  const { active, status, run, running } = useApp();
  const [audit, setAudit] = useState<Audit | null>(null);
  const [alerts, setAlerts] = useState<{ severity: string; message: string }[]>([]);
  const [reports, setReports] = useState<{ name: string; when: string }[]>([]);

  useEffect(() => {
    if (!active) return;
    api.audit(active.location).then((r) => setAudit(r.audit)).catch(() => {});
    api.alerts(active.location).then((r) => setAlerts(r.alerts)).catch(() => {});
    api.reports().then((r) => setReports(r.reports)).catch(() => {});
  }, [active, running]);

  if (!active) return <Empty>Pick a business from the menu at the top.</Empty>;

  const failures = (audit?.findings || []).filter((f) => !f.passed && !f.informational);
  const auto = failures.filter((f) => f.fixable);
  const delta = audit?.previous != null ? audit.score - audit.previous : null;

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div className="lg:col-span-2 space-y-5">
        <Card title="Where this profile stands">
          {audit ? (
            <div className="flex items-center gap-5 flex-wrap">
              <Dial score={audit.score} />
              <div>
                <div className="text-xl font-semibold">{audit.grade}</div>
                <div className="text-sm text-g-grey700">
                  {failures.length} issue{failures.length === 1 ? "" : "s"}
                  {delta != null && delta !== 0 && (
                    <> · <span className={delta > 0 ? "text-g-green" : "text-g-red"}>
                      {delta > 0 ? "up" : "down"} {Math.abs(delta)}
                    </span> since last time</>
                  )}
                </div>
                <div className="text-xs text-g-grey600 mt-1">Checked {ago(audit.when)}</div>
              </div>
              <div className="ml-auto w-40"><Spark points={active.history} /></div>
            </div>
          ) : (
            <Empty>No audit yet. Run one to get a score.</Empty>
          )}
          <div className="flex gap-2 flex-wrap mt-5">
            <Button kind="filled" disabled={running} onClick={() => run("audit")}>
              Run an audit
            </Button>
            <Link href="/fix"><Button disabled={running}>Review the fixes</Button></Link>
            <Button disabled={running} onClick={() => run("watch")}>What changed</Button>
          </div>
        </Card>

        <Card title={`What to fix (${failures.length})`}
              right={<Link href="/audit" className="text-xs text-g-blue">See all →</Link>}>
          {failures.length === 0 ? (
            <Empty>{audit ? "Nothing failed on this profile." : "Run an audit first."}</Empty>
          ) : (
            <div className="space-y-2">
              {failures.slice(0, 6).map((f) => (
                <div key={f.rule_id} className="flex gap-3 items-start p-3 rounded-lg bg-g-grey100">
                  <Chip tone={SEVERITY_TONE[f.severity]}>{f.severity}</Chip>
                  <div className="min-w-0">
                    <div className="font-medium text-sm">{f.title}</div>
                    <div className="text-xs text-g-grey600">{f.detail}</div>
                  </div>
                  {f.fixable && <span className="ml-auto shrink-0"><Chip tone="green">auto</Chip></span>}
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="space-y-5">
        <Card title="Autopilot">
          <p className="text-sm text-g-grey700 mb-3">
            One run that checks what changed, re-scores, and answers any new reviews.
          </p>
          <div className="flex flex-col gap-2">
            <Button disabled={running} onClick={() => run("daily")}>
              Preview the daily run
            </Button>
            <Button kind="danger" disabled={running}
                    onClick={() => confirm(`Publish to ${active.title}?`) && run("daily", {}, true)}>
              Run it for real
            </Button>
          </div>
          <p className="text-xs text-g-grey600 mt-3">
            {auto.length} of the current issues can be fixed automatically.
          </p>
        </Card>

        {alerts.length > 0 && (
          <Card title={`Alerts (${alerts.length})`}
                right={<button className="text-xs text-g-blue"
                               onClick={() => api.ackAlerts(active.location).then(() => setAlerts([]))}>
                        Mark seen</button>}>
            <div className="space-y-2">
              {alerts.map((a, i) => (
                <div key={i} className="text-sm p-2.5 rounded-lg bg-g-redLight border border-g-red/30 text-g-red">
                  {a.message}
                </div>
              ))}
            </div>
          </Card>
        )}

        <Card title="Set-up">
          <ul className="text-sm space-y-2">
            <Row ok={status?.google.signed_in} label="Google connected" />
            <Row ok={status?.llm.ready} label={`Writing via ${status?.llm.backend}`} />
            <Row ok={status?.dataforseo} label="DataForSEO (competitors, citations)"
                 hint="optional" />
            <Row ok={status?.images !== "none"} label="Post images" hint="optional" />
          </ul>
        </Card>

        <Card title="Reports">
          {reports.length === 0 ? <Empty>None yet.</Empty> : (
            <ul className="text-sm space-y-1.5">
              {reports.slice(0, 5).map((r) => (
                <li key={r.name}>
                  <a href={api.reportUrl(r.name)} target="_blank" rel="noreferrer"
                     className="text-g-blue hover:underline break-all">{r.name}</a>
                  <span className="text-g-grey600 text-xs"> · {ago(r.when)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function Row({ ok, label, hint }: { ok?: boolean; label: string; hint?: string }) {
  return (
    <li className="flex items-center gap-2">
      <span className={`w-2 h-2 rounded-full ${ok ? "bg-g-green" : hint ? "bg-g-grey600" : "bg-g-red"}`} />
      <span className={ok ? "" : "text-g-grey700"}>{label}</span>
      {!ok && hint && <span className="text-xs text-g-grey600 ml-auto">{hint}</span>}
    </li>
  );
}
