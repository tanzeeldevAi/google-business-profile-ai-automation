"use client";

import { useState } from "react";
import ActionPage, { Field } from "@/components/ActionPage";
import { useApp } from "@/components/Shell";
import { Card } from "@/components/ui";

export default function CompetitorsPage() {
  const { active, status } = useApp();
  const saved = (active?.settings?.competitors?.keywords || []).join(", ");
  const [keywords, setKeywords] = useState(saved);
  const off = !status?.dataforseo;

  return (
    <ActionPage
      title="Compare to whoever is actually ranking"
      command="compare"
      options={keywords ? { keywords } : {}}
      previewLabel="Check the map pack"
      disabled={off || !keywords.trim()}
      disabledWhy={
        off
          ? "Needs DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD in .env. Everything else in the app works without it."
          : !keywords.trim()
          ? "Add at least one keyword."
          : undefined
      }
      lead={
        <>
          <p>
            Every other rule judges this profile against a fixed number: 20 photos, 25
            reviews, 4.0 stars. Those are a guess at an average market. Twenty-five
            reviews is invisible in central London and dominant in a market town.
          </p>
          <p>
            This asks a better question: what do the businesses ranking{" "}
            <strong className="text-ink">above you</strong> actually have? A delta
            against whoever is genuinely winning is not a guess.
          </p>
        </>
      }
      controls={
        <div className="rounded-lg bg-panel-2 p-3.5">
          <Field
            label="Keywords to check (max 5)"
            value={keywords}
            onChange={setKeywords}
            placeholder="plumber durham, boiler repair durham"
            hint="Use the words a customer types, not your job title. One billed request per keyword, cached for 24 hours."
          />
        </div>
      }
    >
      <Card title="What gets compared">
        <ul className="text-sm text-ink-2 space-y-2 list-disc pl-5">
          <li>
            <strong className="text-ink">Reviews</strong> against the top-three average,
            and how far behind.
          </li>
          <li>
            <strong className="text-ink">Categories</strong> that two or more of the top
            three carry and this profile does not. One rival having an odd category is
            noise; two of three is how that market is described.
          </li>
          <li>
            <strong className="text-ink">Photos</strong> against the top-three average.
          </li>
        </ul>
        <p className="text-sm text-ink-3 mt-3">
          Competitors&apos; post cadence and review velocity are not compared, because no
          third party exposes them. Aggregator entries that rank in Maps are filtered out
          — averaging your reviews against a directory page is meaningless.
        </p>
      </Card>
    </ActionPage>
  );
}
