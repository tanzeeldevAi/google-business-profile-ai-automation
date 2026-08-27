"""The search terms Google says people used to find this profile.

This is the most valuable thing in the whole Business Profile, and almost
nobody acts on it. Google is telling you, in the customer's own words, what
they typed. The job is simple:

    1. Read every search term (Performance -> Searches showed your profile)
    2. Work out which of them the profile does NOT mention anywhere
    3. Put those words back into the profile -- as services with real
       descriptions, and into the ongoing posts

That is the whole idea: the words people already find you with should appear in
the profile they land on.

Two things about the data that shape everything here:

  * Counts come back as an exact `value` OR a `threshold` ("fewer than 15").
    Low-volume terms are always thresholded, and most terms are low volume.
    A thresholded term is not worthless -- it is a long-tail phrase with real
    intent -- so they are kept, ranked below exact counts.

  * Terms include brand searches ("northgate plumbing"), which you already win
    by definition. Those are separated out, because a coverage score that
    counts your own name is flattering and useless.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

# Words that carry no targeting meaning. "near me" is handled as a phrase.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "best", "by", "can", "cheap",
    "close", "do", "for", "from", "get", "good", "how", "i", "in", "is", "it",
    "me", "my", "near", "nearby", "of", "on", "or", "the", "to", "top", "us",
    "we", "what", "where", "who", "with", "you", "your", "service", "services",
    "company", "companies", "business", "local", "open", "now", "today",
}

# A term that is only these is not a service anybody offers.
NOT_A_SERVICE = re.compile(
    r"^(near me|open now|number|phone number|contact|address|directions|"
    r"opening hours|hours|reviews|prices?|cost|quote)$", re.I)


# Longest first, so "ations" is tried before "s".
_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ers", "er",
             "ies", "ied", "ies", "ist", "ors", "or", "ed", "es", "s")


def _stem(word: str) -> str:
    """Reduce a word enough that its variants match each other.

    A length-relative trim does NOT work here, and that is worth spelling out:
    "plumber"[:4] is "plum" but "plumbing"[:5] is "plumb", so the two never
    match and the tool reports a keyword gap that is not real. Strip a known
    suffix first, THEN truncate to a fixed length, so every variant lands on
    the same string:

        plumber, plumbing        -> plumb
        drain, drains, draining  -> drain
        install, installation    -> insta
        boiler, boilers          -> boil
    """
    w = word.lower()
    for suffix in _SUFFIXES:
        if len(w) - len(suffix) >= 4 and w.endswith(suffix):
            w = w[:-len(suffix)]
            break
    return w[:5]


def _tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if w not in STOPWORDS and len(w) > 1]


@dataclass
class Keyword:
    term: str
    impressions: int
    exact: bool = True

    @property
    def label(self) -> str:
        return f"{self.impressions:,}" if self.exact else f"<{self.impressions}"

    @property
    def words(self) -> list[str]:
        return _tokens(self.term)

    def stems(self, drop: set[str] | None = None) -> list[str]:
        drop = drop or set()
        return [_stem(w) for w in self.words if _stem(w) not in drop]


@dataclass
class Coverage:
    keyword: Keyword
    is_brand: bool
    places: list[str] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        return bool(self.places)


@dataclass
class Analysis:
    keywords: list[Keyword] = field(default_factory=list)
    coverage: list[Coverage] = field(default_factory=list)
    months: str = ""
    # Stems that carry no service meaning for this business -- currently the
    # city. Kept on the analysis so clustering can exclude them too.
    drop_stems: set[str] = field(default_factory=set)

    @property
    def brand(self) -> list[Coverage]:
        return [c for c in self.coverage if c.is_brand]

    @property
    def discovery(self) -> list[Coverage]:
        """Terms that are not the business's own name. These are the ones worth
        competing for -- a brand search was always going to find you."""
        return [c for c in self.coverage if not c.is_brand]

    @property
    def gaps(self) -> list[Coverage]:
        """Discovery terms that appear nowhere on the profile, biggest first."""
        return sorted([c for c in self.discovery if not c.covered],
                      key=lambda c: (c.keyword.exact, c.keyword.impressions),
                      reverse=True)

    @property
    def covered_rate(self) -> float:
        disc = self.discovery
        if not disc:
            return 0.0
        return sum(1 for c in disc if c.covered) / len(disc)

    @property
    def total_impressions(self) -> int:
        return sum(k.impressions for k in self.keywords)

    @property
    def missed_impressions(self) -> int:
        return sum(c.keyword.impressions for c in self.gaps)


def parse(raw: list[dict]) -> list[Keyword]:
    """Turn the API payload into Keywords, biggest first."""
    out: list[Keyword] = []
    for row in raw or []:
        term = (row.get("searchKeyword") or "").strip()
        if not term:
            continue
        value = row.get("insightsValue", {}) or {}
        if "value" in value:
            out.append(Keyword(term, int(value["value"]), exact=True))
        elif "threshold" in value:
            out.append(Keyword(term, int(value["threshold"]), exact=False))
        else:
            out.append(Keyword(term, 0, exact=False))
    # Exact counts first, then thresholds, each by size.
    return sorted(out, key=lambda k: (k.exact, k.impressions), reverse=True)


def _profile_fields(snap, site_text: str = "") -> dict[str, str]:
    """Everywhere a keyword could legitimately already appear."""
    services = []
    for item in snap.location.get("serviceItems", []) or []:
        label = (item.get("freeFormServiceItem", {}).get("label", {}) or {})
        services.append(label.get("displayName", ""))
        services.append(label.get("description", ""))
        structured = item.get("structuredServiceItem", {}) or {}
        services.append(structured.get("description", ""))

    cats = [snap.primary_category.get("displayName", "")]
    cats += [c.get("displayName", "") for c in snap.additional_categories]

    return {
        "business name": snap.title,
        "categories": " ".join(cats),
        "description": snap.get("profile.description", "") or "",
        "services": " ".join(s for s in services if s),
        "website": site_text[:200000],
    }


def _covers(haystack: str, kw: Keyword, drop: set[str]) -> bool:
    """Does this text cover the keyword?

    All of the keyword's meaningful words must be present, stem-matched. The
    city and the brand name are dropped first: "boiler repair durham" is
    covered by a service called "Boiler repair" on a profile that is already
    in Durham, and demanding the city appear too would report a gap that is
    not real.
    """
    hay = " ".join(_tokens(haystack))
    hay_stems = {_stem(w) for w in hay.split()}
    stems = kw.stems(drop)
    if not stems:
        return False
    return all(s in hay_stems for s in stems)


def analyse(keywords: list[Keyword], snap, site_text: str = "",
            posts_text: str = "") -> Analysis:
    """Work out which search terms the profile already reflects, and which it
    ignores."""
    brand_words = {_stem(w) for w in _tokens(snap.title)}
    city_words = {_stem(w) for w in _tokens(snap.locality)}
    drop = city_words

    fields = _profile_fields(snap, site_text)
    if posts_text:
        fields["recent posts"] = posts_text

    coverage: list[Coverage] = []
    for kw in keywords:
        stems = set(kw.stems())
        # A brand search is one that contains the business's own name.
        is_brand = bool(brand_words) and brand_words.issubset(stems)

        places = [name for name, text in fields.items()
                  if text and _covers(text, kw, drop)]
        # Matching only the business name is not coverage of a discovery term.
        if not is_brand and places == ["business name"]:
            places = []
        coverage.append(Coverage(kw, is_brand, places))

    return Analysis(keywords=keywords, coverage=coverage, drop_stems=drop)


def cluster(gaps: list[Coverage], max_groups: int = 12,
            drop: set[str] | None = None) -> list[dict]:
    """Group near-duplicate search terms so we propose one service, not nine.

    "boiler repair", "boiler repair near me" and "emergency boiler repair" are
    one service.

    Grouped on the MOST shared stem, not the rarest. Rarest sounds right --
    the most specific word -- but it is exactly wrong: it keys each term on
    whatever makes it unique, which scatters the variants that should be
    together. The word they share is the noun that names the job.

    `drop` removes stems that must never become a group key. The city is the
    one that matters: it appears in half the search terms, so without this it
    wins the "most shared" vote every time and every unrelated service ends up
    in one "durham" bucket.
    """
    drop = drop or set()
    buckets: dict[str, list[Coverage]] = defaultdict(list)
    freq: dict[str, int] = defaultdict(int)
    for c in gaps:
        for s in set(c.keyword.stems(drop)):
            freq[s] += 1

    for c in gaps:
        stems = set(c.keyword.stems(drop))
        if not stems:
            continue
        # Most shared first; alphabetical only to break ties deterministically.
        key = max(stems, key=lambda s: (freq[s], -ord(s[0]) if s else 0))
        buckets[key].append(c)

    groups = [
        {
            "key": key,
            "terms": [c.keyword for c in sorted(
                items, key=lambda c: (c.keyword.exact, c.keyword.impressions),
                reverse=True)],
            "impressions": sum(c.keyword.impressions for c in items),
        }
        for key, items in buckets.items()
    ]
    groups.sort(key=lambda g: -g["impressions"])
    return groups[:max_groups]


def worth_a_service(group: dict) -> bool:
    """Is this cluster actually a service somebody sells?

    Filters out the terms that are questions about the business rather than
    things it does -- "opening hours", "phone number", "near me". Putting those
    in the services list would be nonsense on a public profile.
    """
    terms = [g.term for g in group["terms"]]
    if all(NOT_A_SERVICE.match(t.strip()) for t in terms):
        return False
    # A single stopword-only cluster carries no meaning.
    return bool(group["terms"][0].words)


def summarise(analysis: Analysis, limit: int = 15) -> str:
    """The block handed to the writer, so posts use the words people type."""
    gaps = [c.keyword.term for c in analysis.gaps[:limit]]
    if not gaps:
        return ""
    return ("Search terms people actually used to find this business, which the "
            "profile does not currently mention. Use the ones that genuinely "
            "describe work this business does, in natural sentences. Do not "
            "list them, and do not use one that does not fit:\n"
            + "\n".join(f"- {t}" for t in gaps))


def to_snapshot_dict(analysis: Analysis, gap_limit: int = 20) -> dict:
    """The flat summary the audit rules read."""
    top = analysis.gaps[0].keyword if analysis.gaps else None
    return {
        "total": len(analysis.keywords),
        "discovery": len(analysis.discovery),
        "impressions": analysis.total_impressions,
        "covered_rate": round(analysis.covered_rate, 3),
        "gap_count": len(analysis.gaps),
        "missed_impressions": analysis.missed_impressions,
        "months": analysis.months,
        "top_gap": ({"term": top.term, "label": top.label,
                     "impressions": top.impressions} if top else None),
        "gaps": [{"term": c.keyword.term, "label": c.keyword.label,
                  "impressions": c.keyword.impressions}
                 for c in analysis.gaps[:gap_limit]],
        "top_terms": [{"term": c.keyword.term, "label": c.keyword.label,
                       "places": c.places, "brand": c.is_brand}
                      for c in analysis.coverage[:gap_limit]],
    }


def show(analysis: Analysis, limit: int = 25) -> None:
    kws = analysis.keywords
    if not kws:
        print("\n  No search terms returned.\n"
              "  Google needs a few months of activity before it reports any, "
              "and\n  the current month is never included.\n")
        return

    print(f"\n  {len(kws)} search term(s) over {analysis.months or 'the period'}"
          f"  --  {analysis.total_impressions:,} impressions\n")

    print(f"  {'TERM':<44} {'SHOWN':>8}   WHERE IT APPEARS")
    print("  " + "-" * 76)
    for c in analysis.coverage[:limit]:
        where = ", ".join(c.places) if c.places else "NOWHERE"
        tag = " [brand]" if c.is_brand else ""
        print(f"  {c.keyword.term[:43]:<44} {c.keyword.label:>8}   "
              f"{where}{tag}")
    if len(analysis.coverage) > limit:
        print(f"  ... and {len(analysis.coverage) - limit} more")

    disc = analysis.discovery
    print(f"\n  Non-brand terms: {len(disc)}   "
          f"covered by the profile: {analysis.covered_rate:.0%}")
    if analysis.gaps:
        print(f"  {len(analysis.gaps)} term(s) appear nowhere on the profile, "
              f"worth {analysis.missed_impressions:,} impressions.")
        print("\n  Turn them into services:  python run.py fix --only services")
    print()
