"use client";

import { useState } from "react";
import ActionPage, { Toggle } from "@/components/ActionPage";
import { Card } from "@/components/ui";

export default function KeywordsPage() {
  const [csv, setCsv] = useState(false);

  return (
    <ActionPage
      title="What people typed to find this business"
      command="keywords"
      options={csv ? { csv: true } : {}}
      previewLabel="Pull the search terms"
      lead={
        <>
          <p>
            Google&apos;s Performance tab has a list of the exact phrases real customers
            used. It is the most valuable thing on the profile and almost nobody acts on
            it.
          </p>
          <p>
            Every term is cross-referenced against the business name, categories,
            description, services, recent posts and the website. The ones marked{" "}
            <strong className="text-ink">NOWHERE</strong> are the work: Google is already
            showing this business for words the profile never says.
          </p>
        </>
      }
      controls={
        <div className="rounded-lg bg-panel-2 p-3.5">
          <Toggle
            label="Also write the full list to a CSV"
            hint="Lands in the reports folder. Useful to send to a client."
            checked={csv}
            onChange={setCsv}
          />
        </div>
      }
    >
      <Card title="Then turn the gaps into services">
        <p className="text-sm text-ink-2">
          The Fix screen clusters the variants (&ldquo;boiler repair&rdquo;, &ldquo;boiler
          repair near me&rdquo; and &ldquo;emergency boiler repair&rdquo; are one
          service), names each one in the customer&apos;s own words, and writes a
          description from the website copy. The same terms are fed to the post writer,
          so they get used on an ongoing basis too.
        </p>
      </Card>

      <Card title="Three things the raw data will not tell you">
        <ul className="text-sm text-ink-2 space-y-2 list-disc pl-5">
          <li>
            <strong className="text-ink">Threshold counts.</strong> Google returns an
            exact number for big terms and &ldquo;fewer than 15&rdquo; for the rest. Most
            terms are the latter. They are kept and ranked below exact counts, because a
            long-tail phrase with real intent is not worthless.
          </li>
          <li>
            <strong className="text-ink">Brand searches are separated out.</strong> A
            coverage score that counts your own name is flattering and useless.
          </li>
          <li>
            <strong className="text-ink">The city is not required.</strong> &ldquo;boiler
            repair durham&rdquo; is covered by a service called &ldquo;Boiler repair&rdquo;
            on a profile already in Durham.
          </li>
        </ul>
      </Card>
    </ActionPage>
  );
}
