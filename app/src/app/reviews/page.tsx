"use client";

import { useEffect, useState } from "react";
import ActionPage, { Toggle } from "@/components/ActionPage";
import { useApp } from "@/components/Shell";
import { Card, Empty, Pill } from "@/components/ui";
import { ago, api } from "@/lib/api";

export default function ReviewsPage() {
  const { active, running } = useApp();
  const [includeHeld, setIncludeHeld] = useState(false);
  const [replies, setReplies] = useState<
    { target: string; detail: string; dry_run: boolean; when: string }[]
  >([]);

  useEffect(() => {
    if (!active) return;
    api
      .activity(active.location)
      .then((r) => setReplies(r.actions.filter((a) => a.kind === "review_reply")))
      .catch(() => {});
  }, [active, running]);

  return (
    <ActionPage
      title="Reply to reviews"
      command="reviews"
      writes
      options={includeHeld ? { "include-held": true } : {}}
      lead={
        <>
          <p>
            Google says plainly that replying to reviews helps local ranking. It is the
            highest-value thing on the whole audit, it is free, and most competitors do
            not bother.
          </p>
          <p>
            Replies are written in the owner&apos;s voice from the profile and the
            business&apos;s own website. Anything that reads as machine-written is
            regenerated rather than sent.
          </p>
        </>
      }
      controls={
        <div className="rounded-lg bg-panel-2 p-3.5">
          <Toggle
            label="Also reply to low-star reviews"
            hint="Off by default. A one-star review is a conversation with an upset customer and usually deserves a human, not a generated reply."
            checked={includeHeld}
            onChange={setIncludeHeld}
          />
        </div>
      }
    >
      <Card title="How it stays safe">
        <ul className="text-sm text-ink-2 space-y-1.5 list-disc pl-5">
          <li>
            <strong className="text-ink">Low-star reviews are held for a human</strong>{" "}
            unless you turn that off above.
          </li>
          <li>A review already replied to is never replied to twice.</li>
          <li>Nothing is sent until you press Apply, and you see every draft first.</li>
        </ul>
      </Card>

      <Card title={`Replies sent (${replies.filter((r) => !r.dry_run).length})`}>
        {replies.length === 0 ? (
          <Empty>Nothing yet. Preview to see the drafts.</Empty>
        ) : (
          <div className="space-y-2">
            {replies.slice(0, 15).map((r, i) => (
              <div key={i} className="p-3 rounded-lg bg-panel-2">
                <div className="flex items-center gap-2 mb-1">
                  <Pill tone={r.dry_run ? "dim" : "good"}>
                    {r.dry_run ? "preview" : "sent"}
                  </Pill>
                  <span className="text-xs text-ink-3 ml-auto">{ago(r.when)}</span>
                </div>
                <p className="text-sm text-ink-2">{r.detail}</p>
              </div>
            ))}
          </div>
        )}
      </Card>
    </ActionPage>
  );
}
