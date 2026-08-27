"""Who is actually beating this profile in the map pack, and by how much.

Every other rule in this tool judges a profile against a fixed threshold: 20
photos, 25 reviews, 4.0 stars. Those numbers are a guess at an average market,
and in a real one they are usually wrong in both directions. Twenty-five
reviews is invisible in central London and dominant in a market town.

This asks a better question: what do the businesses ranking above you actually
have? A delta against whoever is genuinely winning is not a guess.

Google's own API cannot tell you any of this -- it only ever describes profiles
you manage. So this is the one part of the tool that needs a paid third party
(DataForSEO), and it degrades to "not checked" without one.

WHAT IS AND IS NOT AVAILABLE

  available   name, map rank, review count, rating, primary and additional
              categories, photo count, claimed status, address, phone
  NOT         competitors' post cadence, and their review velocity. Posts are
              not exposed by any third party, and per-competitor review dates
              need a separate paid call each. X3 therefore compares PHOTOS,
              and says so, rather than quietly comparing something narrower
              than its name suggests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import mean

from . import dataforseo

MAX_KEYWORDS = 5


@dataclass
class Business:
    name: str
    rank: int | None = None
    rating: float | None = None
    reviews: int | None = None
    category: str = ""
    additional_categories: list[str] = field(default_factory=list)
    photos: int | None = None
    claimed: bool | None = None
    address: str = ""
    phone: str = ""
    place_id: str = ""
    is_us: bool = False

    @property
    def all_categories(self) -> list[str]:
        cats = [self.category] + list(self.additional_categories)
        return [c for c in cats if c]


@dataclass
class Comparison:
    keywords: list[str] = field(default_factory=list)
    us: Business | None = None
    rivals: list[Business] = field(default_factory=list)
    ranks: dict[str, int | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def top(self) -> list[Business]:
        """The best-ranked rivals, deduplicated, best first."""
        return sorted([r for r in self.rivals if not r.is_us],
                      key=lambda b: (b.rank if b.rank is not None else 99))[:3]

    def _avg(self, attr: str) -> float | None:
        vals = [getattr(b, attr) for b in self.top
                if getattr(b, attr) is not None]
        return mean(vals) if vals else None

    @property
    def avg_reviews(self) -> float | None:
        return self._avg("reviews")

    @property
    def avg_rating(self) -> float | None:
        return self._avg("rating")

    @property
    def avg_photos(self) -> float | None:
        return self._avg("photos")

    @property
    def missing_categories(self) -> list[tuple[str, int]]:
        """Categories two or more of the top three use, that we do not.

        The "two or more" is the point. One rival having an odd category is
        noise; two of the three sharing one is how that market is described.
        """
        ours = {c.lower() for c in (self.us.all_categories if self.us else [])}
        counts: dict[str, int] = {}
        for rival in self.top:
            for cat in {c.lower(): c for c in rival.all_categories}.values():
                if cat.lower() in ours:
                    continue
                counts[cat] = counts.get(cat, 0) + 1
        shared = [(cat, n) for cat, n in counts.items() if n >= 2]
        return sorted(shared, key=lambda kv: -kv[1])

    @property
    def ranked_for(self) -> list[str]:
        return [k for k, v in self.ranks.items() if v is not None]


# ------------------------------------------------------------------- fetching

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _parse(item: dict, keyword: str) -> Business:
    rating = item.get("rating") or {}
    return Business(
        name=item.get("title", "") or "",
        rank=item.get("rank_group") or item.get("rank_absolute"),
        rating=rating.get("value"),
        reviews=rating.get("votes_count"),
        category=item.get("category", "") or "",
        additional_categories=[c for c in (item.get("additional_categories")
                                           or []) if c],
        # DataForSEO exposes this on most maps results but not all; None means
        # "not reported", which the rules treat as not checked rather than zero.
        photos=item.get("total_photos"),
        claimed=item.get("is_claimed"),
        address=item.get("address", "") or "",
        phone=item.get("phone", "") or "",
        place_id=item.get("place_id", "") or "",
    )


def _is_us(business: Business, our_name: str, our_phone: str,
           our_place_id: str) -> bool:
    if our_place_id and business.place_id:
        return business.place_id == our_place_id
    if our_phone and business.phone:
        # Compare the last 9 digits so +44 191 555 0142 matches 0191 555 0142.
        a, b = _digits(our_phone)[-9:], _digits(business.phone)[-9:]
        if a and a == b:
            return True
    return bool(our_name) and _norm(business.name) == _norm(our_name)


def compare(keywords: list[str], *, our_name: str, our_phone: str = "",
            our_place_id: str = "", latitude: float | None = None,
            longitude: float | None = None, location_name: str = "",
            language_code: str = "en", depth: int = 10,
            verbose: bool = True) -> Comparison:
    """Run each keyword through Google Maps and build the comparison.

    One billed request per keyword, capped at five.
    """
    keywords = [k.strip() for k in keywords if k.strip()][:MAX_KEYWORDS]
    result = Comparison(keywords=keywords)
    if not keywords:
        result.notes.append("no keywords given")
        return result

    if verbose:
        print(f"\n  Checking {len(keywords)} keyword(s) against the live map "
              f"pack. {len(keywords)} billed request(s).\n")

    seen: dict[str, Business] = {}
    for keyword in keywords:
        try:
            items = dataforseo.maps_search(
                keyword, latitude=latitude, longitude=longitude,
                location_name=location_name, language_code=language_code,
                depth=depth, verbose=verbose)
        except dataforseo.DataForSeoError as exc:
            result.notes.append(f"{keyword}: {exc}")
            result.ranks[keyword] = None
            continue

        our_rank = None
        for item in items:
            if item.get("type") not in (None, "maps_search"):
                continue
            # Some pack results are aggregator entries rather than a business
            # -- a directory page that happens to rank in Maps. Comparing
            # review counts against one of those is meaningless.
            if item.get("is_directory_item"):
                continue
            business = _parse(item, keyword)
            if not business.name:
                continue
            business.is_us = _is_us(business, our_name, our_phone, our_place_id)
            if business.is_us:
                our_rank = business.rank
                if result.us is None:
                    result.us = business
                continue

            key = business.place_id or _norm(business.name)
            existing = seen.get(key)
            # Keep the best rank a rival achieved across all the keywords.
            if existing is None or (business.rank or 99) < (existing.rank or 99):
                seen[key] = business

        result.ranks[keyword] = our_rank
        if verbose:
            where = f"#{our_rank}" if our_rank else "not in the pack"
            print(f"      {keyword:<38} {where}")

    result.rivals = list(seen.values())
    return result


# ----------------------------------------------------------- snapshot summary

def to_snapshot_dict(c: Comparison, our_reviews: int | None = None,
                     our_rating: float | None = None,
                     our_photos: int | None = None) -> dict:
    """The flat summary the rules read.

    Our own review and photo counts come from the Google API, not from the
    scrape -- they are authoritative there and only approximate here.
    """
    us = c.us
    return {
        "keywords": c.keywords,
        "ranked_for": c.ranked_for,
        "ranks": c.ranks,
        "rival_count": len(c.top),
        "our_reviews": our_reviews if our_reviews is not None else
        (us.reviews if us else None),
        "our_rating": our_rating if our_rating is not None else
        (us.rating if us else None),
        "our_photos": our_photos if our_photos is not None else
        (us.photos if us else None),
        "avg_reviews": c.avg_reviews,
        "avg_rating": c.avg_rating,
        "avg_photos": c.avg_photos,
        "missing_categories": [cat for cat, _n in c.missing_categories],
        "top": [{"name": b.name, "rank": b.rank, "reviews": b.reviews,
                 "rating": b.rating, "photos": b.photos,
                 "categories": b.all_categories} for b in c.top],
        "notes": c.notes,
    }


def show(c: Comparison, our_reviews: int | None = None,
         our_rating: float | None = None, our_photos: int | None = None) -> None:
    if not c.top:
        print("\n  No competitors came back.")
        for n in c.notes:
            print(f"    {n}")
        print()
        return

    print("\n  WHERE YOU RANK\n")
    for keyword, rank in c.ranks.items():
        where = f"#{rank}" if rank else "not in the top results"
        print(f"    {keyword:<40} {where}")

    print(f"\n  THE TOP {len(c.top)} IN THAT PACK\n")
    print(f"    {'#':<3} {'BUSINESS':<32} {'REVIEWS':>8} {'RATING':>7} "
          f"{'PHOTOS':>7}")
    print("    " + "-" * 62)

    def cell(value, fmt="{:,}"):
        return fmt.format(value) if value is not None else "-"

    for b in c.top:
        print(f"    {b.rank or '?':<3} {b.name[:31]:<32} "
              f"{cell(b.reviews):>8} {cell(b.rating, '{:.1f}'):>7} "
              f"{cell(b.photos):>7}")

    ours_r = our_reviews if our_reviews is not None else (
        c.us.reviews if c.us else None)
    ours_rat = our_rating if our_rating is not None else (
        c.us.rating if c.us else None)
    ours_p = our_photos if our_photos is not None else (
        c.us.photos if c.us else None)
    print("    " + "-" * 62)
    print(f"    {'you':<3} {(c.us.name if c.us else 'not found')[:31]:<32} "
          f"{cell(ours_r):>8} {cell(ours_rat, '{:.1f}'):>7} {cell(ours_p):>7}")

    print("\n  THE GAP\n")
    for label, ours, theirs, fmt in (
            ("Reviews", ours_r, c.avg_reviews, "{:,.0f}"),
            ("Rating", ours_rat, c.avg_rating, "{:.2f}"),
            ("Photos", ours_p, c.avg_photos, "{:,.0f}")):
        if ours is None or theirs is None:
            print(f"    {label:<10} not comparable "
                  f"({'ours' if ours is None else 'theirs'} not reported)")
            continue
        delta = ours - theirs
        arrow = "ahead" if delta >= 0 else "behind"
        print(f"    {label:<10} you {fmt.format(ours):>8}   "
              f"top-3 average {fmt.format(theirs):>8}   "
              f"{fmt.format(abs(delta))} {arrow}")

    missing = c.missing_categories
    if missing:
        print("\n  CATEGORIES THE TOP 3 USE THAT YOU DO NOT\n")
        for cat, n in missing:
            print(f"    {cat:<40} used by {n} of {len(c.top)}")

    print("\n  Competitors' post cadence and review velocity are not available "
          "from any\n  third party, so they are not compared here.")
    for n in c.notes:
        print(f"    note: {n}")
    print()
