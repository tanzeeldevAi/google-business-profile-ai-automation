#!/usr/bin/env python3
"""The website layer: extraction, discovery, and the grounding guard.

Offline. A fake HTML page is parsed directly rather than fetched, and the
network functions are never called.

    python test/test_site.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test"))

from bs4 import BeautifulSoup  # noqa: E402

from gbp import site  # noqa: E402
from gbp.rules import Snapshot  # noqa: E402
from gbp import rules  # noqa: E402
from fixtures import good_snapshot  # noqa: E402

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")


SERVICE_HTML = """
<!doctype html><html><head>
<title>Boiler Repair in Durham | Northgate Plumbing</title>
<meta name="description" content="Same-day boiler repair across Durham.">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Plumber","name":"Northgate Plumbing",
 "telephone":"+44 191 555 0142"}
</script>
</head><body>
<nav><a href="/">Home</a><a href="/services/">Services</a></nav>
<header>Call us on 0191 555 0142</header>
<main>
  <h1>Boiler Repair in Durham</h1>
  <p>We repair gas and combi boilers across Durham and Chester-le-Street.
     Most repairs are finished in a single visit, and we carry the common
     parts on the van.</p>
  <h2>What is included</h2>
  <p>A full diagnostic, the repair itself, and a gas safety check before we
     leave. Our call-out fee is 65 pounds and is deducted from the repair
     if you go ahead.</p>
  <h2>Areas we cover</h2>
  <p>Durham, Chester-le-Street, Spennymoor and Bishop Auckland.</p>
  <a href="/services/blocked-drains/">Blocked drains</a>
  <a href="/services/bathroom-installation/">Bathroom installation</a>
  <a href="/blog/how-to-bleed-a-radiator/">Blog post</a>
  <a href="https://facebook.com/example">Facebook</a>
