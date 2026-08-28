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
import re
import time
from dataclasses import dataclass, field
from typing import Any

from . import db, images, keywords as kw_mod, llm, site
from .api import ApiError, Client
from .rules import Snapshot

# Google's own list. LEARN_MORE needs a url; CALL needs none.
CTA_TYPES = {"BOOK", "ORDER", "SHOP", "LEARN_MORE", "SIGN_UP", "CALL"}

MAX_POST_CHARS = 1500

# A run of digits long enough to be a phone number, in any of the shapes a
# Pakistani or international number gets written in.
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")

# A phone number carries at least nine digits. The shape alone is not enough to
# tell one from a date: "2026-08-28" matches the pattern above but holds only
# eight, and blocking a post for mentioning a date would be its own bug.
_MIN_PHONE_DIGITS = 9


def find_phone_numbers(text: str) -> list[str]:
    """Every phone number in the text, dates and short figures excluded."""
    out = []
    for match in _PHONE.finditer(text):
        found = match.group(0).strip()
        if sum(c.isdigit() for c in found) >= _MIN_PHONE_DIGITS:
            out.append(found)
    return out


SYSTEM = """You write Google Business Profile posts for a local business.

Voice: the owner, writing quickly and plainly. Useful first, promotional never.

Hard rules:
- 120 to 220 words. Google truncates hard on mobile, so the first sentence has
  to carry the whole point on its own.
- Open with the customer's problem in their own words, not with the business
  name.
- Give one genuinely useful specific thing: what to check, what it costs
  roughly, how long it takes, what goes wrong when it is left.
- NEVER put a phone number in the post. Google rejects the whole post for it,
  silently, after it appears to publish. The call button on the profile is how
  people ring. This is not a style preference, it is the difference between a
  post that exists and one that does not.
- No superlatives, no "we are proud to", no hashtags, no emoji, no links in the
  body (the button handles that).
- Never invent a price, a guarantee, an award or a statistic. If you were not
  given a number, write it without one.
- Plain sentences. No em-dashes. Short paragraphs.

Output the post text only."""

# Added on top of SYSTEM when the post is written from a service page. This is
# what makes "post about these services, from these pages" mean something
# stronger than "here is some background reading".
GROUNDED_SYSTEM = """
YOU ARE WRITING FROM ONE SPECIFIC PAGE.

The page content is given to you below. It is the only source you have.

- Describe the service the way THAT PAGE describes it. Same scope, same
  inclusions, same process, same names for things.
- Every factual detail must come from the page: what is covered, what is not,
  how long it takes, what it costs, which areas are served, any guarantee.
- If the page does not say something, you do not know it. Write around it.
- Do not add a number, a price, a timeframe, a percentage or a quantity that
  does not appear on the page.
- Do not promise anything the page does not promise.

Getting this wrong puts a false claim on a public business profile, so when in
doubt, leave it out."""


@dataclass
class PostDraft:
    topic: str
    text: str
    cta_type: str
    cta_url: str
    image_url: str | None = None
    image_path: str | None = None
    source_url: str | None = None
    # Anything that should stop this being published. Empty means good to go.
    problems: list[str] = field(default_factory=list)


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


def choose_target(snap: Snapshot, location_name: str, cfg: dict,
                  site_data: "site.Site | None" = None
                  ) -> tuple[str, "site.Page | None"]:
    """Pick what to post about, and the page to write it from.

    When service page URLs are configured, the rotation runs over THOSE pages
    and nothing else -- that is the whole point of listing them. Otherwise it
    falls back to the services on the Google profile, with no source page.

    Either way it picks the least recently used one, so the rotation is real
    rather than random-with-repeats.
    """
    recent = [r["target"] for r in db.recent_actions(location_name, limit=60)
              if r["kind"] == "post"]

    if site_data and site_data.services:
        pages = list(site_data.services.values())
        unused = [p for p in pages if p.url not in recent]
        pool = unused or pages
        # Least recently used: the one furthest down the recent list.
        page = min(pool, key=lambda p: (recent.index(p.url)
                                        if p.url in recent else -1))
        label = page.h1 or page.title or page.url
        return label, page

    services = _services(snap) or ["our services"]
    unused = [s for s in services if s not in recent]
    pool = unused or services
    return random.choice(pool), None


