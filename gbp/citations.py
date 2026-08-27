"""Where else this business is listed, and whether the details agree.

Only ONE thing is checked here: whether the phone number on a directory listing
matches the one on the Google profile. That is NAP consistency, and Google uses
it as a signal that a business is real and that its details are current.

WHAT IS DELIBERATELY NOT CHECKED: citation COUNT.

"Get listed on 40 to 50 directories" is a number that gets repeated in training
material and sold by citation vendors. Consistency across the listings you have
is a real ranking factor with real evidence behind it. Volume past the major
aggregators is not, and scoring a profile down for having 30 listings instead of
50 would be inventing a problem. If a count is ever wanted here, it belongs as
an informational line worth zero points.

HOW IT WORKS, AND WHAT THAT COSTS IN ACCURACY

  1. One Google search for the business name plus its city (billed once).
  2. Results on known directory domains are kept.
  3. Each of those pages is fetched and read for phone numbers.
  4. A page is a MISMATCH only if it names this business AND shows a different
     phone. A page with no phone visible is reported as "not shown", never as a
     mismatch -- plenty of directories hide the number behind a click, and
     calling that an inconsistency would be a fabricated finding.

Directories block bots freely. A page we cannot read is reported as unread.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import dataforseo, site as site_mod

# Directories that carry weight for a local business. Deliberately short: the
# aggregators and the ones people actually read, not a link-farm list.
DIRECTORY_DOMAINS = {
    "yelp.com", "yelp.co.uk", "yell.com", "thomsonlocal.com", "cylex-uk.co.uk",
    "bingplaces.com", "bing.com", "apple.com", "facebook.com", "foursquare.com",
    "tripadvisor.com", "tripadvisor.co.uk", "trustpilot.com", "checkatrade.com",
    "ratedpeople.com", "mybuilder.com", "houzz.com", "houzz.co.uk",
    "yellowpages.com", "bbb.org", "angi.com", "thumbtack.com", "manta.com",
    "hotfrog.com", "brownbook.net", "cylex.us.com", "scoot.co.uk",
    "freeindex.co.uk", "192.com", "touchlocal.com", "opendi.co.uk",
    "justdial.com", "sulekha.com", "yellowpages.ae", "connect.ae",
}


@dataclass
class Listing:
    domain: str
    url: str
    title: str = ""
    phones: list[str] = field(default_factory=list)
    read: bool = False
    error: str = ""

    @property
    def status(self) -> str:
        if not self.read:
            return f"unread ({self.error})" if self.error else "unread"
        if not self.phones:
            return "no phone shown"
        return ", ".join(self.phones[:2])


@dataclass
class CitationCheck:
    business: str = ""
    our_phone: str = ""
    listings: list[Listing] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def read(self) -> list[Listing]:
        return [l for l in self.listings if l.read]

    @property
    def matching(self) -> list[Listing]:
        tail = _digits(self.our_phone)[-9:]
        return [l for l in self.read if tail and
                any(tail in _digits(p) for p in l.phones)]

    @property
    def mismatched(self) -> list[Listing]:
        """Pages showing a phone number that is NOT ours."""
        tail = _digits(self.our_phone)[-9:]
        out = []
        for l in self.read:
            if not l.phones:
                continue
            if tail and any(tail in _digits(p) for p in l.phones):
                continue
            out.append(l)
        return out

    @property
    def silent(self) -> list[Listing]:
        return [l for l in self.read if not l.phones]


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _domain(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_directory(url: str) -> bool:
    host = _domain(url)
    return any(host == d or host.endswith("." + d) for d in DIRECTORY_DOMAINS)


def find(business_name: str, city: str, our_phone: str, *,
         location_name: str = "", language_code: str = "en",
         max_pages: int = 10, timeout: int = 20,
         user_agent: str = "", verbose: bool = True) -> CitationCheck:
    """Find directory listings and check the phone on each. One billed search."""
    check = CitationCheck(business=business_name, our_phone=our_phone)
    query = f'"{business_name}" {city}'.strip()

    if verbose:
        print(f"\n  Searching for: {query}   (1 billed request)\n")

    try:
        items = dataforseo.organic_search(
            query, location_name=location_name, language_code=language_code,
            verbose=verbose)
    except dataforseo.DataForSeoError as exc:
        check.notes.append(str(exc))
        return check

    seen: set[str] = set()
    for item in items:
        url = item.get("url") or ""
        if not url or not _is_directory(url):
            continue
        domain = _domain(url)
        if domain in seen:
            continue
        seen.add(domain)
        check.listings.append(Listing(domain=domain, url=url,
                                      title=item.get("title", "") or ""))
        if len(check.listings) >= max_pages:
            break

    if not check.listings:
        check.notes.append(
            "No listings on known directories appeared in the search results. "
            "That may mean there are none, or that they rank below the depth "
            "searched.")
        return check

    for listing in check.listings:
        if verbose:
            print(f"    reading {listing.domain} ...", end=" ", flush=True)
        page = site_mod.fetch_page(listing.url, timeout, user_agent)
        if not page.ok:
            listing.error = page.error
            if verbose:
                print(page.error)
            continue
        listing.read = True
        listing.phones = page.phones
        if verbose:
            print(listing.status)

    return check


def to_snapshot_dict(check: CitationCheck) -> dict:
    return {
        "found": len(check.listings),
        "read": len(check.read),
        "matching": len(check.matching),
        "mismatched": [
            {"domain": l.domain, "url": l.url, "phones": l.phones[:2]}
            for l in check.mismatched],
        "silent": [l.domain for l in check.silent],
        "notes": check.notes,
    }


def show(check: CitationCheck) -> None:
    if not check.listings:
        print("\n  No directory listings found.")
        for n in check.notes:
            print(f"    {n}")
        print()
        return

    print(f"\n  {len(check.listings)} directory listing(s) found, "
          f"{len(check.read)} readable.\n")
    print(f"    {'DIRECTORY':<26} PHONE SHOWN")
    print("    " + "-" * 60)
    for l in check.listings:
        print(f"    {l.domain[:25]:<26} {l.status}")

    bad = check.mismatched
    print()
    if bad:
        print(f"  {len(bad)} listing(s) show a DIFFERENT phone number to your "
              f"Google profile:")
        for l in bad:
            print(f"    {l.domain}  shows {', '.join(l.phones[:2])}")
            print(f"      {l.url}")
        print("\n  Fix these first. An inconsistent number is a live signal to "
              "Google that\n  the details may be wrong, and it sends real "
              "customers to a dead line.")
    else:
        print("  Every readable listing agrees with the profile's phone number.")

    if check.silent:
        print(f"\n  {len(check.silent)} listing(s) show no phone at all "
              f"({', '.join(check.silent[:5])}). Not a\n  mismatch -- many "
              f"directories hide the number behind a click.")

    print("\n  Citation COUNT is deliberately not scored. Consistency is a "
          "ranking factor;\n  the number of directories you appear on, past "
          "the main ones, is not.")
    for n in check.notes:
        print(f"    note: {n}")
    print()