</main>
<footer><script>var x=1;</script>Registered in England</footer>
</body></html>
"""


def parse(html: str, url: str) -> site.Page:
    """Run the same extraction fetch_page does, without the network."""
    page = site.Page(url=site._normalise(url))
    soup = BeautifulSoup(html, "html.parser")
    page.title = soup.title.get_text(strip=True)
    h1 = soup.find("h1")
    page.h1 = h1.get_text(" ", strip=True) if h1 else ""
    md = soup.find("meta", attrs={"name": "description"})
    page.meta_description = md.get("content", "") if md else ""
    page.headings = [h.get_text(" ", strip=True)
                     for h in soup.find_all(["h2", "h3"])]
    import re
    base = "https://northgateplumbing.co.uk"
    from urllib.parse import urljoin
    page.links = [site._normalise(urljoin(url, a["href"]))
                  for a in soup.find_all("a", href=True)
                  if urljoin(url, a["href"]).startswith(base)]
    page.has_local_schema = bool(re.search(r'"@type"\s*:\s*"[^"]*Plumber', html))
    page.phones = site.extract_phones(html)
    page.text = site._clean_text(soup)
    return page


URL = "https://northgateplumbing.co.uk/services/boiler-repair/"
page = parse(SERVICE_HTML, URL)

print("\n== page extraction ==")
check("title is read", "Boiler Repair" in page.title, page.title)
check("h1 is read", page.h1 == "Boiler Repair in Durham", page.h1)
check("meta description is read", "Same-day" in page.meta_description)
check("subheadings are read", len(page.headings) == 2, str(page.headings))
check("body copy is extracted", "carry the common parts" in page.text)
check("scripts are stripped", "var x" not in page.text)
check("nav is stripped", "Services" not in page.text.split("Boiler Repair")[0])
check("LocalBusiness schema is detected", page.has_local_schema)
check("phone numbers are found", any("1915550142" in p for p in page.phones),
      str(page.phones))
check("internal links are collected", len(page.links) >= 3, str(page.links))
check("external links are excluded",
      not any("facebook" in l for l in page.links))
check("a page with text is ok", page.ok)
check("url is normalised (no trailing slash)", not page.url.endswith("/"),
      page.url)

print("\n== phone extraction does not mistake dates for numbers ==")
# Caught on a live site: 2026-08-07 reduces to 20260807, which then fails to
# match the profile's real number and reports a NAP mismatch that is not real.
PHONE_CASES = [
    ("Published 2026-08-07 and updated 2026-05-12", [], "ISO dates"),
    ("Updated 07/08/2026", [], "slash date"),
    ("Call +44 191 555 0142 today", ["+441915550142"], "UK with +"),
    ("Ring 0191 555 0142", ["01915550142"], "UK leading zero"),
    ("Tel: +971559461604", ["+971559461604"], "Gulf, no separators"),
    ("(555) 123-4567", ["5551234567"], "US bracketed"),
    ("Order #1234567890123456 shipped", [], "long id"),
    ("Trading since 1998", [], "a year"),
    ("Invoice 987654321 paid", [], "bare id with no leading zero"),
]
for _raw, _want, _label in PHONE_CASES:
    _got = site.extract_phones(_raw)
    check(f"phone: {_label}", _got == _want, f"got {_got}, wanted {_want}")

print("\n== the prompt block ==")
block = page.summary()
check("block names the page", URL.rstrip("/") in block)
check("block carries the heading", "Boiler Repair in Durham" in block)
check("block carries the sections", "What is included" in block)
check("block carries the body", "gas safety check" in block)
check("block is capped", len(page.summary(max_chars=100)) < 900,
      str(len(page.summary(max_chars=100))))

print("\n== service page discovery ==")
home = site.Page(url="https://northgateplumbing.co.uk", text="x", links=[
    "https://northgateplumbing.co.uk/services/boiler-repair",
    "https://northgateplumbing.co.uk/services/blocked-drains",
    "https://northgateplumbing.co.uk/about",
    "https://northgateplumbing.co.uk/blog/how-to-bleed-a-radiator",
    "https://northgateplumbing.co.uk/privacy",
    "https://northgateplumbing.co.uk/brochure.pdf",
    "https://northgateplumbing.co.uk/wp-admin/index.php",
])
found = site.discover_service_pages("https://northgateplumbing.co.uk", home,
                                    limit=8, timeout=1)
check("service pages are found", len(found) >= 2, str(found))
# Both service pages must outrank everything else. Which of the two comes
# first is arbitrary and not worth asserting.
check("service URLs rank above everything else",
      all("/services/" in u for u in found[:2]), str(found))
check("about pages rank below service pages",
      found.index("https://northgateplumbing.co.uk/about") >= 2
      if "https://northgateplumbing.co.uk/about" in found else True, str(found))
check("blog posts are excluded", not any("/blog/" in u for u in found))
check("privacy is excluded", not any("privacy" in u for u in found))
check("PDFs are excluded", not any(".pdf" in u for u in found))
check("wp-admin is excluded", not any("wp-" in u for u in found))

print("\n== the grounding guard ==")
src = page.text
check("a number from the page is allowed",
      site.unverified_numbers("The call-out fee is 65 pounds.", src) == [])
check("an invented number is caught",
      site.unverified_numbers("We have fixed over 4,200 boilers.", src) == ["4,200"],
      str(site.unverified_numbers("We have fixed over 4,200 boilers.", src)))
check("an invented percentage is caught",
      "97" in site.unverified_numbers("97% first-time fix rate.", src))
check("small prose numbers are allowed",
      site.unverified_numbers("Three things to check in the next 5 minutes.",
                              src) == [])
check("text with no numbers passes",
      site.unverified_numbers("We repair boilers across Durham.", src) == [])
check("commas in the source still match",
      site.unverified_numbers("1,200 jobs", "we did 1200 jobs") == [])
check("an empty source flags nothing when unused",
      site.unverified_numbers("no digits here", "") == [])

print("\n== the snapshot summary ==")
s = site.Site(base_url="https://northgateplumbing.co.uk", home=page,
              services={URL.rstrip("/"): page})
summary = site.to_snapshot_dict(s)
check("summary reports ok", summary["ok"])
check("summary carries phones", bool(summary["phones"]))
check("summary carries schema flag", summary["has_local_schema"])
check("summary counts service pages", summary["service_pages"] == 1)
check("summary omits page text", "text" not in summary)

broken = site.Site(base_url="https://example.com",
                   home=site.Page(url="https://example.com",
                                  error="returned 500"))
bsum = site.to_snapshot_dict(broken)
check("a broken site reports not ok", not bsum["ok"])
check("a broken site carries the reason", bsum["error"] == "returned 500")

print("\n== the website rules ==")


def with_site(sitedict, available_extra=True):
    snap = good_snapshot()
    snap.site = sitedict
    if not available_extra:
        snap.available = snap.available - {"site"}
    return {f.rule_id: f for f in rules.run_all(snap, {})}


ok_rules = with_site(summary)
check("W1 passes for a readable site", ok_rules["W1"].passed)
check("W3 passes when schema is present", ok_rules["W3"].passed)

bad_rules = with_site(bsum)
check("W1 fails for an unreachable site", not bad_rules["W1"].passed)
check("W1 says why", "returned 500" in bad_rules["W1"].detail)
check("W2 is not checked when the site is unreadable",
      bad_rules["W2"].informational)

mismatch = dict(summary, phones=["+441915559999"])
mm = with_site(mismatch)
check("W2 catches a phone mismatch", not mm["W2"].passed, mm["W2"].detail)

# The good fixture's profile phone is +44 191 555 0142; the page has the same
# number written differently. It must still match.
match = dict(summary, phones=["01915550142"])
check("W2 matches the same number written differently",
      with_site(match)["W2"].passed, with_site(match)["W2"].detail)

nophone = dict(summary, phones=[])
check("W2 flags a site with no number at all",
      not with_site(nophone)["W2"].passed)

noschema = dict(summary, has_local_schema=False)
check("W3 fails without schema", not with_site(noschema)["W3"].passed)

skipped = with_site(summary, available_extra=False)
for rid in ("W1", "W2", "W3"):
    check(f"{rid} is informational when the site was not fetched",
          skipped[rid].informational)
    check(f"{rid} scores nothing when not fetched", skipped[rid].points == 0)

print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f in fails:
    print(f"  x {f}")
sys.exit(1 if fails else 0)
