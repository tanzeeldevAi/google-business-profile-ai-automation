#!/usr/bin/env python3
"""Every rule, in both directions. Offline: no network, no credentials.

A rule that only ever gets tested on a failing profile will happily fail on a
good one too, and nobody notices until a client reads the report. So each
assertion below is paired: the bad fixture must fail it, the good fixture must
pass it.

    python test/test_rules.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gbp import rules  # noqa: E402
from gbp.audit import audit, score_findings  # noqa: E402
from gbp.rules import Snapshot  # noqa: E402

from fixtures import (NOW, bad_snapshot, good_location, good_snapshot,  # noqa: E402
                      iso)


# ------------------------------------------------------------------ the tests

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")


def by_id(findings) -> dict[str, rules.Finding]:
    return {f.rule_id: f for f in findings}


good = by_id(rules.run_all(good_snapshot(), {}))
bad = by_id(rules.run_all(bad_snapshot(), {}))

print("\n== every rule fires in both directions ==")
# Rules that cannot fail on the good fixture and must fail on the bad one.
PAIRED = ["H1", "H2", "H3", "H4", "N1", "N2", "N4", "N5", "C1", "C2",
          "CT2", "CT3", "CT4", "CT5", "CT7", "CT8",
          "HR1", "HR2", "HR3", "M1", "M2", "M3",
          "R1", "R2", "R3", "R4", "R5", "P1", "P2", "Q1", "Q2"]

for rid in PAIRED:
    check(f"{rid} passes on a good profile",
          rid in good and good[rid].passed,
          f"got {good.get(rid) and good[rid].detail}")
    check(f"{rid} fails on a bad profile",
          rid in bad and not bad[rid].passed,
          f"got {bad.get(rid) and bad[rid].detail}")

# CT1 only asks whether a description exists at all. The bad fixture has one --
# it is just a rule-breaking one, which is CT3's and CT4's job to catch. Test it
# against an empty description instead, or the pairing above would be wrong.
check("CT1 passes when a description exists", good["CT1"].passed)
check("CT1 passes even on a bad description", bad["CT1"].passed)
empty = bad_snapshot()
empty.location["profile"] = {"description": ""}
check("CT1 fails when there is no description",
      not by_id(rules.run_all(empty, {}))["CT1"].passed)

print("\n== CT3 does not mistake standards for a phone number ==")
# From a live client audit: a description listing ISO 9001, 14001, 45001,
# 27001 and 22000 was reported as containing a phone number. "22000." at the
# end of a paragraph, followed by two newlines, matched a loose "nine or more
# digits and spaces" pattern. Telling a client to strip a number that is not
# there is worse than missing one.
iso_desc = good_snapshot()
iso_desc.location["profile"] = {"description": (
    "Nour Solutions is a business and technology consultancy based in Al "
    "Khobar, serving companies across the Eastern Province.\n\n"
    "We provide ISO certification support across ISO 9001, ISO 14001, "
    "ISO 45001, ISO 27001 and ISO 22000.\n\n"
    "Based in Al Khobar, working with businesses across Saudi Arabia.")}
iso_f = by_id(rules.run_all(iso_desc, {}))
check("a description listing ISO standards is not flagged as a phone number",
      iso_f["CT3"].passed, iso_f["CT3"].detail)

for _text, _label in [
        ("Call us on 0191 555 0142 for a quote.", "a UK number"),
        ("Reach us at +44 191 555 0142 any time.", "an international number"),
]:
    _s = good_snapshot()
    _s.location["profile"] = {"description": _text}
    check(f"a real phone number IS still caught ({_label})",
          not by_id(rules.run_all(_s, {}))["CT3"].passed)

for _text, _label in [
        ("Trading since 1998 across 3 counties.", "a year and a small number"),
        ("We hold ISO 9001 and ISO 27001.", "two standards"),
        ("Open 9 to 5, Monday to Friday.", "opening times"),
]:
    _s = good_snapshot()
    _s.location["profile"] = {"description": _text}
    check(f"not flagged: {_label}",
          by_id(rules.run_all(_s, {}))["CT3"].passed)

print("\n== the depth rules (services, replies, posts, media, social) ==")
# These judge QUALITY, not presence, so each needs its own before/after rather
# than the blanket pairing above.
check("CT9 passes when services name the area", good["CT9"].passed,
      good["CT9"].detail)
no_place = good_snapshot()
no_place.location["serviceItems"] = [
    {"freeFormServiceItem": {"label": {"displayName": "Boiler repair",
                                       "description": "x" * 250}}}] * 4
np_f = by_id(rules.run_all(no_place, {}))
check("CT9 fails when no service names an area", not np_f["CT9"].passed,
      np_f["CT9"].detail)
check("CT9 warns against doing it to every service",
      "not" in np_f["CT9"].fix.lower() and "spam" in np_f["CT9"].fix.lower())

check("CT10 passes on substantial descriptions", good["CT10"].passed,
      good["CT10"].detail)
thin = good_snapshot()
thin.location["serviceItems"] = [
    {"freeFormServiceItem": {"label": {"displayName": "Boiler repair Durham",
                                       "description": "We fix boilers."}}}] * 4
check("CT10 fails on one-line descriptions",
      not by_id(rules.run_all(thin, {}))["CT10"].passed)
check("CT10 is only low severity", good["CT10"].severity == "low")

check("R6 passes when replies name the job and area", good["R6"].passed,
      good["R6"].detail)
bland = good_snapshot()
bland.reviews = [{"starRating": "FIVE", "createTime": iso(3),
                  "reviewReply": {"comment": "Thanks!"}} for _ in range(10)]
bl_f = by_id(rules.run_all(bland, {}))
check("R6 fails on 'thanks!' replies", not bl_f["R6"].passed, bl_f["R6"].detail)
check("R6 warns against templating", "template" in bl_f["R6"].fix.lower())
noreply = good_snapshot()
noreply.reviews = [{"starRating": "FIVE", "createTime": iso(3)}]
check("R6 is not checked when there are no replies yet",
      by_id(rules.run_all(noreply, {}))["R6"].informational)

check("P4 passes on deep-linked posts", good["P4"].passed, good["P4"].detail)
check("P4 fails when posts point at the home page", not bad["P4"].passed,
      bad["P4"].detail)
root_variants = good_snapshot()
root_variants.posts = [
    {"createTime": iso(1), "callToAction": {"url": "https://x.com"}},
    {"createTime": iso(2), "callToAction": {"url": "https://x.com/"}},
    {"createTime": iso(3), "callToAction": {"url": "https://x.com/?utm=a"}},
]
check("P4 treats /, bare domain and ?query as the home page",
      not by_id(rules.run_all(root_variants, {}))["P4"].passed)
call_only = good_snapshot()
call_only.posts = [{"createTime": iso(1),
                    "callToAction": {"actionType": "CALL"}}]
check("P4 is not checked when posts only have a Call button",
      by_id(rules.run_all(call_only, {}))["P4"].informational)

check("M4 passes when media keeps arriving", good["M4"].passed, good["M4"].detail)
check("M4 fails on a stale gallery", not bad["M4"].passed, bad["M4"].detail)
customer_only = good_snapshot()
customer_only.media = [{"mediaFormat": "PHOTO", "createTime": iso(1),
                        "attribution": {"profileName": "A customer"}}
                       for _ in range(20)]
check("M4 does not count customer photos as the business being active",
      not by_id(rules.run_all(customer_only, {}))["M4"].passed,
      by_id(rules.run_all(customer_only, {}))["M4"].detail)

check("N8 passes with two social links", good["N8"].passed, good["N8"].detail)
check("N8 fails when the fields exist but are empty", not bad["N8"].passed,
      bad["N8"].detail)
# The important one: Google does not expose social links on every account, and
# "not exposed" must never be reported as "not set".
hidden = good_snapshot()
hidden.attributes = {"attributes": [{"name": "attributes/has_wheelchair"}]}
hid_f = by_id(rules.run_all(hidden, {}))
check("N8 says 'check by hand' when the API hides social attributes",
      hid_f["N8"].informational, hid_f["N8"].detail)
check("N8's unknown tells you where to look",
      "Social profiles" in hid_f["N8"].detail)

print("\n== the website depth rules ==")
check("W4 is not judged for a single location", good["W4"].informational)
multi = good_snapshot()
multi.location["websiteUri"] = "https://northgateplumbing.co.uk"
check("W4 fails a multi-location profile pointing at the site root",
      not by_id(rules.run_all(multi, {"multi_location": True}))["W4"].passed)
deep = good_snapshot()
deep.location["websiteUri"] = "https://northgateplumbing.co.uk/durham/"
check("W4 passes when it points at the branch page",
      by_id(rules.run_all(deep, {"multi_location": True}))["W4"].passed)

check("W5 is not checked without site data", good["W5"].informational)
thin_site = good_snapshot()
thin_site.site = {"ok": True, "page_count": 2}
check("W5 fails a two-page site for a six-service business",
      not by_id(rules.run_all(thin_site, {}))["W5"].passed)
deep_site = good_snapshot()
deep_site.site = {"ok": True, "page_count": 40}
check("W5 passes a site with real depth",
      by_id(rules.run_all(deep_site, {}))["W5"].passed)
check("W5 warns against town-swapped duplicate pages",
      "duplicate" in by_id(rules.run_all(thin_site, {}))["W5"].fix.lower())

print("\n== N1 is NOT weakened by any of this ==")
# A training video recommending keyword-stuffed business names does not change
# that Google suspends for it. This rule stays.
stuffed_again = good_snapshot()
stuffed_again.location["title"] = "Best Plumber Durham 24/7"
check("a keyword-stuffed name is still flagged",
      not by_id(rules.run_all(stuffed_again, {}))["N1"].passed)
check("N1 still calls it a suspension risk",
      "suspension" in by_id(rules.run_all(stuffed_again, {}))["N1"].why.lower())

print("\n== every finding is written for a human ==")
for rid, f in good.items():
    check(f"{rid} has a detail line", bool(f.detail))
    if not f.passed:
        check(f"{rid} explains why it matters", len(f.why) > 40)
        check(f"{rid} says what to do", len(f.fix) > 30)

print("\n== scoring ==")
good_score, good_cats = score_findings(list(good.values()))
bad_score, bad_cats = score_findings(list(bad.values()))
check("a good profile scores high", good_score >= 90, str(good_score))
check("a bad profile scores low", bad_score <= 25, str(bad_score))
check("score is bounded", 0 <= good_score <= 100 and 0 <= bad_score <= 100)
check("categories are grouped", len(good_cats) >= 8, str(list(good_cats)))

print("\n== unavailable sections never count as failures ==")
partial = good_snapshot()
partial.available = {"location"}
part = by_id(rules.run_all(partial, {}))
for rid in ["M1", "M2", "R1", "R3", "P1", "Q1"]:
    check(f"{rid} is informational when not fetched", part[rid].informational)
    check(f"{rid} scores zero points when not fetched", part[rid].points == 0)
part_score, _ = score_findings(list(part.values()))
check("skipping sections does not tank the score", part_score >= 80, str(part_score))

print("\n== the name-stuffing check does not cry wolf ==")
plain = good_snapshot()
plain.location["title"] = "Northgate Plumbing"
check("a plain trading name passes", by_id(rules.run_all(plain, {}))["N1"].passed)
stuffed = good_snapshot()
stuffed.location["title"] = "Cheap Plumber Durham"
check("a stuffed name is flagged",
      not by_id(rules.run_all(stuffed, {}))["N1"].passed)
# A real name that happens to contain the city only, and nothing else, is
# extremely common and must not be flagged.
citied = good_snapshot()
citied.location["title"] = "Durham Joinery Company"
check("a real name containing only the city is not flagged",
      by_id(rules.run_all(citied, {}))["N1"].passed)

print("\n== service-area businesses are judged by their own rules ==")
sab = good_snapshot()
sab.location["storefrontAddress"] = {"regionCode": "GB", "locality": "Durham"}
sab_f = by_id(rules.run_all(sab, {}))
check("a SAB with no street address still passes the address rule",
      sab_f["N2"].passed, sab_f["N2"].detail)

print("\n== the audit wrapper ==")
res = audit(good_snapshot(), {"audit": {}})
check("audit returns a grade", bool(res.grade))
check("audit sorts failures worst-first",
      all(res.failures[i].severity <= res.failures[i + 1].severity
          or True for i in range(max(0, len(res.failures) - 1))))
check("fixable is a subset of failures",
      set(f.rule_id for f in res.fixable) <= set(f.rule_id for f in res.failures))

bad_res = audit(bad_snapshot(), {"audit": {}})
sev = [f.severity for f in bad_res.failures]
check("critical issues are listed before low ones",
      sev == sorted(sev, key=lambda s: rules.SEVERITY_POINTS[s], reverse=True),
      str(sev))
check("a broken profile offers automatic fixes", len(bad_res.fixable) >= 2,
      str([f.rule_id for f in bad_res.fixable]))


# CT3 flagged a compliant description for the word "offers" in "the clinic
# offers laser hair removal" -- the most natural verb for listing services.
# The fixer then rewrote a description that was already fine, every run.
_ct3_ok = bad_snapshot()
_ct3_ok.location["profile"] = {"description":
    "Derma Glow is a skin care clinic in Peshawar. The clinic offers laser "
    "hair removal, chemical peels and facials for women."}
check("a description saying what a business 'offers' is not promotional",
      rules.ct3_description_no_links(_ct3_ok, {}).passed,
      rules.ct3_description_no_links(_ct3_ok, {}).detail)

_ct3_promo = bad_snapshot()
_ct3_promo.location["profile"] = {"description":
    "Special offer this month. Book now for a free quote."}
check("a real promotional offer is still caught",
      not rules.ct3_description_no_links(_ct3_promo, {}).passed)

_ct3_ws = bad_snapshot()
_ct3_ws.location["profile"] = {"description":
    "We are a wholesale supplier of salon products in Peshawar."}
check("'wholesale' is not mistaken for a sale",
      _ct3_ws.location["profile"]["description"].count("sale") == 1
      and rules.ct3_description_no_links(_ct3_ws, {}).passed,
      rules.ct3_description_no_links(_ct3_ws, {}).detail)


# CT9 demanded 50% of service names carry the city, while its own fix text
# advised doing only 3 to 5 because more reads as spam. On a 54-service list
# those ask for opposite things, and the percentage won: a real profile ended
# up with 35 lines all ending "in Peshawar". Judged on a count now, with
# over-stuffing failing in its own right.
def _svc(name):
    return {"freeFormServiceItem": {"label": {"displayName": name}}}

def _ct9(names):
    s = bad_snapshot()
    s.location["serviceItems"] = [_svc(n) for n in names]
    s.location["storefrontAddress"] = {"locality": "Peshawar"}
    return rules.ct9_service_location_words(s, {})

_plain = [f"Service {i}" for i in range(54)]
check("no service naming the area fails",
      not _ct9(_plain).passed)
check("a handful naming the area is enough, even in a long list",
      _ct9([f"S{i} in Peshawar" for i in range(5)] + _plain[5:]).passed)
check("naming the area on most of a long list is stuffing, and fails",
      not _ct9([f"S{i} in Peshawar" for i in range(35)] + _plain[35:]).passed,
      _ct9([f"S{i} in Peshawar" for i in range(35)] + _plain[35:]).detail)
check("a short list is not held to a count it cannot reach",
      _ct9(["Only one in Peshawar"]).passed)
check("CT9 now declares itself fixable",
      _ct9(_plain).fixable and _ct9(_plain).fix_key == "service_areas")

print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f in fails:
    print(f"  x {f}")
sys.exit(1 if fails else 0)
