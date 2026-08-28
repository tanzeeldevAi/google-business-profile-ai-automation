#!/usr/bin/env python3
"""Offline end-to-end run. No network, no Google account, no model calls.

Exercises the whole pipeline against a fixture: audit, scoring, the HTML
report, fix planning, review drafting, post building, and the change watcher.
The language model is stubbed, so this is safe and instant to run any time.

    python test/smoke_test.py
"""
from __future__ import annotations

import os
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
        # What Google says it did with a post. Real profiles return LIVE,
        # PROCESSING or REJECTED.
        self.post_state = "LIVE"

    def patch_location(self, location, body, update_mask):
        self.patches.append((location, body, update_mask))
        return {}

    def reply_to_review(self, name, comment):
        self.replies.append((name, comment))
        return {}

    def create_local_post(self, account, location_id, body):
        self.posts.append(body)
        name = f"{account}/locations/{location_id}/localPosts/{len(self.posts)}"
        return {"name": name, "state": self.post_state}

    def local_posts(self, account, location_id):
        """Publishing checks this, because Google returns 200 on create and
        then decides whether to reject the post. The fake has to model that or
        the check goes untested."""
        return [{"name": f"{account}/locations/{location_id}/localPosts/{i + 1}",
                 "state": self.post_state, "summary": b.get("summary", "")}
                for i, b in reversed(list(enumerate(self.posts)))]


fc = FakeClient()
sent = fix.apply(fixes, fc, LOC, dry_run=True)
check("dry run writes nothing", sent == 0 and not fc.patches)
sent = fix.apply(fixes, fc, LOC, dry_run=False)
check("apply writes each fix", sent == len(fixes) and len(fc.patches) == len(fixes))
check("applied fixes are recorded", db.already_done(LOC, "fix", "description"))

print("\n" + "=" * 68)
print("4b. SERVICES FROM SEARCH TERMS")

from gbp import keywords as kw_mod  # noqa: E402
from gbp import site as site_mod_early  # noqa: E402

KW_RAW = [
    {"searchKeyword": "boiler repair durham", "insightsValue": {"value": "175"}},
    {"searchKeyword": "emergency boiler repair",
     "insightsValue": {"threshold": "15"}},
    {"searchKeyword": "power flush durham", "insightsValue": {"value": "60"}},
    {"searchKeyword": "opening hours", "insightsValue": {"threshold": "15"}},
]
kw_snap = good_snapshot()
kw_snap.location["serviceItems"] = []
kw_snap.location["profile"] = {"description": "We are a plumbing company."}
kw_analysis = kw_mod.analyse(kw_mod.parse(KW_RAW), kw_snap)
kw_snap.keywords = kw_mod.to_snapshot_dict(kw_analysis)

check("search terms produce gaps", len(kw_analysis.gaps) >= 2,
      str([c.keyword.term for c in kw_analysis.gaps]))


def stub_services(prompt, *, system="", cfg=None, model=None, retries=2):
    # One line per group, in the format the planner parses.
    return ("Boiler Repair | Diagnostic and repair for gas and combi boilers, "
            "covering Durham and the surrounding area.\n"
            "Power Flushing | Clearing sludge from a central heating system so "
            "radiators heat evenly again.\n"
            "Underfloor Heating | Installation and repair of underfloor "
            "heating for homes.")


llm.generate = stub_services
kw_result = audit(kw_snap, CFG)
svc_fixes = fix.plan(kw_result, kw_snap, CFG, only=["services"],
                     analysis=kw_analysis)
check("a services fix is planned", len(svc_fixes) == 1,
      str([f.key for f in svc_fixes]))

svc = svc_fixes[0]
check("services fix writes serviceItems", svc.update_mask == "serviceItems")
items = svc.body["serviceItems"]
check("services are proposed", len(items) >= 2, str(len(items)))
first = items[0]["freeFormServiceItem"]
check("each service has a category", bool(first.get("category")),
      str(first.get("category")))
check("each service has a display name", bool(first["label"]["displayName"]))
check("each service has a description", bool(first["label"]["description"]))
check("names are within Google's limit",
      all(len(i["freeFormServiceItem"]["label"]["displayName"]) <= 120
          for i in items))
check("descriptions are within Google's limit",
      all(len(i["freeFormServiceItem"]["label"]["description"]) <= 300
          for i in items))
check("the numbered prefix is stripped from the name",
      not first["label"]["displayName"][0].isdigit(),
      first["label"]["displayName"])
check("the fix shows which search terms justified each service",
      any("from:" in n for n in svc.notes), str(svc.notes[:4]))
check("the fix warns that a search term is not a promise",
      any("promise" in n for n in svc.notes))
check("'opening hours' is never proposed as a service",
      not any("opening hour" in
              i["freeFormServiceItem"]["label"]["displayName"].lower()
              for i in items))

