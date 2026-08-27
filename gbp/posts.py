"""Writing and publishing Google Posts.

A What's New post stops being shown prominently after about a week, so the
whole value is in posting weekly and never stopping. Almost no small competitor
does, which is why it is worth automating.

Topics rotate through the services on the profile so the same job type does not
come round twice in a month, and every post carries a button -- a post with no
call to action is an advert with no way to respond.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from . import db, images, llm
from .api import ApiError, Client
from .rules import Snapshot

# Google's own list. LEARN_MORE needs a url; CALL needs none.
CTA_TYPES = {"BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL"}

MAX_POST_CHARS = 1500

SYSTEM = """You write Google Business Profile posts for a local business.

Voice: the owner, writing quickly and plainly. Useful first, promotional never.

Hard rules:
- 120 to 220 words. Google truncates hard on mobile, so the first sentence has
  to carry the whole point on its own.
- Open with the customer's problem in their own words, not with the business
  name.
- Give one genuinely useful specific thing: what to check, what it costs
  roughly, how long it takes, what goes wrong when it is left.
- No superlatives, no "we are proud to", no hashtags, no emoji, no links in the
  body (the button handles that).
- Never invent a price, a guarantee, an award or a statistic. If you were not
  given a number, write it without one.
- Plain sentences. No em-dashes. Short paragraphs.

Output the post text only."""


@dataclass
class PostDraft:
    topic: str
    text: str
    cta_type: str
    cta_url: str
    image_url: str | None = None
    image_path: str | None = None


def _services(snap: Snapshot) -> list[str]:
    out: list[str] = []
    for item in snap.location.get("serviceItems", []) or []:
        label = (item.get("freeFormServiceItem", {}).get("label", {}) or {})
        if label.get("displayName"):
            out.append(label["displayName"])
    if not out:
        cat = snap.primary_category.get("displayName")
        if cat:
            out.append(cat)
        out += [c.get("displayName", "") for c in snap.additional_categories]
    return [s for s in out if s]


def choose_topic(snap: Snapshot, location_name: str, cfg: dict) -> str:
    """Pick the service least recently posted about, so the rotation is real."""
    services = _services(snap) or ["our services"]
    recent = [r["target"] for r in db.recent_actions(location_name, limit=40)
              if r["kind"] == "post"]
    unused = [s for s in services if s not in recent]
    pool = unused or services
    # Seeded by nothing in particular -- the point is only to break ties.
    return random.choice(pool)


def draft(snap: Snapshot, topic: str, cfg: dict) -> str:
    bcfg = cfg.get("business", {}) or {}
    city = bcfg.get("city") or snap.locality or ""
    facts = bcfg.get("facts", []) or []

    prompt = (
        f"Business: {bcfg.get('name') or snap.title}\n"
        f"What it does: {bcfg.get('what_we_do', '')}\n"
        f"City and area: {city}\n"
        f"Today's topic: {topic}\n"
    )
    if facts:
        prompt += ("Facts the owner has confirmed (use only these, and only if "
                   "they fit):\n" + "\n".join(f"- {f}" for f in facts) + "\n")
    prompt += (f"\nWrite the post about {topic}, for someone in {city} who has "
               f"that problem right now.")

    text = llm.generate(prompt, system=SYSTEM, cfg=cfg.get("llm", {}))
    if len(text) > MAX_POST_CHARS:
        cut = text[:MAX_POST_CHARS]
        dot = cut.rfind(". ")
        text = (cut[:dot + 1] if dot > 600 else cut).strip()
    return text


def plan(snap: Snapshot, location_name: str, cfg: dict,
         *, topic: str | None = None, with_image: bool = True) -> PostDraft:
    pcfg = cfg.get("posts", {}) or {}
    bcfg = cfg.get("business", {}) or {}

    topic = topic or choose_topic(snap, location_name, cfg)
    text = draft(snap, topic, cfg)

    cta_type = (pcfg.get("cta_type") or "LEARN_MORE").upper()
    if cta_type not in CTA_TYPES:
        raise RuntimeError(f"posts.cta_type '{cta_type}' is not one of "
                           f"{', '.join(sorted(CTA_TYPES))}")
    cta_url = pcfg.get("cta_url") or snap.location.get("websiteUri", "") or ""
    if cta_type != "CALL" and not cta_url:
        raise RuntimeError(
            f"posts.cta_type is {cta_type}, which needs a URL, but neither "
            f"posts.cta_url nor the profile's website is set.")

    image_url = image_path = None
    if with_image:
        try:
            img = images.generate(topic, bcfg.get("city") or snap.locality,
                                  topic, cfg)
            if img:
                image_path = str(img.path)
                image_url = images.host(img, cfg)
        except Exception as exc:
            # An image problem must never block the post. Text-only still
            # counts for freshness, which is the ranking signal.
            print(f"  ! image step skipped: {exc}")

    return PostDraft(topic=topic, text=text, cta_type=cta_type,
                     cta_url=cta_url, image_url=image_url,
                     image_path=image_path)


def to_api_body(d: PostDraft, language: str = "en") -> dict[str, Any]:
    body: dict[str, Any] = {
        "languageCode": language,
        "summary": d.text,
        "topicType": "STANDARD",
    }
    cta: dict[str, Any] = {"actionType": d.cta_type}
    if d.cta_type != "CALL":
        cta["url"] = d.cta_url
    body["callToAction"] = cta
    if d.image_url:
        body["media"] = [{"mediaFormat": "PHOTO", "sourceUrl": d.image_url}]
    return body


def show(d: PostDraft) -> None:
    print("\n" + "-" * 72)
    print(f"  TOPIC:  {d.topic}")
    print("-" * 72)
    print(f"\n{d.text}\n")
    print(f"  Button: {d.cta_type}" + (f" -> {d.cta_url}" if d.cta_url else ""))
    if d.image_path:
        print(f"  Image:  {d.image_path}")
        print(f"  Hosted: {d.image_url or 'NOT hosted -- post will be text only'}")
    else:
        print("  Image:  none (text-only post)")
    print()


def apply(d: PostDraft, client: Client, account: str, location_name: str,
          location_id: str, *, dry_run: bool = True,
          language: str = "en") -> bool:
    if dry_run:
        print("  DRY RUN -- nothing was published. Re-run with --apply.")
        db.record_action(location_name, "post", d.topic, d.text[:500],
                         dry_run=True)
        return False
    try:
        client.create_local_post(account, location_id,
                                 to_api_body(d, language))
    except ApiError as exc:
        print(f"  x post failed: {exc}")
        return False
    db.record_action(location_name, "post", d.topic, d.text[:500])
    print("  + posted.")
    return True
