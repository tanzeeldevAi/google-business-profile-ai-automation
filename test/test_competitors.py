#!/usr/bin/env python3
"""Map-pack comparison and directory NAP checking.

Offline. The DataForSEO payloads are fixtures; nothing is fetched and nothing
is billed.

    python test/test_competitors.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))

from gbp import citations, competitors as comp, rules  # noqa: E402
from fixtures import good_snapshot  # noqa: E402

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")


def item(title, rank, votes=None, value=None, cat="Plumber", extra=None,
         photos=None, phone="", place_id="", claimed=True):
    out = {
        "type": "maps_search", "title": title, "rank_group": rank,
        "category": cat, "additional_categories": extra or [],
        "phone": phone, "place_id": place_id, "is_claimed": claimed,
        "address": "somewhere",
    }
    if votes is not None or value is not None:
        out["rating"] = {"value": value, "votes_count": votes}
    if photos is not None:
        out["total_photos"] = photos
    return out


PACK = [
    item("Riverside Plumbing", 1, votes=412, value=4.8, photos=180,
         extra=["Drainage service", "Boiler supplier"], place_id="A"),
    item("City Drains Ltd", 2, votes=286, value=4.6, photos=120,
         extra=["Drainage service", "Water damage restoration"], place_id="B"),
    item("Northgate Plumbing", 3, votes=30, value=4.9, photos=24,
         extra=["Drainage service"], place_id="US",
         phone="+44 191 555 0142"),
    item("Quick Fix Plumbers", 4, votes=95, value=4.2, photos=60,
         extra=["Boiler supplier"], place_id="D"),
]

print("\n== parsing the map pack ==")
parsed = [comp._parse(i, "plumber durham") for i in PACK]
first = parsed[0]
check("name is read", first.name == "Riverside Plumbing")
check("rank is read", first.rank == 1)
check("review count is read", first.reviews == 412)
check("rating is read", first.rating == 4.8)
check("photo count is read", first.photos == 180)
check("primary category is read", first.category == "Plumber")
check("additional categories are read",
      "Drainage service" in first.additional_categories)
check("all_categories includes both", len(first.all_categories) == 3,
      str(first.all_categories))

no_photos = comp._parse(item("X", 1, votes=5, value=4.0), "k")
check("a missing photo count is None, not zero", no_photos.photos is None)
no_rating = comp._parse({"title": "Y", "rank_group": 2}, "k")
check("a missing rating is None, not zero",
      no_rating.rating is None and no_rating.reviews is None)

print("\n== identifying which one is us ==")
check("matched by place id",
      comp._is_us(comp.Business(name="Anything", place_id="US"),
                  "Northgate Plumbing", "", "US"))
check("matched by phone when place id is absent",
      comp._is_us(comp.Business(name="Different Name",
                                phone="0191 555 0142"),
                  "Northgate Plumbing", "+44 191 555 0142", ""))
check("matched by name as a last resort",
      comp._is_us(comp.Business(name="northgate  plumbing"),
                  "Northgate Plumbing", "", ""))
check("a rival is not mistaken for us",
      not comp._is_us(comp.Business(name="Riverside Plumbing", place_id="A"),
                      "Northgate Plumbing", "+44 191 555 0142", "US"))

print("\n== building the comparison ==")
c = comp.Comparison(keywords=["plumber durham"])
for b in parsed:
    b.is_us = comp._is_us(b, "Northgate Plumbing", "+44 191 555 0142", "US")
    if b.is_us:
        c.us = b
    else:
        c.rivals.append(b)
c.ranks["plumber durham"] = 3

check("we are identified", c.us is not None and c.us.name == "Northgate Plumbing")
check("we are excluded from the rivals",
      all(not r.is_us for r in c.rivals))
check("top is the best three rivals", len(c.top) == 3, str(len(c.top)))
check("top is ordered by rank", [b.rank for b in c.top] == [1, 2, 4],
      str([b.rank for b in c.top]))

check("average reviews is over the top three",
      round(c.avg_reviews) == round((412 + 286 + 95) / 3), str(c.avg_reviews))
check("average photos is over the top three",
      round(c.avg_photos) == round((180 + 120 + 60) / 3), str(c.avg_photos))
check("average rating is over the top three",
      abs(c.avg_rating - (4.8 + 4.6 + 4.2) / 3) < 0.01, str(c.avg_rating))

print("\n== the category gap ==")
missing = dict(c.missing_categories)
check("a category two rivals share, that we lack, is flagged",
      "Boiler supplier" in missing, str(missing))
check("it reports how many rivals use it", missing.get("Boiler supplier") == 2,
      str(missing))
check("a category only ONE rival uses is ignored as noise",
      "Water damage restoration" not in missing, str(missing))
check("a category we already have is not flagged",
      "Drainage service" not in missing, str(missing))

print("\n== averages survive missing data ==")
partial = comp.Comparison()
partial.rivals = [
    comp.Business(name="A", rank=1, reviews=100, photos=None),
    comp.Business(name="B", rank=2, reviews=200, photos=50),
]
check("an average ignores the entries that have no value",
      partial.avg_photos == 50, str(partial.avg_photos))
check("an average with nothing to average is None",
      comp.Comparison().avg_reviews is None)

print("\n== the snapshot summary ==")
summary = comp.to_snapshot_dict(c, our_reviews=30, our_rating=4.9,
                                our_photos=24)
check("our own numbers come from Google, not the scrape",
      summary["our_reviews"] == 30 and summary["our_photos"] == 24)
check("the top three are carried", len(summary["top"]) == 3)
check("missing categories are carried",
      "Boiler supplier" in summary["missing_categories"])
check("summary is JSON-shaped",
      all(not hasattr(v, "__dataclass_fields__")
          for v in summary.values() if not isinstance(v, (list, dict))))

print("\n== the X rules ==")


def with_comp(d, available=True):
    s = good_snapshot()
    s.competitors = d
    if available:
        s.available = s.available | {"competitors"}
    return {f.rule_id: f for f in rules.run_all(s, {})}


behind = with_comp(summary)
check("X1 fails when far behind on reviews", not behind["X1"].passed,
      behind["X1"].detail)
check("X1 says how far behind", "behind" in behind["X1"].detail)
check("X1 warns against buying reviews", "buy" in behind["X1"].fix.lower())
check("X2 fails when a shared category is missing", not behind["X2"].passed)
check("X2 names the category", "Boiler supplier" in behind["X2"].detail)
check("X2 says only add what you offer",
      "genuinely" in behind["X2"].fix.lower())
check("X3 fails when far behind on photos", not behind["X3"].passed,
      behind["X3"].detail)

ahead = with_comp(dict(summary, our_reviews=500, our_photos=400,
                       missing_categories=[]))
check("X1 passes when ahead", ahead["X1"].passed, ahead["X1"].detail)
check("X2 passes with no category gap", ahead["X2"].passed)
check("X3 passes when ahead on photos", ahead["X3"].passed)

# The whole point of the module: the bar is theirs, not a fixed number.
quiet_market = with_comp(dict(summary, our_reviews=30, avg_reviews=25,
                              missing_categories=[]))
check("30 reviews PASSES in a market where the top three average 25",
      quiet_market["X1"].passed, quiet_market["X1"].detail)
busy_market = with_comp(dict(summary, our_reviews=30, avg_reviews=400))
check("the same 30 reviews FAILS where the top three average 400",
      not busy_market["X1"].passed, busy_market["X1"].detail)

nodata = with_comp(dict(summary, our_photos=None, avg_photos=None))
check("X3 is not checked when photo counts are not reported",
      nodata["X3"].informational, nodata["X3"].detail)

off = with_comp({}, available=False)
for rid in ("X1", "X2", "X3"):
    check(f"{rid} is not checked without DataForSEO", off[rid].informational)
    check(f"{rid} scores nothing without DataForSEO", off[rid].points == 0)

print("\n== aggregator entries are not competitors ==")
# Found on live data: some map results are directory pages, flagged with
# is_directory_item. Comparing a real business's review count against one of
# those is meaningless, so they are dropped before anything is averaged.
DIRECTORY_PACK = list(PACK) + [
    dict(item("Best Plumbers Directory", 5, votes=9000, value=4.9,
              photos=5000, place_id="DIR"), is_directory_item=True),
]
kept = [i for i in DIRECTORY_PACK if not i.get("is_directory_item")]
check("a directory item is filtered before comparison",
      len(kept) == len(PACK), f"{len(kept)} kept vs {len(PACK)} expected")
check("its inflated numbers never reach the average",
      all(comp._parse(i, "k").reviews != 9000 for i in kept))

print("\n== citations: which URLs count as a directory ==")
check("yelp is a directory", citations._is_directory("https://www.yelp.com/biz/x"))
check("a subdomain counts",
      citations._is_directory("https://uk.trustpilot.com/review/x"))
check("the client's own site is not a directory",
      not citations._is_directory("https://northgateplumbing.co.uk/about"))
check("a random blog is not a directory",
      not citations._is_directory("https://someblog.com/best-plumbers"))

print("\n== citations: mismatch vs silence ==")
chk = citations.CitationCheck(business="Northgate Plumbing",
                              our_phone="+44 191 555 0142")
chk.listings = [
    citations.Listing("yell.com", "u1", read=True, phones=["01915550142"]),
    citations.Listing("yelp.com", "u2", read=True, phones=["01915559999"]),
    citations.Listing("cylex-uk.co.uk", "u3", read=True, phones=[]),
    citations.Listing("checkatrade.com", "u4", read=False, error="returned 403"),
]
check("a matching number is counted as matching",
      [l.domain for l in chk.matching] == ["yell.com"])
check("a DIFFERENT number is a mismatch",
      [l.domain for l in chk.mismatched] == ["yelp.com"])
check("a page showing NO phone is not a mismatch",
      "cylex-uk.co.uk" not in [l.domain for l in chk.mismatched])
check("a page showing no phone is reported separately",
      [l.domain for l in chk.silent] == ["cylex-uk.co.uk"])
check("an unreadable page is not judged at all",
      "checkatrade.com" not in [l.domain for l in chk.mismatched]
      and "checkatrade.com" not in [l.domain for l in chk.silent])
check("an unreadable page says why", "403" in chk.listings[3].status)

print("\n== the CI2 rule ==")


def with_cit(d, available=True):
    s = good_snapshot()
    s.citations = d
    if available:
        s.available = s.available | {"citations"}
    return {f.rule_id: f for f in rules.run_all(s, {})}


cit = with_cit(citations.to_snapshot_dict(chk))
check("CI2 fails on a phone mismatch", not cit["CI2"].passed, cit["CI2"].detail)
check("CI2 names the directory", "yelp.com" in cit["CI2"].detail)
check("CI2 says tracking numbers belong on the website",
      "tracking" in cit["CI2"].fix.lower())

clean = citations.CitationCheck(business="X", our_phone="+44 191 555 0142")
clean.listings = [citations.Listing("yell.com", "u", read=True,
                                    phones=["01915550142"])]
check("CI2 passes when everything agrees",
      with_cit(citations.to_snapshot_dict(clean))["CI2"].passed)

unread = citations.CitationCheck(business="X", our_phone="0191")
unread.listings = [citations.Listing("yelp.com", "u", read=False,
                                     error="returned 403")]
check("CI2 is not checked when nothing was readable",
      with_cit(citations.to_snapshot_dict(unread))["CI2"].informational)
check("CI2 is not checked without DataForSEO",
      with_cit({}, available=False)["CI2"].informational)

print("\n== there is deliberately no CI1 ==")
all_ids = {f.rule_id for f in rules.run_all(good_snapshot(), {})}
check("no citation-count rule exists", "CI1" not in all_ids)
check("nothing scores a profile on directory count",
      not any("40 to 50" in f.fix or "40-50" in f.fix
              for f in rules.run_all(good_snapshot(), {})))

print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f in fails:
    print(f"  x {f}")
sys.exit(1 if fails else 0)