existing_snap = good_snapshot()
existing_snap.location["serviceItems"] = [
    {"freeFormServiceItem": {"label": {"displayName": "Existing service",
                                       "description": "Already here."}}}]
existing_snap.keywords = kw_snap.keywords
svc2 = fix.plan(audit(existing_snap, CFG), existing_snap, CFG,
                only=["services"], analysis=kw_analysis)
check("existing services are preserved, not replaced",
      any(i.get("freeFormServiceItem", {}).get("label", {})
          .get("displayName") == "Existing service"
          for i in svc2[0].body["serviceItems"]) if svc2 else False,
      "no fix planned" if not svc2 else "")

no_gaps = fix.plan_services(good_snapshot(), CFG, None,
                            kw_mod.Analysis(keywords=[], coverage=[]))
check("no gaps means no services fix", no_gaps is None)

# From the first live run: the model answered with arrows instead of pipes,
# nothing parsed, and the tool reported "nothing to fix" on a profile that had
# a real gap. Both halves of that are now covered.
for _sep, _label in [("|", "pipe"), ("→", "arrow"), ("->", "ascii arrow"),
                     ("—", "em dash"), (":", "colon")]:
    def _stub(prompt, *, system="", cfg=None, model=None, retries=2, _s=_sep):
        return "\n".join(
            f"Service {i} {_s} A description of the work, what it covers and "
            f"who it is for." for i in range(1, 4))
    llm.generate = _stub
    _f = fix.plan_services(kw_snap, CFG, None, kw_analysis)
    check(f"a {_label} separator is parsed", _f is not None
          and len(_f.body["serviceItems"]) >= 1,
          "returned None" if _f is None else "")

# THE LIVE BUG, and it had two halves.
#
# 1. `claude -p` is a full agent, not a text completion. With tools it can read
#    the working directory and act on what it finds.
# 2. Worse, and the actual cause: when gbp-autopilot is run from inside a
#    Claude Code session, the parent exports CLAUDE_CODE_SESSION_ID, a
#    CLAUDE_CODE_MESSAGING_SOCKET and friends. The nested `claude -p` picks
#    them up, JOINS the parent session, and answers the operator's
#    conversation instead of the prompt it was given. The planner was handed
#    back a markdown status report about this repo and split it on colons.
#
# Fixed in three places: the CLI runs with --tools "", it runs with the session
# environment stripped and from a neutral cwd, and nothing that fails to look
# like a service gets through the parser.
from gbp.fix import _reject_service  # noqa: E402
from gbp.llm import _isolated_env, _SESSION_ENV  # noqa: E402

_dirty = {"CLAUDECODE": "1", "CLAUDE_CODE_SESSION_ID": "abc",
          "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_CODE_MESSAGING_SOCKET": "/x",
          "CLAUDE_CODE_MESSAGING_TOKEN": "t", "AI_AGENT": "claude",
          "BAGGAGE": "x", "CLAUDE_PID": "9"}
_keep = {"PATH": "/usr/bin", "HOME": "/home/x", "USERPROFILE": "C:/Users/x",
         "APPDATA": "C:/x", "ANTHROPIC_API_KEY": "sk-x"}
_before = dict(os.environ)
os.environ.update(_dirty)
os.environ.update(_keep)
_clean_env = _isolated_env()

for _var in _dirty:
    check(f"session env stripped: {_var}", _var not in _clean_env)
for _var in _keep:
    check(f"kept for the CLI to work: {_var}", _clean_env.get(_var) == _keep[_var])
check("the session pattern is anchored, not a substring match",
      not _SESSION_ENV.match("MY_CLAUDE_SETTING"))
check("stripping does not mutate the real environment",
      "CLAUDE_CODE_SESSION_ID" in os.environ)
os.environ.clear()
os.environ.update(_before)

import inspect  # noqa: E402
_src = inspect.getsource(llm._via_cli)
check("the CLI is invoked with no tools", '"--tools", ""' in _src)
check("the CLI runs from a neutral cwd, not the project", "cwd=" in _src)
check("the CLI runs with the isolated environment",
      "env=_isolated_env()" in _src)

# The one that took longest to find, because it did not look like a bug. A
# multi-line prompt passed as a command-line ARGUMENT arrives truncated on
# Windows: the CLI saw only the first line. A full services brief came back as
# "Got it, Nour Solutions. What would you like me to do for it?" -- which reads
# like the model being unhelpful, not like the prompt never arriving. Sending
# the identical prompt on stdin returns the answer asked for.
check("the prompt is sent on stdin", "input=prompt" in _src,
      "a multi-line prompt in argv arrives truncated on Windows")
