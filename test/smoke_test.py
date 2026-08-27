#!/usr/bin/env python3
"""Offline end-to-end run. No network, no Google account, no model calls.

Exercises the whole pipeline against a fixture: audit, scoring, the HTML
report, fix planning, review drafting, post building, and the change watcher.
The language model is stubbed, so this is safe and instant to run any time.

    python test/smoke_test.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Point the database and reports at a temp dir BEFORE anything imports config
# paths, so a smoke test never touches real client data.
_tmp = Path(tempfile.mkdtemp(prefix="gbp-smoke-"))
from gbp import config  # noqa: E402
config.DATA_DIR = _tmp / "data"
config.REPORT_DIR = _tmp / "reports"
config.DB_PATH = config.DATA_DIR / "gbp.db"

from gbp import db, fix, holidays, images, llm, posts, report, reviews, watch  # noqa: E402
from gbp.audit import audit  # noqa: E402
from gbp.rules import Snapshot  # noqa: E402

sys.path.insert(0, str(ROOT / "test"))
from fixtures import bad_snapshot, good_snapshot, NOW  # noqa: E402

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
        print(f"  ok    {name}")
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")
        print(f"  FAIL  {name}  {extra}")


# The stub returns something realistic enough to exercise cleaning and limits.
STUB_TEXT = ("Northgate Plumbing has covered Durham and the surrounding villages "
             "since 2009. We handle emergency plumbing, blocked drains and boiler "
             "repair for homes and small commercial premises. Every engineer is "
             "directly employed and Gas Safe registered, we quote before we start, "
             "and most jobs are finished on the first visit.")


def stub_generate(prompt, *, system="", cfg=None, model=None, retries=2):
    return STUB_TEXT


llm.generate = stub_generate

CFG = {
    "business": {
        "name": "Northgate Plumbing", "city": "Durham",
        "what_we_do": "Emergency plumbing and drainage.",
        "facts": ["Trading since 2009.", "Gas Safe registered."],
    },
    "llm": {"backend": "claude"},
    "audit": {},
    "posts": {"cta_type": "LEARN_MORE", "cta_url": "https://example.com"},
    "images": {"backend": "none", "host": "none"},
    "holidays": {"region_code": "GB", "horizon_days": 120},
}

LOC = "locations/111"

print("\n" + "=" * 68)
print("1. DATABASE")
db.init()
check("database initialises", config.DB_PATH.exists())
db.record_action(LOC, "review_reply", "reviews/abc", "hi")
check("an action is remembered", db.already_done(LOC, "review_reply", "reviews/abc"))
check("an unrelated action is not", not db.already_done(LOC, "post", "reviews/abc"))
db.record_action(LOC, "review_reply", "reviews/abc", "hi again")
check("recording the same action twice does not duplicate",
      len([r for r in db.recent_actions(LOC) if r["target"] == "reviews/abc"]) == 1)

print("\n" + "=" * 68)
print("2. AUDIT")
good = audit(good_snapshot(), CFG)
bad = audit(bad_snapshot(), CFG)
check("a good profile scores well", good.score >= 90, str(good.score))
check("a bad profile scores badly", bad.score <= 25, str(bad.score))
check("bad profile has critical findings",
      any(f.severity == "critical" for f in bad.failures))
check("findings are ordered worst first",
      bad.failures[0].severity == "critical")
check("every category is represented", len(good.by_category) >= 9,
      str(len(good.by_category)))

print("\n" + "=" * 68)
print("3. HTML REPORT")
path = report.write(bad, prepared_by="Test Agency")
html = path.read_text(encoding="utf-8")
check("report file is written", path.exists())
check("report is self-contained (no external assets)",
      "http://" not in html.replace("http://www.w3.org", "")
      and "<script" not in html)
check("report names the business", "Best Cheap Plumber" in html)
check("report shows the score", f">{bad.score}<" in html)
check("report includes why-it-matters", "Why it matters" in html)
check("report includes what-to-do", "What to do" in html)
check("report escapes html in business data", "&amp;" in html or "<script" not in html)
check("report is a complete document",
      html.startswith("<!doctype html>") and html.rstrip().endswith("</html>"))

good_path = report.write(good, previous_score=60)
check("report shows the trend when there is history",
      "up 3" in good_path.read_text(encoding="utf-8")
      or "since the last check" in good_path.read_text(encoding="utf-8"))

print("\n" + "=" * 68)
print("4. FIXES")
snap = bad_snapshot()
bad_result = audit(snap, CFG)
fixes = fix.plan(bad_result, snap, CFG)
keys = {f.key for f in fixes}
check("a broken description is planned for rewrite", "description" in keys, str(keys))
check("holiday hours are planned", "holiday_hours" in keys, str(keys))

desc_fix = next(f for f in fixes if f.key == "description")
check("description fix has a narrow update mask",
      desc_fix.update_mask == "profile.description", desc_fix.update_mask)
check("description fix body only touches the description",
      list(desc_fix.body) == ["profile"] and list(desc_fix.body["profile"]) == ["description"])
check("description is within Google's limit", len(desc_fix.after) <= 750,
      str(len(desc_fix.after)))
check("rewritten description drops the URL", "example.com" not in desc_fix.after)
check("rewritten description drops the phone number",
      "555" not in desc_fix.after)

hol_fix = next(f for f in fixes if f.key == "holiday_hours")
check("holiday fix writes specialHours", hol_fix.update_mask == "specialHours")
periods = hol_fix.body["specialHours"]["specialHourPeriods"]
check("holiday periods have complete dates",
      all(p["startDate"].get("year") and p["startDate"].get("month")
          and p["startDate"].get("day") for p in periods))
check("holiday fix explains itself", any("holiday" in n.lower() for n in hol_fix.notes))


class FakeClient:
    def __init__(self):
        self.patches = []
        self.replies = []
        self.posts = []

    def patch_location(self, location, body, update_mask):
        self.patches.append((location, body, update_mask))
        return {}

    def reply_to_review(self, name, comment):
        self.replies.append((name, comment))
        return {}

    def create_local_post(self, account, location_id, body):
        self.posts.append(body)
        return {}


fc = FakeClient()
sent = fix.apply(fixes, fc, LOC, dry_run=True)
check("dry run writes nothing", sent == 0 and not fc.patches)
sent = fix.apply(fixes, fc, LOC, dry_run=False)
check("apply writes each fix", sent == len(fixes) and len(fc.patches) == len(fixes))
check("applied fixes are recorded", db.already_done(LOC, "fix", "description"))

print("\n" + "=" * 68)
print("5. REVIEWS")
review_set = [
    {"name": "reviews/r1", "starRating": "FIVE", "comment": "Fixed my boiler fast.",
     "reviewer": {"displayName": "Sarah Hughes"}, "createTime": "2026-08-20T10:00:00Z"},
    {"name": "reviews/r2", "starRating": "ONE", "comment": "Turned up two hours late.",
     "reviewer": {"displayName": "Dave"}, "createTime": "2026-08-21T10:00:00Z"},
    {"name": "reviews/r3", "starRating": "FIVE", "comment": "Great.",
     "reviewer": {"displayName": "Amy"}, "createTime": "2026-08-22T10:00:00Z",
     "reviewReply": {"comment": "Thanks Amy."}},
]
check("answered reviews are excluded", len(reviews.unanswered(review_set)) == 2)

drafts = reviews.plan(review_set, CFG, "locations/222")
check("a draft per unanswered review", len(drafts) == 2, str(len(drafts)))
one_star = next(d for d in drafts if d.stars == 1)
five_star = next(d for d in drafts if d.stars == 5)
check("a one-star review is HELD by default", one_star.held)
check("a five-star review is not held", not five_star.held)
check("held reviews say why", bool(one_star.reason))

fc2 = FakeClient()
reviews.apply(drafts, fc2, "locations/222", dry_run=True)
check("review dry run sends nothing", not fc2.replies)
n = reviews.apply(drafts, fc2, "locations/222", dry_run=False)
check("only the safe review is sent", n == 1 and len(fc2.replies) == 1)
check("the sent reply is the five-star one",
      fc2.replies[0][0] == "reviews/r1")
before = len(fc2.replies)
n2 = reviews.apply(drafts, fc2, "locations/222", dry_run=False)
check("re-applying the same drafts sends nothing new",
      n2 == 0 and len(fc2.replies) == before,
      f"sent {n2} more, replies now {len(fc2.replies)}")
check("replies are recorded",
      db.already_done("locations/222", "review_reply", "reviews/r1"))

drafts2 = reviews.plan(review_set, CFG, "locations/222")
check("an already-answered review is not re-drafted",
      all(d.review_name != "reviews/r1" for d in drafts2),
      str([d.review_name for d in drafts2]))

print("\n" + "=" * 68)
print("6. POSTS")
gs = good_snapshot()
draft = posts.plan(gs, LOC, CFG, with_image=False)
check("a post is drafted", bool(draft.text))
check("post picks a topic from the profile", bool(draft.topic))
check("post has a call to action", draft.cta_type in posts.CTA_TYPES)
body = posts.to_api_body(draft)
check("post body has a summary", bool(body.get("summary")))
check("post body has a CTA with a url",
      body["callToAction"]["actionType"] == "LEARN_MORE"
      and body["callToAction"]["url"].startswith("http"))
check("text-only post carries no media", "media" not in body)

call_cfg = dict(CFG, posts={"cta_type": "CALL", "cta_url": ""})
call_draft = posts.plan(gs, LOC, call_cfg, with_image=False)
check("a CALL button needs no url",
      "url" not in posts.to_api_body(call_draft)["callToAction"])

with_img = posts.PostDraft(topic="Boiler repair", text="x", cta_type="CALL",
                           cta_url="", image_url="https://cdn.example.com/a.png")
check("an image post carries media",
      posts.to_api_body(with_img)["media"][0]["sourceUrl"].endswith("a.png"))

fc3 = FakeClient()
posts.apply(draft, fc3, "accounts/1", LOC, "111", dry_run=True)
check("post dry run publishes nothing", not fc3.posts)
posts.apply(draft, fc3, "accounts/1", LOC, "111", dry_run=False)
check("apply publishes the post", len(fc3.posts) == 1)

print("\n" + "=" * 68)
print("7. IMAGES (no network)")
prompt = images.build_prompt("Boiler repair", "Durham")
check("image prompt names the service", "boiler repair" in prompt.lower())
check("image prompt names the city", "Durham" in prompt)
check("image prompt forbids text in the image", "no text" in prompt.lower())
check("images are off by default in this config",
      images.generate("x", "y", "z", CFG) is None)

print("\n" + "=" * 68)
print("8. WATCH")
first = watch.run(good_snapshot(), "locations/333")
check("first run reports no changes", first == [])
changed = good_snapshot()
changed.location["title"] = "Northgate Plumbing and Heating"
changed.location["metadata"]["hasVoiceOfMerchant"] = False
second = watch.run(changed, "locations/333")
labels = {c.label for c in second}
check("a name change is detected", "Business name" in labels, str(labels))
check("losing verification is detected", "Verified" in labels, str(labels))
check("losing verification is critical",
      next(c for c in second if c.label == "Verified").severity == "critical")
check("critical changes are listed first", second[0].severity == "critical")
check("changes raise alerts", len(db.open_alerts("locations/333")) >= 2)
third = watch.run(changed, "locations/333")
check("an unchanged profile reports nothing", third == [])

print("\n" + "=" * 68)
print("9. HOLIDAYS")
check("Easter 2026 is correct", holidays.easter(2026) == date(2026, 4, 5))
check("Easter 2027 is correct", holidays.easter(2027) == date(2027, 3, 28))
us = dict(holidays.upcoming("US", 200, today=date(2026, 8, 26)))
check("US Thanksgiving 2026 is the fourth Thursday",
      us.get(date(2026, 11, 26)) == "Thanksgiving", str(list(us.items())[:4]))
ca = dict(holidays.upcoming("CA", 200, today=date(2026, 8, 26)))
check("Canadian Thanksgiving is the second Monday",
      ca.get(date(2026, 10, 12)) == "Thanksgiving")
check("lunar-holiday countries are flagged for manual entry",
      holidays.needs_manual_dates("AE") and holidays.needs_manual_dates("PK"))
check("a country with computable holidays is not flagged",
      not holidays.needs_manual_dates("GB"))
extra = holidays.upcoming("AE", 400, today=date(2026, 8, 26),
                          extra=[{"date": "2027-03-20", "name": "Eid al-Fitr"}])
check("config-supplied holidays are merged in",
      any(n == "Eid al-Fitr" for _d, n in extra))

print("\n" + "=" * 68)
print("10. TEXT CLEANING")
check("markdown bold is stripped", llm.clean("**hi** there") == "hi there")
check("code fences are stripped", llm.clean("```\nhello\n```") == "hello")
check("wrapping quotes are stripped", llm.clean('"hello"') == "hello")
check("em-dashes are replaced", "—" not in llm.clean("a — b"))
check("smart quotes are normalised", "’" not in llm.clean("it’s"))
check("AI throat-clearing is detected",
      "we appreciate you taking the time" in
      llm.banned_hits("We appreciate you taking the time to write this."))
check("a normal reply is not flagged", llm.banned_hits("Thanks Sarah, glad we "
                                                       "could sort the boiler.") == [])

print("\n" + "=" * 68)
print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f in fails:
    print(f"  x {f}")
print(f"  (temp data in {_tmp})\n")
sys.exit(1 if fails else 0)
