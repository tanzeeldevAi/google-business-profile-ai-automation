"use client";

import { useEffect, useRef, useState } from "react";
import { api, Job } from "@/lib/api";

/**
 * The running command, pinned to the bottom of every screen.
 *
 * Output arrives over server-sent events rather than polling, so a long audit
 * shows progress as it happens instead of sitting blank for a minute. It falls
 * back to polling if the stream cannot open -- a dashboard that goes silent
 * looks broken even when the job is fine.
 */
export default function JobDrawer({
  jobId, running, onDone,
}: {
  jobId: string | null;
  running: boolean;
  onDone: () => void;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [open, setOpen] = useState(true);
  const logRef = useRef<HTMLDivElement>(null);
  const doneRef = useRef(false);

  // `onDone` is an inline arrow in the parent, so it is a NEW function on every
  // render. Depending on it directly made this effect tear down the event
  // stream and re-open it from line zero on every render -- an infinite
  // subscribe loop that duplicated the log and made the drawer flicker. Hold it
  // in a ref and depend only on the job id, which is what actually changes.
  const onDoneRef = useRef(onDone);
  useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  useEffect(() => {
    if (!jobId) return;
    doneRef.current = false;
    setOpen(true);
    setJob(null);

    let sent = 0;
    let poll: ReturnType<typeof setInterval> | null = null;

    const finish = (j: Job) => {
      if (doneRef.current) return;
      doneRef.current = true;
      setJob(j);
      onDoneRef.current();
    };

    const source = new EventSource(api.streamUrl(jobId));
    source.onmessage = (event) => {
      const snap: Job = JSON.parse(event.data);
      sent = snap.total;
      setJob((prev) =>
        prev ? { ...snap, lines: [...prev.lines, ...snap.lines] } : snap,
      );
      if (!snap.running) { source.close(); finish(snap); }
    };
    source.onerror = () => {
      // Streaming failed (a proxy that buffers, a dropped connection). Poll
      // instead rather than leaving the user staring at nothing.
      source.close();
      if (poll) return;
      poll = setInterval(async () => {
        try {
          const snap = await api.job(jobId, sent);
          sent = snap.total;
          setJob((prev) =>
            prev ? { ...snap, lines: [...prev.lines, ...snap.lines] } : snap,
          );
          if (!snap.running) { clearInterval(poll!); poll = null; finish(snap); }
        } catch { /* keep trying; the job may still be alive */ }
      }, 900);
    };

    return () => { source.close(); if (poll) clearInterval(poll); };
  }, [jobId]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [job?.lines.length]);

  if (!jobId || !job) return null;

  const good = job.exit_code === 0;
  const dot = job.running ? "bg-warn animate-pulse" : good ? "bg-good" : "bg-bad";

  return (
    <div className="sticky bottom-0 z-30 border-t border-line bg-panel">
      <div className="max-w-[1400px] mx-auto px-5">
        <div className="flex items-center gap-3 py-2 text-sm">
          <span className={`w-2.5 h-2.5 rounded-full ${dot}`} />
          <span className="font-medium">
            {job.running ? `Running ${job.command}…`
              : good ? `${job.command} finished` : `${job.command} exited ${job.exit_code}`}
          </span>
          <code className="text-xs text-ink-3 hidden sm:inline">
            run.py {job.argv.join(" ")}
          </code>
          <span className="ml-auto text-xs text-ink-3 tabular-nums">{job.elapsed}s</span>
          {job.running && (
            <button
              onClick={() => api.stop()}
              className="text-xs px-2 py-1 rounded border border-bad/50 text-bad hover:bg-bad/10"
            >
              Stop
            </button>
          )}
          <button
            onClick={() => setOpen((v) => !v)}
            className="text-xs px-2 py-1 rounded border border-line text-ink-2 hover:text-ink"
          >
            {open ? "Hide" : "Show"}
          </button>
        </div>

        {open && (
          <div
            ref={logRef}
            className="max-h-72 overflow-auto rounded-t-lg bg-[#0B0D11] border border-line border-b-0 p-3 font-mono text-[12.5px] leading-relaxed"
          >
            {job.lines.map((line, i) => (
              <div key={i} className={`logline ${colour(line)}`}>{line || "\u00a0"}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function colour(line: string): string {
  if (/^\s*(x |!|Traceback)|FAIL|error|refus|could not|failed/i.test(line)) return "text-bad";
  if (/DRY RUN|WILL NOT PUBLISH|NOTE:|not checked|skipped/i.test(line)) return "text-warn";
  if (/^\s*\+|Ready\.|posted\.|passed|finished/i.test(line)) return "text-good";
  if (/^\s*[-=#]|^\s{2}\w+ \.+/.test(line)) return "text-ink-3";
  return "text-ink-2";
}
