"use client";

import { useEffect, useState } from "react";
import ActionPage, { Field } from "@/components/ActionPage";
import { useApp } from "@/components/Shell";
import { Banner, Button, Card, Chip, Empty, Skeleton } from "@/components/ui";
import { api, CategoryRef, ProfileDetails } from "@/lib/api";

/**
 * The facts only a person knows: where the business is, what it is, how to
 * reach it.
 *
 * The audit and the fixers handle what can be judged automatically. None of
 * them can know that a clinic moved from the third floor to the second, so
 * until this screen existed the answer to "the client moved" was "log into
 * Google and do it by hand", which is not what the tool is for.
 *
 * Everything here previews before it writes, because these are the fields a
 * customer actually navigates by.
 */
export default function ProfilePage() {
  const { active, running } = useApp();
  const [now, setNow] = useState<ProfileDetails | null>(null);
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [website, setWebsite] = useState("");
  const [extra, setExtra] = useState<CategoryRef[] | null>(null);
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<CategoryRef[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState("");

  useEffect(() => {
    if (!active) return;
    api.details(active.location)
      .then((d) => { setNow(d); setExtra(d.additional); })
      .catch(() => setNow(null));
  }, [active, running]);

  if (!active) return <Empty>Pick a business first.</Empty>;

  const search = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const r = await api.searchCategories(query);
      setFound(r.categories);
      setSearched(query);
    } catch {
      setFound([]);
      setSearched(query);
    } finally {
      setSearching(false);
    }
  };

  // Google's cap: one primary plus nine more.
  const total = 1 + (extra?.length ?? 0);
  const full = total >= 10;
  const changed =
    JSON.stringify(extra?.map((c) => c.id)) !==
    JSON.stringify(now?.additional.map((c) => c.id));

  const options: Record<string, unknown> = {};
  if (address.trim()) options.address = address.trim();
  if (phone.trim()) options.phone = phone.trim();
  if (website.trim()) options.website = website.trim();
  if (changed && extra) options.categories = extra.map((c) => c.id).join(",");

  const nothingToDo = Object.keys(options).length === 0;

  return (
    <ActionPage
      title="The profile itself"
      command="details"
      writes
      options={options}
      disabled={nothingToDo}
      disabledWhy={nothingToDo ? "Change something first." : undefined}
      previewLabel="Preview the change"
      applyLabel="Write it to Google"
      lead={
        <>
          <p>
            Address, categories and contact details. These are the facts only you
            know, so nothing here is generated and nothing is guessed.
          </p>
          <p>
            Each field is written with its own narrow update, so changing the
            address <strong className="text-g-grey900">cannot</strong> blank the
            phone number.
          </p>
        </>
      }
      controls={
        <div className="rounded-lg bg-g-grey100 p-3.5">
          <Field
            label="Street address"
            value={address}
            onChange={setAddress}
            placeholder={now?.address_line || "leave blank to keep it"}
            hint="The city and postcode already on the profile are kept as they are."
          />
          <Field
            label="Phone"
            value={phone}
            onChange={setPhone}
            placeholder={now?.phone || "leave blank to keep it"}
          />
          <Field
            label="Website"
            value={website}
            onChange={setWebsite}
            placeholder={now?.website || "leave blank to keep it"}
          />
        </div>
      }
    >
      {address.trim() && (
        <Banner tone="yellow" title="An address change can trigger re-verification">
          Google sometimes asks a business to verify itself again after the
          address moves. A change of floor or suite inside the same building is
          usually accepted without it, but it is not guaranteed.
        </Banner>
      )}

      <Card title="On the profile now">
        {!now ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-5" />)}</div>
        ) : (
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
            <Row label="Address" value={`${now.address_line}, ${now.locality} ${now.postal_code}`} />
            <Row label="Phone" value={now.phone || "(none)"} />
            <Row label="Website" value={now.website || "(none)"} />
            <Row label="Primary category" value={now.primary.name} />
            <Row
              label="Services"
              value={`${now.services.total} listed, ${now.services.described} with a description`}
            />
          </dl>
        )}
      </Card>

      <Card
        title={`Categories (${total} of 10)`}
        subtitle="One primary plus up to nine more. The primary is the strongest ranking signal on the profile."
      >
        {!now ? <Skeleton className="h-20" /> : (
          <>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Chip tone="green">{now.primary.name}</Chip>
              <span className="text-[11px] uppercase tracking-wider text-g-grey600">
                primary
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {(extra ?? []).map((c) => (
                <span
                  key={c.id}
                  className="inline-flex items-center gap-1.5 rounded-pill border
                    border-g-grey300 bg-white px-2.5 py-1 text-[13px] text-g-grey900"
                >
                  {c.name}
                  <button
                    onClick={() => setExtra((v) => (v ?? []).filter((x) => x.id !== c.id))}
                    className="text-g-grey500 hover:text-g-red"
                    title={`Remove ${c.name}. The profile stops being eligible for searches that map to it.`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>

            <div className="mt-4 border-t border-g-grey200 pt-4">
              <div className="flex gap-2">
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") search(); }}
                  placeholder="search Google's categories, e.g. makeup"
                  className="flex-1 rounded-lg border border-g-grey300 bg-white px-3 py-2
                    text-sm outline-none focus:border-g-blue"
                />
                <Button kind="outlined" onClick={search} disabled={searching}>
                  {searching ? "Searching…" : "Search"}
                </Button>
              </div>

              {searched && found.length === 0 && !searching && (
                <p className="mt-3 text-[13px] text-g-grey700">
                  Google has no category matching &ldquo;{searched}&rdquo;. Its
                  list is fixed — you can only pick from what it offers, so try a
                  different word.
                </p>
              )}

              {found.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {found.map((c) => {
                    const on = c.id === now.primary.id
                      || (extra ?? []).some((x) => x.id === c.id);
                    return (
                      <button
                        key={c.id}
                        disabled={on || full}
                        onClick={() => setExtra((v) => [...(v ?? []), c])}
                        title={full ? "Google allows 10 categories. Remove one first." : undefined}
                        className={`rounded-pill border px-2.5 py-1 text-[13px] ${
                          on || full
                            ? "border-g-grey200 text-g-grey500 cursor-not-allowed"
                            : "border-g-blue text-g-blue hover:bg-g-blueLight"
                        }`}
                      >
                        {on ? `${c.name} · already on` : `+ ${c.name}`}
                      </button>
                    );
                  })}
                </div>
              )}

              {full && (
                <p className="mt-3 text-[13px] text-[#b06000]">
                  All 10 slots are used. Remove one before adding another.
                </p>
              )}
            </div>
          </>
        )}
      </Card>
    </ActionPage>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-g-grey600">{label}</dt>
      <dd className="text-g-grey900 break-words">{value}</dd>
    </>
  );
}
