"""Replying to Google reviews.

Google has said publicly that responding to reviews improves local ranking, and
most small competitors never do it. That makes this the highest-value automation
on the profile, and also the most dangerous: a tone-deaf automated reply to a
one-star review is worse than silence, and it is public forever.

So the defaults are cautious:

  * dry run unless you pass --apply
  * low-star reviews are HELD for a human by default (`hold_below`)
  * a reply is never sent twice, tracked in the database by review name
  * a per-run cap, so a first run on a profile with 300 unanswered reviews
    does not fire 300 replies in one burst
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import db, llm
from .api import ApiError, Client

STARS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}

SYSTEM = """You write replies to Google reviews as the business owner.

Voice: a competent owner typing on their phone. Warm, brief, specific, human.

Hard rules:
- 1 to 3 sentences. Never more.
- Use the reviewer's first name if there is one, once, at the start.
- Refer to something concrete they actually said. Generic replies are worse
  than none, and the next customer can tell.
- Never invent a detail: no discounts, no promises, no claims about what
  happened on the job, no staff names you were not given.
- No marketing language, no hashtags, no links, no emoji.
- For a negative review: acknowledge the specific problem, take it offline
  ("call us on the number on our profile"), no excuses, no arguing, no legal
  language. Do not apologise more than once.
- Never say "we appreciate you taking the time" or anything like it.

Output the reply text only."""


@dataclass
class Draft:
    review_name: str
    reviewer: str
    stars: int
    comment: str
    reply: str
    held: bool
    reason: str = ""


def _stars(review: dict) -> int:
    return STARS.get(review.get("starRating", ""), 0)


def _reviewer(review: dict) -> str:
    name = (review.get("reviewer", {}) or {}).get("displayName", "") or ""
    return name.split()[0] if name else ""


def unanswered(reviews: list[dict]) -> list[dict]:
    return [r for r in reviews if not r.get("reviewReply")]


def draft_reply(review: dict, cfg: dict) -> str:
    bcfg = cfg.get("business", {}) or {}
    stars = _stars(review)
    name = _reviewer(review)
    comment = (review.get("comment", "") or "").strip()

    context = [
        f"Business: {bcfg.get('name', 'the business')}",
        f"What it does: {bcfg.get('what_we_do', 'a local service business')}",
        f"City: {bcfg.get('city', 'not given')}",
    ]
    tone = cfg.get("reviews", {}).get("tone", "")
    if tone:
        context.append(f"Tone note from the owner: {tone}")

    prompt = (
        "\n".join(context)
        + f"\n\nReview to reply to:\n"
        + f"  Rating: {stars} star(s)\n"
        + f"  Reviewer first name: {name or '(not given)'}\n"
        + f"  Their words: {comment or '(they left a rating with no text)'}\n\n"
        + ("They left no text, so keep it to one short line thanking them for the "
           "rating. Do not guess what they liked."
           if not comment else
           "Reply to what they actually wrote.")
    )
    return llm.generate(prompt, system=SYSTEM, cfg=cfg.get("llm", {}))


def plan(reviews: list[dict], cfg: dict, location_name: str) -> list[Draft]:
    rcfg = cfg.get("reviews", {}) or {}
    hold_below = int(rcfg.get("hold_below", 4))
    limit = int(rcfg.get("max_per_run", 10))

    drafts: list[Draft] = []
    for review in unanswered(reviews):
        name = review.get("name", "")
        if not name or db.already_done(location_name, "review_reply", name):
            continue
        if len(drafts) >= limit:
            break

        stars = _stars(review)
        held = stars and stars < hold_below
        reason = (f"{stars}-star review held for you to answer personally"
                  if held else "")

        try:
            text = draft_reply(review, cfg)
        except llm.LLMError as exc:
            print(f"  ! could not draft a reply: {exc}")
            break

        drafts.append(Draft(
            review_name=name, reviewer=_reviewer(review), stars=stars,
            comment=(review.get("comment", "") or "")[:400],
            reply=text, held=bool(held), reason=reason,
        ))
    return drafts


def show(drafts: list[Draft]) -> None:
    if not drafts:
        print("\n  No reviews are waiting for a reply.\n")
        return
    for d in drafts:
        flag = "  HELD" if d.held else "  SEND"
        print("\n" + "-" * 72)
        print(f"{flag}  {d.stars} star  from {d.reviewer or 'anonymous'}")
        if d.comment:
            print(f"  they said: {d.comment[:200]}")
        print(f"  reply:     {d.reply}")
        if d.reason:
            print(f"  ({d.reason})")
    print()


def apply(drafts: list[Draft], client: Client, location_name: str,
          *, dry_run: bool = True, include_held: bool = False) -> int:
    sendable = [d for d in drafts if include_held or not d.held]
    held = len(drafts) - len(sendable)

    if dry_run:
        print(f"  DRY RUN -- {len(sendable)} reply(ies) would be sent"
              + (f", {held} held for you." if held else "."))
        print("  Re-run with --apply to send.")
        return 0

    sent = 0
    for d in sendable:
        # plan() already filters these out, but apply() is the thing that
        # writes, so it checks again. A duplicate reply overwrites the previous
        # one on a public profile, and the cost of the extra lookup is nothing.
        if db.already_done(location_name, "review_reply", d.review_name):
            print(f"  . already replied to {d.reviewer or 'anonymous'}, skipping")
            continue
        try:
            client.reply_to_review(d.review_name, d.reply)
        except ApiError as exc:
            print(f"  x failed on one review: {exc}")
            continue
        db.record_action(location_name, "review_reply", d.review_name, d.reply)
        sent += 1
        print(f"  + replied to {d.reviewer or 'anonymous'} ({d.stars} star)")

    if held:
        print(f"\n  {held} review(s) held for you -- they are below "
              f"{'the threshold' if not include_held else 'nothing'} and deserve "
              f"a personal answer. Use --include-held to send them anyway.")
    return sent