check("the prompt is NOT passed as an argv",
      '"-p", "--model"' in _src and '"-p", prompt' not in _src)
# Check what is actually put in the command, not what the comments mention --
# the comments explain why --append-system-prompt is wrong, so a plain
# substring search finds it and fails on the explanation.
_cmd_lines = [l for l in _src.splitlines()
              if "cmd" in l and ("+=" in l or "= [exe" in l)]
_cmd_src = "\n".join(_cmd_lines)
check("the system prompt REPLACES the agent prompt",
      "--system-prompt-file" in _cmd_src
      and "--append-system-prompt" not in _cmd_src,
      f"appending leaves the coding-agent persona in charge: {_cmd_src}")
# The system prompt is multi-line too, so it hits the same argv truncation as
# the user prompt. With only line one of SERVICES_SYSTEM the model returned a
# bare name and none of the format or grounding rules that follow it.
check("the system prompt goes in a file, not argv",
      "--system-prompt-file" in _cmd_src and '"--system-prompt",' not in _cmd_src)
check("no MCP servers are loaded", "--strict-mcp-config" in _src)
check("no session is left behind in the operator's history",
      "--no-session-persistence" in _src)

check("the exact live failure is rejected",
      bool(_reject_service("Audit", "90/100, 4 issues")),
      _reject_service("Audit", "90/100, 4 issues"))
check("a genuine service still passes",
      not _reject_service(
          "Boiler Repair",
          "Diagnostic and repair for gas and combi boilers across Durham."))
check("a service description containing standards still passes",
      not _reject_service(
          "ISO Certification Services",
          "Support with ISO 9001, 14001 and 45001 certification for "
          "companies in the Eastern Province."))
for _n, _d, _why in [
        ("X", "A description long enough to pass the length check here.",
         "one-character name"),
        ("Boiler Repair", "We fix boilers.", "one-line description"),
        ("Audit complete", "Everything finished without any problems at all.",
         "tool chatter"),
        ("12/100", "A description long enough to pass the length check here.",
         "a score as the name")]:
    check(f"rejected: {_why}", bool(_reject_service(_n, _d)))


def _garbage(prompt, *, system="", cfg=None, model=None, retries=2):
    return "Audit | 90/100, 4 issues"


llm.generate = _garbage
try:
    fix.plan_services(kw_snap, CFG, None, kw_analysis)
    check("garbage never becomes a proposed service", False, "it was accepted")
except llm.LLMError as exc:
    check("garbage never becomes a proposed service", True)
    check("and the rejection says why", "score" in str(exc).lower(), str(exc)[:80])


def _unparseable(prompt, *, system="", cfg=None, model=None, retries=2):
    return "Here are some thoughts about services but no structured lines."
llm.generate = _unparseable
try:
    fix.plan_services(kw_snap, CFG, None, kw_analysis)
    check("unreadable model output is reported, not swallowed", False,
          "returned quietly")
except llm.LLMError as exc:
    check("unreadable model output is reported, not swallowed", True)
    check("the error shows what came back", "thoughts" in str(exc))

llm.generate = stub_generate

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

# A post that Google rejects must NOT be reported as published. This cost a
# live post on a real client profile: the create call returned 200, the tool
# printed "posted", and the profile showed nothing.
_fc_rej = FakeClient()
_fc_rej.post_state = "REJECTED"
_rej_draft = posts.PostDraft(topic="t", text="Body of the post.",
                             cta_type="LEARN_MORE", cta_url="https://example.com")
_ok = posts.apply(_rej_draft, _fc_rej, "accounts/1", LOC, "111", dry_run=False)
check("a REJECTED post is reported as a failure, not a success", _ok is False)

_fc_live = FakeClient()
_live_draft = posts.PostDraft(topic="t", text="Body of the post.",
                              cta_type="LEARN_MORE", cta_url="https://example.com")
check("a LIVE post is still reported as published",
      posts.apply(_live_draft, _fc_live, "accounts/1", LOC, "111",
                  dry_run=False) is True)

# The whole reason the post was rejected.
_phone_draft = posts.PostDraft(topic="t", text="Ring us on 0327 0155503 today.",
                               cta_type="LEARN_MORE", cta_url="https://example.com")
posts.apply(_phone_draft, FakeClient(), "accounts/1", LOC, "111", dry_run=False)
check("a phone number is stripped before publishing",
      "0327" not in _phone_draft.text, _phone_draft.text)


print("\n" + "=" * 68)
print("6b. POSTS FROM SERVICE PAGES")

from gbp import site as site_mod  # noqa: E402

PAGE_TEXT = ("We repair gas and combi boilers across Durham. Most repairs are "
             "finished in a single visit. The call-out fee is 65 pounds and is "
             "deducted from the repair if you go ahead. We cover Durham, "
             "Chester-le-Street and Spennymoor.")