def draft(snap: Snapshot, topic: str, cfg: dict,
          page: "site.Page | None" = None,
          site_data: "site.Site | None" = None,
          analysis: "kw_mod.Analysis | None" = None) -> tuple[str, list[str]]:
    """Write the post. Returns the text and any problems that should stop it.

    When there is a source page, the result is checked against it: a number the
    page does not contain is not allowed onto the profile. Two regeneration
    attempts, then the post is returned WITH its problems listed, and apply()
    refuses to publish it.
    """
    bcfg = cfg.get("business", {}) or {}
    city = bcfg.get("city") or snap.locality or ""
    facts = bcfg.get("facts", []) or []
    lcfg = cfg.get("llm", {}) or {}

    base = (
        f"Business: {bcfg.get('name') or snap.title}\n"
        f"What it does: {bcfg.get('what_we_do', '')}\n"
        f"City and area: {city}\n"
        f"Today's topic: {topic}\n"
    )
    if facts:
        base += ("Facts the owner has confirmed (use only these, and only if "
                 "they fit):\n" + "\n".join(f"- {f}" for f in facts) + "\n")

    system = SYSTEM
    sources = "\n".join(facts)

    if page is not None:
        system = SYSTEM + "\n" + GROUNDED_SYSTEM
        base += "\n" + site.service_block(page) + "\n"
        sources += "\n" + page.text + "\n" + page.title + "\n" + \
            " ".join(page.headings)
    elif site_data and site_data.ok:
        # No specific page, but we have the site. Give the writer the home page
        # so it at least uses the business's own words.
        block = site.business_block(site_data)
        if block:
            base += "\n" + block + "\n"
            sources += "\n" + site_data.all_text

    ask = (f"\nWrite the post about {topic}, for someone in {city} who has that "
           f"problem right now.")

    prompt = base + ask
    problems: list[str] = []
    text = ""

    for attempt in range(3):
        text = llm.generate(prompt, system=system, cfg=lcfg)
        if len(text) > MAX_POST_CHARS:
            cut = text[:MAX_POST_CHARS]
            dot = cut.rfind(". ")
            text = (cut[:dot + 1] if dot > 600 else cut).strip()

        # A phone number gets the whole post rejected by Google, silently,
        # after it looks like it published. Caught here so the writer rewrites
        # the sentence properly, rather than having the number cut out later
        # and left reading "Call us at today".
        phones = find_phone_numbers(text)
        bad = site.unverified_numbers(text, sources) if sources.strip() else []
        if not bad and not phones:
            return text, []

        problems = []
        if phones:
            problems.append(f"contains a phone number ({phones[0]}), which "
                            f"makes Google reject the whole post")
        if bad:
            problems.append(f"uses a number that is not on the source page or "
                            f"in your confirmed facts: {', '.join(bad)}")

        if attempt < 2:
            retry = base + ask
            if phones:
                retry += ("\n\nYour previous attempt included a phone number. "
                          "Google rejects any post that contains one. Write it "
                          "again with no phone number anywhere, and do not "
                          "replace it with a line telling people to call a "
                          "number -- the profile already has a call button.")
            if bad:
                retry += (f"\n\nYour previous attempt used these numbers, which "
                          f"do not appear in the source above: "
                          f"{', '.join(bad)}. Write it again without them. Do "
                          f"not substitute different numbers -- write the "
                          f"sentence without a figure at all.")
            prompt = retry

    return text, problems


def plan(snap: Snapshot, location_name: str, cfg: dict,
         *, topic: str | None = None, with_image: bool = True,
         site_data: "site.Site | None" = None,
         url: str | None = None,
         analysis: "kw_mod.Analysis | None" = None) -> PostDraft:
    pcfg = cfg.get("posts", {}) or {}
    bcfg = cfg.get("business", {}) or {}

    page = None
    if url and site_data:
        page = site_data.page_for(url)
        if page is None:
            # An explicit --url that we have not already fetched: fetch it now
            # rather than silently posting about something else.
            page = site.fetch_page(url)
            if not page.ok:
                raise RuntimeError(f"Could not read {url} -- {page.error}")
        topic = topic or page.h1 or page.title or url
    elif topic is None:
        topic, page = choose_target(snap, location_name, cfg, site_data)

    text, problems = draft(snap, topic, cfg, page=page, site_data=site_data,
                           analysis=analysis)

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
            # The source page gives the image prompt real detail -- what the
            # job actually involves -- instead of just a service name.
            extra = images.detail_from_page(page) if page else ""
            img = images.generate(topic, bcfg.get("city") or snap.locality,
                                  topic, cfg, extra=extra)
            if img:
                image_path = str(img.path)
                image_url = images.host(img, cfg)
        except Exception as exc:
            # An image problem must never block the post. Text-only still
            # counts for freshness, which is the ranking signal.
            print(f"  ! image step skipped: {exc}")

    return PostDraft(topic=topic, text=text, cta_type=cta_type,
                     cta_url=cta_url, image_url=image_url,
                     image_path=image_path,
                     source_url=page.url if page else None,
                     problems=problems)


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
    if d.source_url:
        print(f"  SOURCE: {d.source_url}")
    print("-" * 72)
    print(f"\n{d.text}\n")
    print(f"  Button: {d.cta_type}" + (f" -> {d.cta_url}" if d.cta_url else ""))
    if d.image_path:
        print(f"  Image:  {d.image_path}")
        print(f"  Hosted: {d.image_url or 'NOT hosted -- post will be text only'}")
    else:
        print("  Image:  none (text-only post)")

    if d.problems:
        print("\n  WILL NOT PUBLISH:")
        for p in d.problems:
            print(f"    - {p}")
        print("\n  The writer could not stay inside the source after three "
              "attempts.")
        print("  Either the page is too thin to write from, or the topic needs "
              "a fact")
        print("  it does not contain. Add it to business.facts if it is true, "
              "or pick")
        print("  a different page. Use --force to publish anyway.")
    print()


