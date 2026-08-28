"use client";

import { useEffect, useState } from "react";
import ActionPage, { Field, Toggle } from "@/components/ActionPage";
import { useApp } from "@/components/Shell";
import { Card, Empty, Chip } from "@/components/ui";
import { ago, api } from "@/lib/api";

export default function PostsPage() {
  const { active, status, running } = useApp();
  const [url, setUrl] = useState("");
  const [topic, setTopic] = useState("");
  const [noImage, setNoImage] = useState(false);
  const [force, setForce] = useState(false);
  const [posts, setPosts] = useState<
    { target: string; detail: string; dry_run: boolean; when: string }[]
  >([]);

  const pages = active?.settings?.website?.service_pages || [];

  useEffect(() => {
    if (!active) return;
    api
      .activity(active.location)
      .then((r) => setPosts(r.actions.filter((a) => a.kind === "post")))
      .catch(() => {});
  }, [active, running]);

  const options: Record<string, unknown> = {};
  if (url) options.url = url;
  if (topic) options.topic = topic;
  if (noImage) options["no-image"] = true;
  if (force) options.force = true;

  return (
    <ActionPage
      title="Write a Google Post"
      command="post"
      writes
      options={options}
      previewLabel="Write a draft"
      applyLabel="Write and publish"
      lead={
        <>
          <p>
            A What&apos;s New post stops being shown prominently after about a week, so
            the whole value is posting weekly and never stopping. Almost no small
            competitor does it.
          </p>
          <p>
            Posts rotate through the service pages you list in Settings, least recently
            used first, and each one is written <strong className="text-g-grey900">from that
            page</strong> — same scope, same inclusions, same words for things.
          </p>
        </>
      }
      controls={
        <div className="rounded-lg bg-g-grey100 p-3.5">
          {pages.length > 0 && (
            <div className="mb-3">
              <div className="text-xs uppercase tracking-wider text-g-grey600 mb-2">
                Write from a specific page
              </div>
              <div className="flex flex-wrap gap-1.5">
                <button
                  onClick={() => setUrl("")}
                  className={`text-xs px-2.5 py-1 rounded border ${
                    url === "" ? "border-accent bg-white" : "border-g-grey300 text-g-grey600"
                  }`}
                >
                  rotate automatically
                </button>
                {pages.map((p) => (
                  <button
                    key={p}
                    onClick={() => setUrl(p)}
                    className={`text-xs px-2.5 py-1 rounded border truncate max-w-xs ${
                      url === p ? "border-accent bg-white" : "border-g-grey300 text-g-grey600"
                    }`}
                    title={p}
                  >
                    {p.replace(/^https?:\/\/[^/]+/, "") || p}
                  </button>
                ))}
              </div>
            </div>
          )}

          <Field
            label="Or a page URL"
            value={url}
            onChange={setUrl}
            placeholder="https://example.com/services/boiler-repair/"
            hint={pages.length === 0 ? "Add your service pages in Settings and they appear here as buttons." : undefined}
          />
          <Field
            label="Force a topic (optional)"
            value={topic}
            onChange={setTopic}
            placeholder="leave blank to rotate through the services"
          />
          <Toggle
            label="Text only, no image"
            checked={noImage}
            onChange={setNoImage}
            hint={
              status?.images === "none"
                ? "No image backend configured, so posts are text-only anyway."
                : undefined
            }
          />
          <Toggle
            label="Publish even if it fails the source check"
            checked={force}
            onChange={setForce}
            hint="The writer refuses to publish a post containing a number the source page does not contain. Only override this if you know the claim is true."
          />
        </div>
      }
    >
      <Card title="The grounding guard">
        <p className="text-sm text-g-grey700">
          Every number in a draft is checked against the source page and your confirmed
          facts. An invented price, timeframe or percentage triggers a rewrite, and after
          three attempts the post is{" "}
          <strong className="text-g-grey900">refused rather than published</strong>. That is
          what makes &ldquo;the details must match the page&rdquo; mean something.
        </p>
      </Card>

      <Card title={`Posts (${posts.filter((p) => !p.dry_run).length} published)`}>
        {posts.length === 0 ? (
          <Empty>Nothing yet.</Empty>
        ) : (
          <div className="space-y-2">
            {posts.slice(0, 12).map((p, i) => (
              <div key={i} className="p-3 rounded-lg bg-g-grey100">
                <div className="flex items-center gap-2 mb-1">
                  <Chip tone={p.dry_run ? "neutral" : "green"}>
                    {p.dry_run ? "draft" : "published"}
                  </Chip>
                  <span className="text-xs text-g-grey600 truncate">{p.target}</span>
                  <span className="text-xs text-g-grey600 ml-auto shrink-0">{ago(p.when)}</span>
                </div>
                <p className="text-sm text-g-grey700 line-clamp-3">{p.detail}</p>
              </div>
            ))}
          </div>
        )}
      </Card>
    </ActionPage>
  );
}
