"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/Shell";
import {
  Banner, Button, Card, Chip, Empty, Progress, Skeleton, TextField,
} from "@/components/ui";
import { ago, api, Review } from "@/lib/api";

type Filter = "unanswered" | "all" | "low" | "answered";

/**
 * The review inbox.
 *
 * Not a "run the reviews command" button: a list you work through. Read the
 * review, generate a reply, EDIT it, send it. The editing step is the point --
 * a reply that goes out unread is how a business ends up publicly thanking
 * someone for a one-star complaint.
 */
export default function ReviewsPage() {
  const { active, can, blockedReason } = useApp();
  const [data, setData] = useState<{
    reviews: Review[]; average: number | null; total: number;
    unanswered: number; blocked: string | null;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("unanswered");
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    if (!active) return;
    setLoading(true);
    try {
      setData(await api.reviews(active.location));
    } catch (e) {
      setData({ reviews: [], average: null, total: 0, unanswered: 0,
                blocked: e instanceof Error ? e.message : String(e) });
    } finally {
      setLoading(false);
    }
  }, [active]);

  useEffect(() => { load(); }, [load]);

  const shown = useMemo(() => {
    const all = data?.reviews || [];
    if (filter === "all") return all;
    if (filter === "answered") return all.filter((r) => r.reply);
    if (filter === "low") return all.filter((r) => r.stars && r.stars <= 3);
    return all.filter((r) => !r.reply);
  }, [data, filter]);

  if (!active) return <Empty>Pick a business first.</Empty>;

  const blocked = blockedReason("reviews");
  if (blocked || data?.blocked) {
    return (
      <div className="max-w-3xl space-y-4">
        <Banner
          tone="red"
          title="Reviews are switched off for this Google project"
          action={<Link href="/setup"><Button kind="filled">Open Setup</Button></Link>}
        >
          {blocked?.reason || data?.blocked}
          <span className="mt-1 block">
            Reviews, Posts and Photos all come from the same Google API. Enabling
            it once turns on all three.
          </span>
        </Banner>
        <Card title="What you will be able to do here">
          <ul className="space-y-2 text-sm text-g-grey700 list-disc pl-5">
            <li>See every review, newest first, with the ones you have not answered on top.</li>
            <li>Generate a reply in the owner&apos;s voice, then <strong>edit it before it goes out</strong>.</li>
            <li>Low-star reviews are flagged and never auto-sent.</li>
            <li>Filter to unanswered, low-star, or answered.</li>
          </ul>
        </Card>
      </div>
    );
  }

  const draft = async (r: Review) => {
    setBusy((b) => ({ ...b, [r.name]: "drafting" }));
    setNotes((n) => ({ ...n, [r.name]: "" }));
    try {
      const res = await api.draftReply(active.location, r.name);
      setDrafts((d) => ({ ...d, [r.name]: res.draft }));
      if (res.held) setNotes((n) => ({ ...n, [r.name]: res.why }));
    } catch (e) {
      setNotes((n) => ({ ...n, [r.name]: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy((b) => ({ ...b, [r.name]: "" }));
    }
  };

  const send = async (r: Review) => {
    const text = (drafts[r.name] || "").trim();
    if (!text) return;
    if (!confirm(`Publish this reply publicly on ${active.title}?\n\n${text}`)) return;
    setBusy((b) => ({ ...b, [r.name]: "sending" }));
    try {
      await api.replyToReview(active.location, r.name, text);
      setDrafts((d) => { const c = { ...d }; delete c[r.name]; return c; });
      await load();
    } catch (e) {
      setNotes((n) => ({ ...n, [r.name]: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy((b) => ({ ...b, [r.name]: "" }));
    }
  };

  return (
    <div className="max-w-4xl space-y-4">
      <Card title="Reviews" subtitle={
        data ? `${data.total} total · ${data.unanswered} waiting for a reply` : undefined
      }>
        <div className="flex items-center gap-6 flex-wrap">
          <div className="flex items-baseline gap-2">
            <span className="font-sans text-4xl text-g-grey900">
              {data?.average?.toFixed(1) ?? "—"}
            </span>
            <Stars value={Math.round(data?.average ?? 0)} />
          </div>
          <div className="text-sm text-g-grey600">
            Replying to reviews is the highest-value thing on this whole tool.
            Google says plainly that it helps local ranking, and most competitors
            never bother.
          </div>
        </div>

        <div className="mt-5 flex gap-2 flex-wrap">
          {([
            ["unanswered", `Waiting (${data?.unanswered ?? 0})`],
            ["low", "Low star"],
            ["answered", "Answered"],
            ["all", `All (${data?.total ?? 0})`],
          ] as [Filter, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`rounded-pill border px-4 h-8 text-[13px] transition-colors duration-150
                ${filter === key
                  ? "bg-g-blueLight border-g-blue text-g-blue font-medium"
                  : "bg-white border-g-grey300 text-g-grey700 hover:bg-g-grey50"}`}
            >
              {label}
            </button>
          ))}
          <Button kind="text" onClick={load} className="ml-auto">Refresh</Button>
        </div>
      </Card>

      {loading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-32 rounded-g" />)}
        </div>
      ) : shown.length === 0 ? (
        <Card><Empty icon="★">
          {filter === "unanswered"
            ? "Every review has a reply. That is exactly where you want to be."
            : "Nothing here."}
        </Empty></Card>
      ) : (
        <div className="space-y-3">
          {shown.map((r) => (
            <Card key={r.name} className="!p-0" pad={false}>
              <div className="flex items-start gap-3">
                <Avatar name={r.reviewer} photo={r.photo} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-g-grey900">{r.reviewer}</span>
                    <Stars value={r.stars} size={14} />
                    <span className="text-[12px] text-g-grey600">
                      {r.when ? ago(r.when) : ""}
                    </span>
                    {!r.reply && <Chip tone="yellow">needs a reply</Chip>}
                    {r.stars > 0 && r.stars <= 3 && <Chip tone="red">low star</Chip>}
                  </div>

                  <p className="mt-2 text-sm text-g-grey700 whitespace-pre-wrap">
                    {r.comment || <span className="italic text-g-grey500">
                      Rating only, no words.
                    </span>}
                  </p>

                  {r.reply && (
                    <div className="mt-3 rounded-g bg-g-grey50 border-l-2 border-g-blue px-3 py-2">
                      <p className="text-[12px] font-medium text-g-grey600 mb-0.5">
                        Your reply {r.replied_when ? `· ${ago(r.replied_when)}` : ""}
                      </p>
                      <p className="text-[13px] text-g-grey700 whitespace-pre-wrap">{r.reply}</p>
                    </div>
                  )}

                  {!r.reply && (
                    <div className="mt-3">
                      {busy[r.name] === "drafting" && (
                        <div className="mb-2"><Progress /></div>
                      )}

                      {drafts[r.name] !== undefined ? (
                        <>
                          {notes[r.name] && (
                            <p className="mb-2 rounded-g bg-g-yellowLight px-3 py-2 text-[12.5px] text-[#b06000]">
                              {notes[r.name]}
                            </p>
                          )}
                          <TextField
                            multiline
                            rows={4}
                            value={drafts[r.name]}
                            onChange={(v) => setDrafts((d) => ({ ...d, [r.name]: v }))}
                            hint="Edit this before it goes out. It publishes publicly under the business name."
                          />
                          <div className="flex gap-2">
                            <Button
                              kind="filled"
                              disabled={busy[r.name] === "sending" || !drafts[r.name].trim()}
                              onClick={() => send(r)}
                            >
                              {busy[r.name] === "sending" ? "Publishing…" : "Publish reply"}
                            </Button>
                            <Button kind="text" onClick={() => draft(r)}>Rewrite</Button>
                            <Button
                              kind="text"
                              onClick={() => setDrafts((d) => {
                                const c = { ...d }; delete c[r.name]; return c;
                              })}
                            >
                              Discard
                            </Button>
                          </div>
                        </>
                      ) : (
                        <div className="flex items-center gap-2">
                          <Button
                            kind="tonal"
                            disabled={!!busy[r.name] || !can("reviews")}
                            onClick={() => draft(r)}
                          >
                            {busy[r.name] === "drafting" ? "Writing…" : "Write a reply"}
                          </Button>
                          {notes[r.name] && (
                            <span className="text-[12.5px] text-g-red">{notes[r.name]}</span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Avatar({ name, photo }: { name: string; photo: string }) {
  if (photo) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={photo} alt="" className="h-10 w-10 shrink-0 rounded-full object-cover" />;
  }
  return (
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full
      bg-g-blueLight text-sm font-medium text-g-blue">
      {(name || "?")[0].toUpperCase()}
    </span>
  );
}

function Stars({ value, size = 16 }: { value: number; size?: number }) {
  return (
    <span className="inline-flex gap-0.5" aria-label={`${value} of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <svg key={i} width={size} height={size} viewBox="0 0 24 24"
             className={i <= value ? "fill-[#fbbc04]" : "fill-g-grey300"}>
          <path d="M12 17.27 18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z" />
        </svg>
      ))}
    </span>
  );
}
