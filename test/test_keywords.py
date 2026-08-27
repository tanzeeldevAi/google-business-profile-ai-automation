#!/usr/bin/env python3
"""Search-term parsing, coverage, clustering and the rules built on them.

Offline. The API payload is a fixture; nothing is fetched.

    python test/test_keywords.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))

from gbp import keywords as kw, rules  # noqa: E402
from fixtures import good_snapshot  # noqa: E402

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")


# Shaped exactly like the Performance API returns it. Note the mix of exact
# `value` counts and privacy `threshold` counts -- most real terms are the
# latter, and a tool that drops them throws away the long tail.
RAW = [
    {"searchKeyword": "plumber durham", "insightsValue": {"value": "820"}},
    {"searchKeyword": "northgate plumbing", "insightsValue": {"value": "410"}},
    {"searchKeyword": "emergency plumber durham",
     "insightsValue": {"value": "260"}},
    {"searchKeyword": "boiler repair durham", "insightsValue": {"value": "175"}},
    {"searchKeyword": "blocked drain durham", "insightsValue": {"value": "90"}},
    {"searchKeyword": "boiler repair near me",
     "insightsValue": {"threshold": "15"}},
    {"searchKeyword": "emergency boiler repair",
     "insightsValue": {"threshold": "15"}},
    {"searchKeyword": "underfloor heating installation",
     "insightsValue": {"threshold": "15"}},
    {"searchKeyword": "northgate plumbing opening hours",
     "insightsValue": {"threshold": "15"}},
    {"searchKeyword": "power flush durham", "insightsValue": {"threshold": "15"}},
    {"searchKeyword": "opening hours", "insightsValue": {"threshold": "15"}},
    {"searchKeyword": "", "insightsValue": {"value": "5"}},
    {"searchKeyword": "no value term", "insightsValue": {}},
]

print("\n== parsing ==")
parsed = kw.parse(RAW)
check("blank terms are dropped", all(k.term for k in parsed))
check("every other term survives", len(parsed) == 12, str(len(parsed)))
check("exact counts are read", parsed[0].impressions == 820 and parsed[0].exact)
check("exact counts sort first", parsed[0].term == "plumber durham",
      parsed[0].term)
thresholded = [k for k in parsed if not k.exact]
check("threshold counts are kept", len(thresholded) >= 6, str(len(thresholded)))
check("a threshold is labelled as a maximum",
      any(k.label.startswith("<") for k in thresholded))
check("an exact count is labelled plainly", parsed[0].label == "820",
      parsed[0].label)
check("a missing insightsValue does not crash",
      any(k.term == "no value term" for k in parsed))
check("parsing is empty-safe", kw.parse([]) == [] and kw.parse(None) == [])

print("\n== coverage against the profile ==")
snap = good_snapshot()
# The good fixture lists generic "Service 0..5", so nothing service-specific is
# covered. Give it two real ones so coverage has something to find.
snap.location["serviceItems"] = [
    {"freeFormServiceItem": {"label": {
        "displayName": "Emergency plumbing",
        "description": "Burst pipes and no heating, same day."}}},
    {"freeFormServiceItem": {"label": {
        "displayName": "Blocked drains",
        "description": "Drain clearing and CCTV surveys."}}},
]
analysis = kw.analyse(parsed, snap)

by_term = {c.keyword.term: c for c in analysis.coverage}

check("a brand search is identified",
      by_term["northgate plumbing"].is_brand)
check("a brand search with extra words is still brand",
      by_term["northgate plumbing opening hours"].is_brand)
check("a generic term is not brand", not by_term["plumber durham"].is_brand)

check("a term covered by a service is marked covered",
      by_term["emergency plumber durham"].covered,
      str(by_term["emergency plumber durham"].places))
check("it says WHERE it is covered",
      "services" in by_term["emergency plumber durham"].places,
      str(by_term["emergency plumber durham"].places))
check("the city is not required to appear",
      by_term["blocked drain durham"].covered,
      str(by_term["blocked drain durham"].places))

check("a term nowhere on the profile is a gap",
      not by_term["underfloor heating installation"].covered,
      str(by_term["underfloor heating installation"].places))
check("power flush is a gap", not by_term["power flush durham"].covered)

check("matching only the business name is not coverage",
      by_term["plumber durham"].places != ["business name"],
      str(by_term["plumber durham"].places))

print("\n== the numbers the report uses ==")
check("brand and discovery are separated",
      len(analysis.brand) >= 2 and len(analysis.discovery) >= 8,
      f"{len(analysis.brand)} brand, {len(analysis.discovery)} discovery")
check("gaps exclude brand terms",
      all(not c.is_brand for c in analysis.gaps))
check("gaps are biggest first",
      [c.keyword.impressions for c in analysis.gaps if c.keyword.exact]
      == sorted([c.keyword.impressions for c in analysis.gaps
                 if c.keyword.exact], reverse=True))
check("coverage rate is a fraction", 0.0 <= analysis.covered_rate <= 1.0,
      str(analysis.covered_rate))
check("missed impressions only counts gaps",
      analysis.missed_impressions <= analysis.total_impressions)
check("total impressions adds up",
      analysis.total_impressions == sum(k.impressions for k in parsed))

print("\n== the stemmer, which is what coverage stands on ==")
# A length-relative trim breaks these pairs, which is exactly the bug that
# reported "emergency plumber" as a gap on a profile that offers it.
for a, b in [("plumber", "plumbing"), ("drain", "drains"),
             ("drain", "draining"), ("install", "installation"),
             ("boiler", "boilers"), ("repair", "repairs"),
             ("heat", "heating"), ("electrician", "electrical")]:
    check(f"{a} and {b} stem the same", kw._stem(a) == kw._stem(b),
          f"{kw._stem(a)} vs {kw._stem(b)}")
check("short words are left alone", kw._stem("gas") == "gas")
check("power is not over-stemmed to pow", kw._stem("power") == "power")

print("\n== clustering into services ==")
# Built directly rather than taken from the fixture, so the grouping is
# tested on its own terms.
CLUSTER_GAPS = [
    kw.Coverage(kw.Keyword("boiler repair durham", 175), False, []),
    kw.Coverage(kw.Keyword("boiler repair near me", 15, exact=False), False, []),
    kw.Coverage(kw.Keyword("emergency boiler repair", 15, exact=False),
                False, []),
    kw.Coverage(kw.Keyword("underfloor heating installation", 40), False, []),
    kw.Coverage(kw.Keyword("power flush durham", 15, exact=False), False, []),
]
groups = kw.cluster(CLUSTER_GAPS, drop={"durha"})
check("gaps are grouped", len(groups) >= 2, str(len(groups)))
check("groups are biggest first",
      [g["impressions"] for g in groups]
      == sorted([g["impressions"] for g in groups], reverse=True))
boiler = [g for g in groups if any("boiler" in k.term for k in g["terms"])]
check("all three boiler variants land in one group",
      len(boiler) == 1 and len(boiler[0]["terms"]) == 3,
      str([[k.term for k in g["terms"]] for g in groups]))
check("the boiler group sums its impressions",
      boiler[0]["impressions"] == 205, str(boiler[0]["impressions"]))
check("an unrelated term gets its own group",
      any(len(g["terms"]) == 1 and "underfloor" in g["terms"][0].term
          for g in groups))

groups_from_fixture = kw.cluster(analysis.gaps, drop=analysis.drop_stems)
check("a group carries its own impressions",
      all(g["impressions"] >= 0 for g in groups_from_fixture))

print("\n== not everything is a service ==")
hours_only = kw.cluster([c for c in analysis.coverage
                         if c.keyword.term == "opening hours"])
check("'opening hours' is rejected as a service",
      all(not kw.worth_a_service(g) for g in hours_only),
      str(hours_only))
check("a real job is accepted as a service",
      any(kw.worth_a_service(g) for g in groups))

print("\n== the block handed to the post writer ==")
block = kw.summarise(analysis)
check("the block lists gap terms", "underfloor heating" in block, block[:120])
check("the block tells the writer not to force them",
      "does not fit" in block or "genuinely" in block)
check("no gaps means no block",
      kw.summarise(kw.Analysis(keywords=[], coverage=[])) == "")

print("\n== the snapshot summary ==")
summary = kw.to_snapshot_dict(analysis)
for key in ("total", "discovery", "impressions", "covered_rate", "gap_count",
            "missed_impressions", "top_gap", "gaps", "top_terms"):
    check(f"summary has {key}", key in summary)
check("top_gap is the biggest uncovered term",
      summary["top_gap"]["term"] == analysis.gaps[0].keyword.term)
check("summary is JSON-shaped",
      all(not hasattr(v, "__dataclass_fields__")
          for v in summary.values() if not isinstance(v, (list, dict))))

print("\n== the rules ==")


def with_kw(summary_dict, available=True):
    s = good_snapshot()
    s.keywords = summary_dict
    if not available:
        s.available = s.available - {"keywords"}
    return {f.rule_id: f for f in rules.run_all(s, {})}


poor = with_kw(dict(summary, covered_rate=0.1, discovery=10, gap_count=9))
check("KW2 fails on poor coverage", not poor["KW2"].passed, poor["KW2"].detail)
check("KW2 says the percentage", "%" in poor["KW2"].detail)
check("KW2 is auto-fixable via services", poor["KW2"].fix_key == "services")
check("KW2 points at run.py fix", poor["KW2"].command == "run.py fix")

great = with_kw(dict(summary, covered_rate=0.95, discovery=10, gap_count=0,
                     top_gap=None))
check("KW2 passes on good coverage", great["KW2"].passed)
check("KW3 passes when nothing big is missing", great["KW3"].passed)
check("KW3 fails when a big term is missing", not poor["KW3"].passed)
check("KW3 names the term", summary["top_gap"]["term"] in poor["KW3"].detail,
      poor["KW3"].detail)

thin = with_kw(dict(summary, discovery=2))
check("KW2 does not judge a profile with too few terms",
      thin["KW2"].informational, thin["KW2"].detail)

missing = with_kw({}, available=False)
for rid in ("KW1", "KW2", "KW3"):
    check(f"{rid} is informational when not fetched", missing[rid].informational)
    check(f"{rid} scores nothing when not fetched", missing[rid].points == 0)

check("KW1 is always informational", with_kw(summary)["KW1"].informational)
check("KW1 reports the totals", "term(s)" in with_kw(summary)["KW1"].detail)

print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f in fails:
    print(f"  x {f}")
sys.exit(1 if fails else 0)
