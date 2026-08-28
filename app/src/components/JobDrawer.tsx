"use client";

import { useEffect, useRef, useState } from "react";
import { api, Job } from "@/lib/api";
import { Button, Progress } from "@/components/ui";

/**
 * The running command, pinned to the bottom of every screen.
 *
 * Output arrives over server-sent events rather than polling, so a long run
 * shows progress as it happens instead of sitting blank. It falls back to
 * polling if the stream cannot open -- a dashboard that goes silent looks
 * broken even when the job is fine.
 *
 * Two things this has been caught out by, both worth keeping in mind:
 *
 *   1. It was written against the old dark palette. When the app moved to
 *      Google's colours the tokens it used (bg-panel, border-line, text-ink)
 *      stopped existing, so Tailwind emitted nothing for them and the whole
 *      drawer rendered transparent and borderless. It was on the page the
 *      whole time, invisible, which read as "I clicked Preview and nothing
 *      happened". Every colour here now comes from the shared g-* palette.
 *
 *   2. `fix` genuinely takes three minutes -- it writes a description and a
 *      paragraph for each proposed service. A spinner alone is not enough
 *      feedback for that long, so the header carries elapsed time and a live
 *      line count, and the log stays open while it runs.
 */
export default function JobDrawer({
  jobId, onDone,
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
  const dot = job.running
    ? "bg-g-yellow animate-pulse"
    : good ? "bg-g-green" : "bg-g-red";

  return (
    <div className="sticky bottom-0 z-30 border-t border-g-grey300 bg-white shadow-e2">
      {job.running && <Progress />}
      <div className="max-w-[1400px] mx-auto px-5">
        <div className="flex items-center gap-3 py-2.5 text-sm">
          <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
          <span className="font-medium text-g-grey900">
            {job.running ? `Running ${job.command}…`
              : good ? `${job.command} finished`
              : `${job.command} stopped — exit ${job.exit_code}`}
          </span>
          <code className="hidden text-xs text-g-grey600 sm:inline">
            run.py {job.argv.join(" ")}
          </code>

          <span className="ml-auto flex items-center gap-3 text-xs tabular-nums text-g-grey600">
            {job.running && job.elapsed > 20 && (
              <span className="hidden sm:inline">
                this one usually takes a few minutes
              </span>
            )}
            <span>{job.total} lines</span>
            <span>{job.elapsed}s</span>
          </span>

          {job.running && (
            <Button kind="danger" onClick={() => api.stop()}>Stop</Button>
          )}
          <Button kind="text" onClick={() => setOpen((v) => !v)}>
            {open ? "Hide" : "Show"}
          </Button>
        </div>

        {open && (
          <div
            ref={logRef}
            className="scroll-slim max-h-72 overflow-auto rounded-t-g border border-b-0
              border-g-grey300 bg-g-grey50 p-3 font-mono text-[12.5px] leading-relaxed"
          >
            {/* `logline` supplies whitespace-pre-wrap. The fix output
                indents proposed services, and HTML collapses the indent
                without it. */}
            {job.lines.map((line, i) => (
              <div key={i} className={`logline ${colour(line)}`}>
                {line || " "}
              </div>
            ))}
            {job.running && (
              <div className="text-g-grey500">
                <span className="inline-block animate-pulse">▊</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/** Colour a log line by what it is saying, on the light surface. */
function colour(line: string): string {
  if (/^\s*(x |!|Traceback)|FAIL|error|refus|could not|failed/i.test(line))
    return "text-g-red";
  if (/DRY RUN|WILL NOT PUBLISH|NOTE:|not checked|skipped/i.test(line))
    return "text-[#b06000]";
  if (/^\s*\+|Ready\.|posted\.|passed|finished/i.test(line))
    return "text-g-green";
  if (/^\s*[-=#]|^\s{2}\w+ \.+/.test(line)) return "text-g-grey500";
  return "text-g-grey700";
}
