"use client";

import { useEffect, useState } from "react";
import { useApp } from "@/components/Shell";
import { Button, Card, Empty } from "@/components/ui";
import { api, ProfileSettings } from "@/lib/api";

/**
 * Per-business settings.
 *
 * These are stored against the profile, NOT in config.yaml, which is what lets
 * one install manage many clients. `facts` in particular is the only thing the
 * description writer is allowed to assert, so one client's claims can never end
 * up on another's profile.
 */
export default function SettingsPage() {
  const { active, refresh } = useApp();
  const [s, setS] = useState<ProfileSettings>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (active) setS(active.settings || {});
  }, [active]);

  if (!active) return <Empty>Pick a business first.</Empty>;

  const business = s.business || {};
  const website = s.website || {};
  const competitors = s.competitors || {};

  const set = (patch: ProfileSettings) => {
    setS((prev) => ({ ...prev, ...patch }));
    setSaved(false);
  };

  const save = async () => {
    setError("");
    try {
      await api.saveSettings(active.location, s);
      await refresh();
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const lines = (v?: string[]) => (v || []).join("\n");
  const toLines = (v: string) =>
    v.split("\n").map((x) => x.trim()).filter(Boolean);

  return (
    <div className="space-y-5 max-w-3xl">
      <Card title={`Settings for ${active.title}`}>
        <p className="text-sm text-g-grey700">
          These belong to this business. Thresholds, the model and rate limits live in{" "}
          <code>config.yaml</code> and are shared by everything.
        </p>
      </Card>

      <Card title="The business">
        <Text
          label="Name"
          value={business.name ?? active.title ?? ""}
          onChange={(v) => set({ business: { ...business, name: v } })}
        />
        <Text
          label="City"
          value={business.city ?? active.city ?? ""}
          onChange={(v) => set({ business: { ...business, city: v } })}
        />
        <Area
          label="What it does"
          rows={3}
          value={business.what_we_do || ""}
          onChange={(v) => set({ business: { ...business, what_we_do: v } })}
          hint="One or two plain sentences, the way you would say it out loud."
        />
      </Card>

      <Card title="Confirmed facts">
        <p className="text-sm text-g-grey700 mb-3">
          <strong className="text-g-grey900">The only claims the writer may make.</strong> One
          per line. If a detail is not here and not on the website, it will not appear in
          a description, a post or a review reply.
        </p>
        <Area
          label=""
          rows={6}
          value={lines(business.facts)}
          onChange={(v) => set({ business: { ...business, facts: toLines(v) } })}
          placeholder={"Trading since 2009.\nGas Safe registered.\nTwelve month guarantee on workmanship."}
          hint="Leave it empty if nothing has been verified with the client. Empty is honest; a guess is not."
        />
      </Card>

      <Card title="Website and service pages">
        <Text
          label="Website"
          value={website.url || ""}
          placeholder="taken from the Google profile if left blank"
          onChange={(v) => set({ website: { ...website, url: v } })}
        />
        <Area
          label="Service page URLs"
          rows={5}
          value={lines(website.service_pages)}
          onChange={(v) => set({ website: { ...website, service_pages: toLines(v) } })}
          placeholder={"https://example.com/services/boiler-repair/\nhttps://example.com/services/blocked-drains/"}
          hint="Posts rotate through ONLY these, least recently used first, each written from that page. Leave empty to discover them from the sitemap."
        />
      </Card>

      <Card title="Competitor keywords">
        <Area
          label=""
          rows={4}
          value={lines(competitors.keywords)}
          onChange={(v) => set({ competitors: { ...competitors, keywords: toLines(v) } })}
          placeholder={"plumber durham\nboiler repair durham"}
          hint="Max 5. Each is one billed DataForSEO request when you run a comparison."
        />
      </Card>

      <div className="flex items-center gap-3">
        <Button kind="filled" onClick={save}>Save</Button>
        {saved && <span className="text-sm text-g-green">Saved.</span>}
        {error && <span className="text-sm text-g-red">{error}</span>}
      </div>
    </div>
  );
}

function Text({
  label, value, onChange, placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="block mb-3">
      <span className="text-sm text-g-grey700">{label}</span>
      <input
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg bg-white border border-g-grey300 px-3 py-2 text-sm outline-none focus:border-g-blue"
      />
    </label>
  );
}

function Area({
  label, value, onChange, rows = 4, placeholder, hint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  placeholder?: string;
  hint?: string;
}) {
  return (
    <label className="block mb-3">
      {label && <span className="text-sm text-g-grey700">{label}</span>}
      <textarea
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-lg bg-white border border-g-grey300 px-3 py-2 text-sm font-mono outline-none focus:border-g-blue resize-y"
      />
      {hint && <span className="text-xs text-g-grey600 block mt-1">{hint}</span>}
    </label>
  );
}
