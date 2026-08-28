"use client";

import { useEffect, useState } from "react";
import { Banner, Button, Card, Chip } from "@/components/ui";
import { api, PlannedFix } from "@/lib/api";

/**
 * One planned change: what it would do, edited, then written.
 *
 * The plan is a proposal, not an instruction. Before this existed the only way
 * to act on a fix was to accept every part of it at once, from a terminal log,
 * with no way to reword a sentence or strike out a service the business does
 * not actually offer. That is the wrong shape for a profile a real customer
 * reads: a service listed here is a promise, and a description is the business
 * talking. So the content arrives editable, and what gets written is whatever
 * is on screen when Apply is pressed -- not whatever the model first wrote.
 */
export default function FixEditor({
  location, fix, onApplied,
}: {
  location: string;
  fix: PlannedFix;
  onApplied: () => void;
}) {
  const listy = fix.proposed.length > 0;

  // Description-shaped fixes are edited as text; list-shaped ones by choosing
  // which entries survive.
  const [text, setText] = useState(fix.after);
  const [keep, setKeep] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setText(fix.after);
    setKeep(Object.fromEntries(fix.proposed.map((p) => [p.name, true])));
    setDone(false);
    setError("");
  }, [fix]);

  const dropped = fix.proposed.filter((p) => !keep[p.name]).length;

  /**
   * Rebuild the payload from what is on screen.
   *
   * For a list fix the body holds every service, existing ones included, so
   * the edit is a filter over it rather than a rewrite -- dropping a proposed
   * service must never drop a service the business already had.
   */
  const buildBody = (): Record<string, unknown> => {
    if (!listy) {
      if (fix.key === "description") return { profile: { description: text } };
      return fix.body;
    }
    const removed = new Set(fix.proposed.filter((p) => !keep[p.name])
                                        .map((p) => p.name));
    const items = (fix.body.serviceItems as Record<string, unknown>[]) || [];
    return {
      ...fix.body,
      serviceItems: items.filter((it) => {
        const label = ((it.freeFormServiceItem as Record<string, unknown>)
          ?.label as Record<string, unknown>) || {};
        return !removed.has(String(label.displayName ?? ""));
      }),
    };
  };

  // A plan saved before the payload was carried through has nothing to send.
  // Re-running the preview regenerates it; pretending otherwise would show an
  // Apply button that could only fail.
  const applyable = fix.update_mask !== "" && Object.keys(fix.body).length > 0;

  const apply = async () => {
    setBusy(true);
    setError("");
    try {
      await api.applyFix(location, fix.key, buildBody());
      setDone(true);
      onApplied();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const changed = listy ? dropped > 0 : text !== fix.after;

  return (
    <Card
      title={fix.title}
      right={<Chip tone={done ? "green" : "neutral"}>{done ? "written" : fix.key}</Chip>}
    >
      {listy ? (
        <>
          <Banner tone="yellow" title={`${fix.proposed.length} proposed`}>
            A search term proves people looked for something. It does not prove this
            business offers it. Untick anything they do not actually do — a service on
            a profile is a promise.
          </Banner>
          <div className="mt-3 space-y-2">
            {fix.proposed.map((s) => (
              <label
                key={s.name}
                className={`flex cursor-pointer gap-3 rounded-g border p-3 transition-colors
                  ${keep[s.name] ? "border-g-grey300" : "border-g-grey200 opacity-50"}`}
              >
                <input
                  type="checkbox"
                  checked={!!keep[s.name]}
                  onChange={(e) =>
                    setKeep((k) => ({ ...k, [s.name]: e.target.checked }))}
                  className="mt-0.5 h-4 w-4 shrink-0 accent-g-blue"
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-g-grey900">{s.name}</span>
                  <span className="mt-1 block text-[13px] leading-relaxed text-g-grey700">
                    {s.description}
                  </span>
                  {s.terms.length > 0 && (
                    <span className="mt-2 flex flex-wrap gap-1">
                      {s.terms.map((t) => (
                        <span key={t} className="rounded-pill bg-g-grey100 px-2 py-0.5
                          text-[11px] text-g-grey600">{t}</span>
                      ))}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>
        </>
      ) : (
        <>
          <div className="mb-3">
            <div className="text-xs uppercase tracking-wider text-g-grey600">Now</div>
            <p className="mt-1 whitespace-pre-wrap rounded-g bg-g-grey50 p-3
              text-[13px] leading-relaxed text-g-grey600">
              {fix.before || "(empty)"}
            </p>
          </div>
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs uppercase tracking-wider text-g-grey600">
                After — edit this before writing it
              </span>
              <span className="text-[11px] tabular-nums text-g-grey600">
                {text.length} characters
              </span>
            </div>
            <textarea
              rows={8}
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="mt-1 w-full resize-y rounded-g border border-g-grey300 bg-white
                p-3 text-[13px] leading-relaxed outline-none focus:border-g-blue"
            />
          </div>
        </>
      )}

      {fix.notes.length > 0 && (
        <ul className="mt-3 space-y-0.5">
          {fix.notes.map((n, i) => (
            <li key={i} className="text-[12.5px] text-g-grey600">{n.trim()}</li>
          ))}
        </ul>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button kind="filled" onClick={apply} disabled={busy || done || !applyable}>
          {busy ? "Writing…" : done ? "Written to the profile" : "Apply to the profile"}
        </Button>
        {!applyable && !done && (
          <span className="text-[12.5px] text-g-grey600">
            This preview was made before edit-and-apply existed. Run the preview
            again to enable it.
          </span>
        )}
        {changed && !done && (
          <span className="text-[12.5px] text-g-grey600">
            {listy ? `${dropped} removed from the proposal` : "edited"}
          </span>
        )}
        {done && (
          <span className="text-[12.5px] text-g-green">
            Google can take a few minutes to show it.
          </span>
        )}
        {error && <span className="text-[12.5px] text-g-red">{error}</span>}
      </div>
    </Card>
  );
}