def page(url, h1, text=PAGE_TEXT):
    return site_mod.Page(url=url, h1=h1, title=h1, text=text,
                         headings=["What is included", "Areas we cover"])


P1 = "https://example.com/services/boiler-repair"
P2 = "https://example.com/services/blocked-drains"
SITE = site_mod.Site(
    base_url="https://example.com",
    home=page("https://example.com", "Northgate Plumbing"),
    services={P1: page(P1, "Boiler Repair in Durham"),
              P2: page(P2, "Blocked Drains in Durham")},
)

LOC2 = "locations/444"

# Topic selection must come from the service pages, not the profile services.
label, chosen = posts.choose_target(good_snapshot(), LOC2, CFG, SITE)
check("topic comes from a service page when URLs are configured",
      chosen is not None and chosen.url in (P1, P2), str(label))
check("the topic label is the page heading", "Durham" in label, label)

# Rotation: once one page is used, the next pick must be the other one.
db.record_action(LOC2, "post", P1, "first post")
_label2, chosen2 = posts.choose_target(good_snapshot(), LOC2, CFG, SITE)
check("the rotation moves to the page that has not been used",
      chosen2 is not None and chosen2.url == P2,
      chosen2.url if chosen2 else "none")

# A post written from a page carries the source and is grounded.
draft_p = posts.plan(good_snapshot(), LOC2, CFG, with_image=False,
                     site_data=SITE, url=P1)
check("an explicit --url is used as the source", draft_p.source_url == P1,
      str(draft_p.source_url))
check("the topic comes from that page", "Boiler Repair" in draft_p.topic,
      draft_p.topic)
check("a grounded post has no problems", draft_p.problems == [],
      str(draft_p.problems))

# Now the important one: a model that invents a number must not get published.
def stub_invents(prompt, *, system="", cfg=None, model=None, retries=2):
    return ("We have completed over 4,200 boiler repairs across Durham with a "
            "98% first-time fix rate.")


llm.generate = stub_invents
bad_draft = posts.plan(good_snapshot(), LOC2, CFG, with_image=False,
                       site_data=SITE, url=P1)
check("an invented number is caught", bool(bad_draft.problems),
      str(bad_draft.problems))
check("the problem names the numbers",
      any("4,200" in p or "98" in p for p in bad_draft.problems),
      str(bad_draft.problems))

fc4 = FakeClient()
published = posts.apply(bad_draft, fc4, "accounts/1", LOC2, "444",
                        dry_run=False)
check("an ungrounded post is NOT published", not published and not fc4.posts)
published = posts.apply(bad_draft, fc4, "accounts/1", LOC2, "444",
                        dry_run=False, force=True)
check("--force publishes it anyway", published and len(fc4.posts) == 1)

# A number that IS on the page must survive.
def stub_grounded(prompt, *, system="", cfg=None, model=None, retries=2):
    return ("If your boiler has stopped, the call-out fee is 65 pounds and "
            "comes off the repair. Most jobs are done in one visit.")


llm.generate = stub_grounded
ok_draft = posts.plan(good_snapshot(), LOC2, CFG, with_image=False,
                      site_data=SITE, url=P1)
check("a number taken from the page is allowed", ok_draft.problems == [],
      str(ok_draft.problems))

# Publishing records against the URL, so the rotation knows.
fc5 = FakeClient()
posts.apply(ok_draft, fc5, "accounts/1", LOC2, "444", dry_run=False)
check("a published post is recorded against its source URL",
      db.already_done(LOC2, "post", P1))

# With no site at all, it falls back to the profile's own services.
llm.generate = stub_generate
fallback = posts.plan(good_snapshot(), "locations/555", CFG, with_image=False,
                      site_data=None)
check("with no website it still writes a post", bool(fallback.text))
check("with no website there is no source URL", fallback.source_url is None)

llm.generate = stub_generate

print("\n" + "=" * 68)
print("7. IMAGES (no network)")
prompt = images.build_prompt("Boiler repair", "Durham")
check("image prompt names the service", "boiler repair" in prompt.lower())
check("image prompt names the city", "Durham" in prompt)
check("image prompt forbids text in the image", "no text" in prompt.lower())
check("images are off by default in this config",
      images.generate("x", "y", "z", CFG) is None)

detail = images.detail_from_page(page(P1, "Boiler Repair in Durham"))
check("a source page gives the image prompt real direction",
      "Boiler Repair in Durham" in detail, detail)
check("the image prompt picks up the page's sections",
      "What is included" in detail, detail)
check("no page means no extra direction", images.detail_from_page(None) == "")
enriched = images.build_prompt("Boiler repair", "Durham", detail)
check("the enriched prompt still forbids text in the image",
      "no text" in enriched.lower())

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