def strip_phone_numbers(text: str) -> tuple[str, int]:
    """Remove phone numbers from post text.

    Learned the hard way on a live profile: a post carrying a booking number
    came back REJECTED from Google while every other post on the same profile
    was LIVE. Nothing in the API response said so -- the create call returned
    200 and the tool printed "posted". The prompt now forbids it, but a prompt
    is a request rather than a guarantee, so it is enforced here too.
    """
    removed = 0

    def drop(match: "re.Match[str]") -> str:
        nonlocal removed
        found = match.group(0)
        if sum(c.isdigit() for c in found) < _MIN_PHONE_DIGITS:
            return found  # a date, not a number anyone can ring
        removed += 1
        return ""

    cleaned = _PHONE.sub(drop, text)
    # Tidy the wreckage a removal leaves: "Bookings on ." and stray gaps.
    cleaned = re.sub(r"[ \t]*[:\-]?[ \t]*\.", ".", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    # Drop any line that only ever existed to carry the number.
    keep = []
    for line in cleaned.split("\n"):
        bare = line.strip().rstrip(".").strip().lower()
        if bare in {"", "bookings", "bookings on", "booking", "call us",
                    "call us on", "call", "contact us"} and line.strip():
            continue
        keep.append(line)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(keep))
    return cleaned.strip(), removed


def verify_state(client: Client, account: str, location_id: str,
                 name: str = "", *, wait: float = 25.0) -> str:
    """What Google actually did with the post that was just sent.

    A 200 from the create call means "accepted for processing", not
    "published". A post can come back REJECTED moments later, and nothing in
    the create response says so.

    Google returns PROCESSING first and settles a second or two later, so this
    waits for a verdict rather than reporting the first thing it sees. Calling
    PROCESSING a failure would be its own bug -- and was, briefly.
    """
    deadline = time.monotonic() + wait
    state = ""
    while True:
        try:
            posts = client.local_posts(account, location_id)
        except ApiError:
            return state
        found = ""
        if name:
            for post in posts:
                if post.get("name") == name:
                    found = post.get("state", "")
                    break
        if not found and posts:
            found = posts[0].get("state", "")
        state = found or state

        if state and state != "PROCESSING":
            return state
        if time.monotonic() >= deadline:
            return state
        time.sleep(2.0)


def apply(d: PostDraft, client: Client, account: str, location_name: str,
          location_id: str, *, dry_run: bool = True,
          language: str = "en", force: bool = False) -> bool:
    if d.problems and not force:
        print("  Not published -- see the problems above.")
        return False
    if dry_run:
        print("  DRY RUN -- nothing was published. Re-run with --apply.")
        db.record_action(location_name, "post", d.source_url or d.topic,
                         d.text[:500], dry_run=True)
        return False
    cleaned, removed = strip_phone_numbers(d.text)
    if removed:
        print(f"  ! removed {removed} phone number(s) from the text -- "
              f"Google rejects posts that contain one.")
        d.text = cleaned

    try:
        created = client.create_local_post(account, location_id,
                                           to_api_body(d, language))
    except ApiError as exc:
        print(f"  x post failed: {exc}")
        return False

    # Google accepts the request and judges the content afterwards, so a 200
    # here is not yet a published post.
    state = verify_state(client, account, location_id,
                         (created or {}).get("name", ""))
    if state == "PROCESSING" or not state:
        print("  ~ posted. Google is still processing it, so it is not "
              "confirmed live yet. Check the profile in a minute.")
        db.record_action(location_name, "post", d.source_url or d.topic,
                         d.text[:500])
        return True

    if state != "LIVE":
        print(f"  x Google returned the post as {state}, so it is NOT on the "
              f"profile. Nothing here retries automatically -- the content "
              f"needs changing first.")
        db.record_action(location_name, "post", d.source_url or d.topic,
                         f"[{state}] {d.text[:480]}")
        return False
    # Recorded against the source URL when there is one, so the rotation over
    # service pages knows which page has had its turn.
    db.record_action(location_name, "post", d.source_url or d.topic,
                     d.text[:500])
    print(f"  + posted{' and confirmed LIVE' if state == 'LIVE' else ''}.")
    return True
