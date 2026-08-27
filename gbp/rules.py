"""The local SEO rule set.

Every rule is a small function that takes a Snapshot and returns a Finding.
Rules never call the network and never mutate anything, which is why the whole
audit is testable offline against a fixture.

Three things every rule must carry, because the report is read by a business
owner and not by an SEO:

    detail  what we actually found, with the number
    why     why Google cares -- the ranking or trust mechanism
    fix     what to do about it, specific enough to act on

`fixable` marks the rules fix.py can apply through the API. Everything else
needs a human, either because Google gives no write access (photos of a real
business, review generation) or because the right answer is a judgement call
about the business (its real-world name).

Severity drives both the score and the order things appear in the report:

    critical  actively costing them the map pack, or a suspension risk
    high      a real ranking or conversion loss
    medium    worth doing, measurable over months
    low       polish
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

SEVERITY_POINTS = {"critical": 20, "high": 10, "medium": 5, "low": 2}

# Which command actually handles each auto-fixable finding. The audit says
# "this is automated"; this is what stops it implying that one command does
# everything, which would be a promise the tool does not keep.
HANDLED_BY = {
    "description": "run.py fix",
    "holiday_hours": "run.py fix",
    "services": "run.py fix",
    "reviews": "run.py reviews",
    "posts": "run.py post",
}

CATEGORY_LABELS = {
    "health": "Profile health",
    "nap": "Name, address and phone",
    "categories": "Categories",
    "content": "Description and services",
    "hours": "Opening hours",
    "media": "Photos and video",
    "reviews": "Reviews",
    "posts": "Google Posts",
    "qanda": "Questions and answers",
    "website": "Website",
    "keywords": "Search terms",
    "competitors": "Against your competitors",
    "offpage": "Directory listings",
    "performance": "Performance",
}


@dataclass
class Finding:
    rule_id: str
    title: str
    severity: str
    category: str
    passed: bool
    detail: str
    why: str
    fix: str
    fixable: bool = False
    fix_key: str | None = None
    # Informational rules report a number without passing or failing, so they
    # never distort the score.
    informational: bool = False

    @property
    def command(self) -> str | None:
        """The command that handles this finding, or None if a person must."""
        return HANDLED_BY.get(self.fix_key or "")

    @property
    def points(self) -> int:
        return 0 if self.informational else SEVERITY_POINTS[self.severity]

    @property
    def earned(self) -> int:
        return self.points if self.passed else 0


@dataclass
class Snapshot:
    """Everything the audit reads. Assembled by audit.py, or loaded from a
    fixture in the tests. Every field defaults to empty so a partial snapshot
    (v4 not approved yet, say) still audits what it can."""
    location: dict[str, Any] = field(default_factory=dict)
    reviews: list[dict] = field(default_factory=list)
    posts: list[dict] = field(default_factory=list)
    media: list[dict] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    performance: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    place_actions: list[dict] = field(default_factory=list)
    # A flat summary of the business's own website, from site.py. Kept as a
    # plain dict so a Snapshot stays JSON-shaped and easy to build in a test.
    site: dict[str, Any] = field(default_factory=dict)
    # Summary of the search terms Google reports for this profile, from
    # keywords.py. Flat for the same reason as `site`.
    keywords: dict[str, Any] = field(default_factory=dict)
    # Map-pack comparison, from competitors.py. Needs a paid third party, so
    # this is empty far more often than the rest.
    competitors: dict[str, Any] = field(default_factory=dict)
    # Directory listing check, from citations.py. Also needs a paid third
    # party, so also absent by default.
    citations: dict[str, Any] = field(default_factory=dict)
    # Which sections we could actually fetch. A section we could not read is
    # reported as unknown, never as a failure -- telling a client their photos
    # are missing when we simply could not look would be worse than useless.
    available: set[str] = field(default_factory=lambda: {
        "location", "reviews", "posts", "media", "questions", "performance",
        "place_actions", "site", "keywords", "attributes"})
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ---------------------------------------------------------- small helpers

    def get(self, dotted: str, default=None):
        node: Any = self.location
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def title(self) -> str:
        return self.location.get("title", "") or ""

    @property
    def locality(self) -> str:
        return self.get("storefrontAddress.locality", "") or ""

    @property
    def region_code(self) -> str:
        return self.get("storefrontAddress.regionCode", "") or ""

    @property
    def is_service_area_business(self) -> bool:
        """A SAB has a service area and no public storefront address."""
        has_area = bool(self.get("serviceArea.places.placeInfos")
                        or self.get("serviceArea.regionCode"))
        has_street = bool(self.get("storefrontAddress.addressLines"))
        return has_area and not has_street

    @property
    def primary_category(self) -> dict:
        return self.get("categories.primaryCategory", {}) or {}

    @property
    def additional_categories(self) -> list[dict]:
        return self.get("categories.additionalCategories", []) or []

    def days_since(self, iso: str | None) -> float | None:
        if not iso:
            return None
        try:
            when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (self.now - when).total_seconds() / 86400.0


RULES: list[Callable[[Snapshot, dict], Finding]] = []


def rule(fn):
    RULES.append(fn)
    return fn


def _stem(word: str) -> str:
    """Crude stem, enough to match a category against prose.

    The category says "Plumber"; the description says "plumbing". Exact
    matching misses that and the rule then tells a perfectly good profile it
    never mentions its own service. Trimming to at least four characters
    catches plumber/plumbing, dentist/dental, electrician/electrical.
    """
    return word[:max(4, len(word) - 3)]


def _mentions(text: str, phrase: str) -> bool:
    """Does `text` mention any meaningful word from `phrase`, allowing for
    different word endings?"""
    words = [w for w in re.findall(r"[a-z]{4,}", phrase.lower())
             if w not in {"shop", "store", "service", "services", "company",
                          "centre", "center", "business", "supplier"}]
    return any(_stem(w) in text for w in words)


def _unknown(rule_id, title, category, section) -> Finding:
    return Finding(
        rule_id=rule_id, title=title, severity="low", category=category,
        passed=True, informational=True,
        detail=f"Not checked -- {section} data was not available on this run.",
        why="", fix="",
    )


# ============================================================== profile health

@rule
def h1_verified(s: Snapshot, cfg: dict) -> Finding:
    verified = bool(s.get("metadata.hasVoiceOfMerchant"))
    return Finding(
        "H1", "Profile is verified", "critical", "health", verified,
        detail="Verified and eligible to show." if verified else
               "NOT verified. Google is not treating this as a confirmed business.",
        why="An unverified profile is capped: it can be hidden from Maps entirely, "
            "and it cannot rank in the local pack. Nothing else on this list "
            "matters until this is fixed.",
        fix="Open the profile in Google Business Profile and complete verification "
            "(video, postcard, phone or email, depending on what Google offers). "
            "If verification keeps failing, the usual cause is an address that "
            "does not match what Google can see on the street.",
    )


@rule
def h2_open(s: Snapshot, cfg: dict) -> Finding:
    status = s.get("openInfo.status", "") or ""
    ok = status in ("OPEN", "")
    return Finding(
        "H2", "Business is marked open", "critical", "health", ok,
        detail=f"Status is {status or 'OPEN'}." if ok else
               f"Status is {status}. Customers see this on the profile.",
        why="A profile marked temporarily or permanently closed is suppressed in "
            "local results and shows a warning banner to anyone who finds it.",
        fix="Set the status back to open in Google Business Profile. If it was "
            "closed by Google rather than by you, that is a reinstatement case, "
            "not a settings change.",
        fixable=False,
    )


@rule
def h3_google_edits(s: Snapshot, cfg: dict) -> Finding:
    pending = bool(s.get("metadata.hasPendingEdits"))
    return Finding(
        "H3", "No edits stuck in review", "high", "health", not pending,
        detail="No pending edits." if not pending else
               "There are edits waiting on Google's review. Until they clear, the "
               "live profile does not match what you have set.",
        why="Pending edits mean the public profile and your settings disagree. It "
            "also often signals that Google is uncertain about the listing, which "
            "is a precursor to a suspension.",
        fix="Open the profile and check what is pending. Edits that sit for more "
            "than a week usually need a reinstatement request rather than patience.",
    )


@rule
def h4_duplicate(s: Snapshot, cfg: dict) -> Finding:
    dup = s.get("metadata.duplicateLocation")
    return Finding(
        "H4", "Not flagged as a duplicate", "high", "health", not dup,
        detail="No duplicate flag." if not dup else
               f"Google has linked this to another listing: {dup}",
        why="Duplicate listings split your reviews and ranking signals between two "
            "profiles, so neither ranks as well as one merged profile would.",
        fix="Ask Google to merge the duplicate into the profile you actually "
            "manage. Merge, never delete -- deleting loses the reviews.",
    )


# ================================================== name, address, phone (NAP)

@rule
def n1_name_stuffing(s: Snapshot, cfg: dict) -> Finding:
    title = s.title
    lowered = title.lower()
    signals: list[str] = []

    cat = s.primary_category.get("displayName") or ""
    if cat and _mentions(lowered, cat):
        signals.append("the category name")

    if s.locality and s.locality.lower() in lowered:
        signals.append("the city")

    promo = [w for w in ("best", "cheap", "top", "#1", "no.1", "affordable",
                         "24/7", "near me", "expert", "professional")
             if w in lowered]
    if promo:
        signals.append("promotional wording (" + ", ".join(promo) + ")")

    # Two or more signals is where it stops looking like a real trading name.
    risky = len(signals) >= 2
    return Finding(
        "N1", "Business name looks like the real name", "high", "nap", not risky,
        detail=(f'Name is "{title}".' if not risky else
                f'Name is "{title}", which contains ' + " and ".join(signals) + "."),
        why="Google requires the name to be the real-world name on your signage and "
            "paperwork. Keyword-stuffed names are the single most reported "
            "violation, and the penalty is a hard suspension, not a ranking dip.",
        fix="If that is genuinely the registered trading name, ignore this and keep "
            "evidence (signage photo, licence) in case of a report. If keywords "
            "were added to help ranking, remove them -- a competitor can report it "
            "at any time.",
        fixable=False,
    )


@rule
def n2_address(s: Snapshot, cfg: dict) -> Finding:
    if s.is_service_area_business:
        return Finding(
            "N2", "Address is set correctly for the business type", "critical",
            "nap", True,
            detail="Service-area business with no public address, which is correct.",
            why="", fix="",
        )
    lines = s.get("storefrontAddress.addressLines", []) or []
    ok = bool(lines and s.locality)
    return Finding(
        "N2", "Address is complete", "critical", "nap", ok,
        detail="Full street address and city are set." if ok else
               "The street address or city is missing.",
        why="Distance from the searcher is one of Google's three local ranking "
            "factors. An incomplete address means Google cannot place you "
            "precisely, and you drop out of nearby searches.",
        fix="Add the complete street address including city and postcode, exactly "
            "as it appears on your other listings and your website footer.",
    )


@rule
def n3_service_area(s: Snapshot, cfg: dict) -> Finding:
    areas = s.get("serviceArea.places.placeInfos", []) or []
    if not s.is_service_area_business and s.get("storefrontAddress.addressLines"):
        return Finding(
            "N3", "Service area is set", "medium", "nap", bool(areas),
            detail=f"{len(areas)} service area(s) set." if areas else
                   "No service areas set. Only customers near the shop see you.",
            why="A storefront can also declare the areas it travels to, which makes "
                "it eligible for searches in those areas rather than only near the "
                "premises.",
            fix="Add the towns or postcodes you actually serve. Do not add areas you "
                "would not travel to -- Google checks this against real behaviour, "
                "and over-claiming gets the whole service area ignored.",
        )
    ok = bool(areas)
    return Finding(
        "N3", "Service area is set", "high", "nap", ok,
        detail=f"{len(areas)} service area(s) set." if ok else
               "No service areas set on a business with no storefront.",
        why="A service-area business with no declared area has nothing for Google "
            "to match a local search against.",
        fix="Add every town, city or postcode you serve, up to Google's limit of 20.",
    )


@rule
def n4_phone(s: Snapshot, cfg: dict) -> Finding:
    primary = s.get("phoneNumbers.primaryPhone", "") or ""
    return Finding(
        "N4", "Phone number is set", "critical", "nap", bool(primary),
        detail=f"Primary phone: {primary}" if primary else "No phone number set.",
        why="Calls are the main conversion on a local profile. No number means the "
            "call button does not exist, and Google has one fewer signal that this "
            "is a real trading business.",
        fix="Add the number that is answered during opening hours. It must match "
            "the number on your website and directory listings exactly.",
    )


@rule
def n5_website(s: Snapshot, cfg: dict) -> Finding:
    uri = s.location.get("websiteUri", "") or ""
    return Finding(
        "N5", "Website is linked", "high", "nap", bool(uri),
        detail=f"Website: {uri}" if uri else "No website linked.",
        why="The linked site is how Google connects the profile to the rest of your "
            "content. Profiles with no site rank worse and convert worse, because "
            "there is nowhere to send someone who wants to check you out.",
        fix="Link the site. Point it at the page that matches the profile -- for a "
            "single location that is the home page, for a multi-location business "
            "it is that branch's own page, never the generic home page.",
    )


@rule
def n6_https(s: Snapshot, cfg: dict) -> Finding:
    uri = s.location.get("websiteUri", "") or ""
    if not uri:
        return _unknown("N6", "Website uses HTTPS", "nap", "the website field")
    ok = uri.lower().startswith("https://")
    return Finding(
        "N6", "Website uses HTTPS", "low", "nap", ok,
        detail=f"Linked URL is {uri.split('://')[0]}://",
        why="An http:// link makes browsers show a not-secure warning to anyone who "
            "clicks through from the profile.",
        fix="Change the linked URL to the https:// version.",
    )


@rule
def n7_opening_date(s: Snapshot, cfg: dict) -> Finding:
    od = s.get("openInfo.openingDate")
    return Finding(
        "N7", "Opening date is set", "low", "nap", bool(od),
        detail="Opening date is set." if od else "No opening date set.",
        why="A long trading history is a trust signal, and the date is used to show "
            "'years in business' on some surfaces.",
        fix="Add the date the business first opened, even if it was decades ago.",
        # Not auto-fixable: only the owner knows the date, and guessing it would
        # put a false claim on a public profile.
        fixable=False,
    )


SOCIAL_ATTRIBUTES = {
    "url_facebook": "Facebook", "url_instagram": "Instagram",
    "url_linkedin": "LinkedIn", "url_pinterest": "Pinterest",
    "url_tiktok": "TikTok", "url_twitter": "X", "url_youtube": "YouTube",
}


@rule
def n8_social_links(s: Snapshot, cfg: dict) -> Finding:
    """Social links on the profile.

    Handle with care. Google added social links to the Business Profile UI, but
    at the time of writing they cannot be WRITTEN through the API, and whether
    they are readable depends on the account. So this rule only judges when the
    attributes payload actually contains social URL attributes. If it does not,
    we cannot tell "none set" apart from "not exposed to us", and reporting
    "no social links" in that case would be a fabricated finding.
    """
    if "attributes" not in s.available:
        return _unknown("N8", "Social profiles are linked", "nap",
                        "profile attribute")

    attrs = s.attributes.get("attributes", []) or []
    social_keys = set()
    found: list[str] = []
    for attr in attrs:
        key = (attr.get("name", "") or "").split("/")[-1]
        if key not in SOCIAL_ATTRIBUTES:
            continue
        social_keys.add(key)
        values = attr.get("uriValues") or attr.get("urlValues") or []
        if values:
            found.append(SOCIAL_ATTRIBUTES[key])

    if not social_keys:
        return Finding(
            "N8", "Social profiles are linked", "low", "nap", True,
            informational=True,
            detail="Not checked -- this Google account does not expose social "
                   "link attributes through the API. Check the profile by hand: "
                   "Edit profile, Contact, Social profiles.",
            why="", fix="",
        )

    want = int(cfg.get("min_social_links", 2))
    ok = len(found) >= want
    return Finding(
        "N8", "Social profiles are linked", "low", "nap", ok,
        detail=(f"{len(found)} linked: {', '.join(found)}." if found else
                "No social profiles linked."),
        why="Google shows these on the profile and uses them to tie the listing "
            "to the same business elsewhere on the web, which reinforces the "
            "entity behind it.",
        fix=f"Link at least {want} -- Facebook plus one other is the usual pair. "
            "Only link accounts that are actually active: a dead Instagram with "
            "three posts from 2021 does more harm than no link.",
    )


# ================================================================== categories

@rule
def c1_primary_category(s: Snapshot, cfg: dict) -> Finding:
    cat = s.primary_category.get("displayName", "")
    return Finding(
        "C1", "Primary category is set", "critical", "categories", bool(cat),
        detail=f"Primary category: {cat}" if cat else "No primary category set.",
        why="The primary category is the strongest single ranking factor on a "
            "Google Business Profile. It decides which searches you are even "
            "eligible for. Getting it wrong caps everything else.",
        fix="Set the most specific category that describes the main thing you do. "
            "Specific beats broad: 'Emergency plumber' outranks 'Contractor' for "
            "the searches that convert.",
    )


@rule
def c2_secondary_categories(s: Snapshot, cfg: dict) -> Finding:
    extra = s.additional_categories
    want = int(cfg.get("min_secondary_categories", 3))
    ok = len(extra) >= want
    names = ", ".join(c.get("displayName", "") for c in extra[:5])
    return Finding(
        "C2", "Secondary categories are used", "high", "categories", ok,
        detail=(f"{len(extra)} secondary categories: {names}" if extra else
                "No secondary categories set."),
        why="Each secondary category makes you eligible for another set of searches "
            "at no cost to the primary. Most profiles leave all nine unused, which "
            "is free visibility left on the table.",
        fix=f"Add at least {want} secondary categories for services you genuinely "
            "offer. Only add what you actually do -- irrelevant categories dilute "
            "relevance and can trigger a quality review.",
    )


@rule
def c3_category_count(s: Snapshot, cfg: dict) -> Finding:
    total = len(s.additional_categories) + (1 if s.primary_category else 0)
    ok = total <= 10
    return Finding(
        "C3", "Not over-categorised", "medium", "categories", ok,
        detail=f"{total} categories in total.",
        why="Google allows one primary and nine secondary. Stuffing every loosely "
            "related category dilutes how strongly you match any single one.",
        fix="Trim to the services you actually deliver and would answer the phone "
            "for.",
    )


# ====================================================== description & services

@rule
def ct1_description(s: Snapshot, cfg: dict) -> Finding:
    desc = s.get("profile.description", "") or ""
    return Finding(
        "CT1", "Business description is written", "high", "content", bool(desc),
        detail=f"{len(desc)} characters." if desc else "No description set.",
        why="The description is the only free text you fully control on the "
            "profile. It is read by customers deciding whether to call, and it is "
            "one of the inputs Google uses to understand what you do.",
        fix="Write up to 750 characters covering what you do, who you serve, the "
            "areas you cover, and what makes you the safe choice.",
        fixable=True, fix_key="description",
    )


@rule
def ct2_description_length(s: Snapshot, cfg: dict) -> Finding:
    desc = s.get("profile.description", "") or ""
    if not desc:
        return _unknown("CT2", "Description uses the space available", "content",
                        "the description")
    ok = len(desc) >= int(cfg.get("min_description_chars", 500))
    return Finding(
        "CT2", "Description uses the space available", "medium", "content", ok,
        detail=f"{len(desc)} of 750 characters used.",
        why="750 characters is the limit and it is there to be used. A two-line "
            "description answers none of the questions a customer has before "
            "calling.",
        fix="Expand towards 750 characters. Cover services, service areas, "
            "qualifications, hours and what happens when someone calls.",
        fixable=True, fix_key="description",
    )


@rule
def ct3_description_no_links(s: Snapshot, cfg: dict) -> Finding:
    desc = s.get("profile.description", "") or ""
    if not desc:
        return _unknown("CT3", "Description follows Google's content rules",
                        "content", "the description")
    bad: list[str] = []
    if re.search(r"https?://|www\.", desc, re.I):
        bad.append("a URL")
    if re.search(r"\b[\d\s().+-]{9,}\b", desc) and re.search(r"\d{5,}", desc):
        bad.append("what looks like a phone number")
    offers = [w for w in ("% off", "discount", "sale", "free quote", "offer",
                          "call now", "book now") if w in desc.lower()]
    if offers:
        bad.append("promotional wording (" + ", ".join(offers) + ")")
    ok = not bad
    return Finding(
        "CT3", "Description follows Google's content rules", "high", "content", ok,
        detail="No prohibited content found." if ok else
               "Contains " + ", ".join(bad) + ".",
        why="Google's guidelines forbid URLs, phone numbers and promotional offers "
            "in the description. A description that breaks them is silently "
            "rejected or stripped, so the effort is wasted either way.",
        fix="Remove links, phone numbers and offers. The phone and website already "
            "have their own fields, and offers belong in a Google Post.",
        fixable=True, fix_key="description",
    )


@rule
def ct4_description_relevance(s: Snapshot, cfg: dict) -> Finding:
    desc = (s.get("profile.description", "") or "").lower()
    if not desc:
        return _unknown("CT4", "Description names the service and the area",
                        "content", "the description")
    cat = s.primary_category.get("displayName") or ""
    has_service = _mentions(desc, cat) if cat else False
    has_place = bool(s.locality and s.locality.lower() in desc)
    ok = has_service and has_place
    missing = []
    if not has_service:
        missing.append("the main service")
    if not has_place:
        missing.append("the city or area served")
    return Finding(
        "CT4", "Description names the service and the area", "medium", "content", ok,
        detail="Names both the service and the area." if ok else
               "Does not mention " + " or ".join(missing) + ".",
        why="The description is read by a customer comparing three profiles. Naming "
            "the service and the area in plain words is what makes it obvious they "
            "are in the right place.",
        fix="Rewrite so the first sentence says what you do and where you do it, in "
            "the words a customer would use.",
        fixable=True, fix_key="description",
    )


@rule
def ct5_services(s: Snapshot, cfg: dict) -> Finding:
    items = s.location.get("serviceItems", []) or []
    want = int(cfg.get("min_services", 5))
    ok = len(items) >= want
    return Finding(
        "CT5", "Services are listed", "high", "content", ok,
        detail=f"{len(items)} services listed." if items else "No services listed.",
        why="The services list is matched against what people search for, and it is "
            "shown on the profile. An empty list means Google is guessing your "
            "service range from your category alone.",
        fix=f"Add at least {want} services, named the way customers ask for them "
            "('blocked drain', not 'drainage remediation').",
    )


@rule
def ct6_service_descriptions(s: Snapshot, cfg: dict) -> Finding:
    items = s.location.get("serviceItems", []) or []
    if not items:
        return _unknown("CT6", "Services have descriptions", "content",
                        "the services list")
    described = sum(
        1 for i in items
        if (i.get("freeFormServiceItem", {}).get("label", {}).get("description")
            or i.get("structuredServiceItem", {}).get("description"))
    )
    ok = described >= max(1, int(len(items) * 0.6))
    return Finding(
        "CT6", "Services have descriptions", "medium", "content", ok,
        detail=f"{described} of {len(items)} services have a description.",
        why="A described service gives Google real text to match a long-tail search "
            "against, and answers the customer's question before they call.",
        fix="Add a short description to each service, covering what is included and "
            "roughly what it costs or how long it takes.",
    )


@rule
def ct7_attributes(s: Snapshot, cfg: dict) -> Finding:
    attrs = s.attributes.get("attributes", []) or []
    want = int(cfg.get("min_attributes", 5))
    ok = len(attrs) >= want
    return Finding(
        "CT7", "Attributes are filled in", "medium", "content", ok,
        detail=f"{len(attrs)} attributes set." if attrs else "No attributes set.",
        why="Attributes power the filters people use in Maps -- wheelchair access, "
            "appointment required, payment types, women-led. Leaving them empty "
            "means being filtered out of searches you would have won.",
        fix="Fill in every attribute your category offers that is genuinely true. "
            "They take five minutes and they are a filter, not a nice-to-have.",
    )


@rule
def ct8_booking_link(s: Snapshot, cfg: dict) -> Finding:
    if "place_actions" not in s.available:
        return _unknown("CT8", "Booking or appointment link", "content",
                        "place action links")
    links = s.place_actions
    ok = bool(links)
    kinds = ", ".join(sorted({l.get("placeActionType", "") for l in links})) or "none"
    return Finding(
        "CT8", "Booking or appointment link", "medium", "content", ok,
        detail=f"Action links set: {kinds}." if ok else
               "No booking, appointment or ordering link set.",
        why="An action link turns the profile into a booking form. Someone who can "
            "book at 11pm without phoning is a job you would otherwise have lost to "
            "whoever answers first in the morning.",
        fix="Add a booking or appointment URL pointing at your scheduling page. If "
            "you have no scheduler, a simple quote-request form still beats "
            "phone-only.",
    )


@rule
def ct9_service_location_words(s: Snapshot, cfg: dict) -> Finding:
    items = s.location.get("serviceItems", []) or []
    if not items:
        return _unknown("CT9", "Services name the area they cover", "content",
                        "the services list")

    places = {p.get("placeName", "") for p in
              (s.get("serviceArea.places.placeInfos", []) or [])}
    if s.locality:
        places.add(s.locality)
    places = {p.lower() for p in places if p}
    if not places:
        return _unknown("CT9", "Services name the area they cover", "content",
                        "any city or service area")

    named = 0
    for item in items:
        label = (item.get("freeFormServiceItem", {}).get("label", {}) or {})
        text = f"{label.get('displayName', '')}".lower()
        if any(place in text for place in places):
            named += 1

    rate = named / len(items)
    want = float(cfg.get("min_service_location_rate", 0.5))
    ok = rate >= want
    return Finding(
        "CT9", "Services name the area they cover", "medium", "content", ok,
        detail=f"{named} of {len(items)} service names mention a city or area "
               f"you serve ({rate:.0%}).",
        why="People search \"AC repair London\", not \"AC repair\". A service "
            "named the way the search is actually typed matches it directly, "
            "instead of relying on Google to infer the location from the pin.",
        fix="Add a location variant for your 3 to 5 main services only. Do not "
            "do it to all of them -- a services list where every line ends in "
            "the same city name reads as spam to a customer and to Google.",
    )


@rule
def ct10_service_description_depth(s: Snapshot, cfg: dict) -> Finding:
    items = s.location.get("serviceItems", []) or []
    lengths = []
    for item in items:
        label = (item.get("freeFormServiceItem", {}).get("label", {}) or {})
        desc = (label.get("description")
                or item.get("structuredServiceItem", {}).get("description") or "")
        if desc:
            lengths.append(len(desc))
    if not lengths:
        return _unknown("CT10", "Service descriptions have some depth", "content",
                        "any service description")

    avg = sum(lengths) / len(lengths)
    want = int(cfg.get("min_service_desc_chars", 200))
    ok = avg >= want
    return Finding(
        "CT10", "Service descriptions have some depth", "low", "content", ok,
        detail=f"Average description is {avg:.0f} characters across "
               f"{len(lengths)} service(s).",
        why="A one-line description gives Google almost nothing to match a "
            "long-tail search against, and answers none of the questions a "
            "customer has before they call.",
        fix="Aim for 250 to 350 characters each: what the job includes, which "
            "areas it covers, and roughly what it costs or how long it takes.",
    )


# =============================================================== opening hours

@rule
def hr1_regular_hours(s: Snapshot, cfg: dict) -> Finding:
    periods = s.get("regularHours.periods", []) or []
    return Finding(
        "HR1", "Opening hours are set", "critical", "hours", bool(periods),
        detail=f"{len(periods)} opening periods set." if periods else
               "No opening hours set.",
        why="Hours decide whether you show as open right now, and 'open now' is one "
            "of the most used filters in Maps. A profile with no hours is dropped "
            "from those results entirely.",
        fix="Set hours for every day, marking days you are closed as closed rather "
            "than leaving them blank.",
    )


@rule
def hr2_hours_complete(s: Snapshot, cfg: dict) -> Finding:
    periods = s.get("regularHours.periods", []) or []
    if not periods:
        # HR1 already reports "no hours at all" as critical. Repeating it here
        # would charge the profile twice for one problem and make the hours
        # category look worse than it is.
        return Finding(
            "HR2", "Hours cover the whole week", "high", "hours", False,
            detail="No hours are set at all, so no day is covered.",
            why="Days left blank read as unknown rather than closed, which loses "
                "you 'open now' matches on the days you are actually open.",
            fix="Set hours for every day, marking closed days as closed.",
        )
    days = {p.get("openDay") for p in periods}
    ok = len(days) >= 5
    return Finding(
        "HR2", "Hours cover the whole week", "high", "hours", ok,
        detail=f"Hours set for {len(days)} day(s) of the week.",
        why="Days left blank read as unknown rather than closed, which loses you "
            "'open now' matches on the days you are actually open.",
        fix="Set every day explicitly. If you are closed Sundays, say closed.",
    )


@rule
def hr3_holiday_hours(s: Snapshot, cfg: dict) -> Finding:
    special = s.get("specialHours.specialHourPeriods", []) or []
    horizon = int(cfg.get("holiday_horizon_days", 60))
    upcoming = 0
    for p in special:
        d = p.get("startDate", {})
        try:
            when = datetime(int(d["year"]), int(d["month"]), int(d["day"]),
                            tzinfo=timezone.utc)
        except (KeyError, ValueError, TypeError):
            continue
        if 0 <= (when - s.now).days <= horizon:
            upcoming += 1
    ok = upcoming > 0
    return Finding(
        "HR3", "Holiday hours are set ahead", "high", "hours", ok,
        detail=(f"{upcoming} special-hours entry in the next {horizon} days."
                if ok else f"Nothing set for the next {horizon} days."),
        why="Google prompts searchers with 'hours might differ' on public holidays "
            "and pushes profiles with confirmed holiday hours above ones without. "
            "Being wrongly listed as open on a holiday also earns one-star reviews "
            "from people who turned up to a locked door.",
        fix="Set special hours for every upcoming public holiday, including the ones "
            "you stay open for. Confirming you are open is worth as much as "
            "marking you closed.",
        fixable=True, fix_key="holiday_hours",
    )


# ============================================================ photos and video

@rule
def m1_photo_count(s: Snapshot, cfg: dict) -> Finding:
    if "media" not in s.available:
        return _unknown("M1", "Enough photos", "media", "photos")
    photos = [m for m in s.media if m.get("mediaFormat") == "PHOTO"]
    want = int(cfg.get("min_photos", 20))
    ok = len(photos) >= want
    return Finding(
        "M1", "Enough photos", "high", "media", ok,
        detail=f"{len(photos)} photos on the profile.",
        why="Photo count correlates strongly with clicks and direction requests. "
            "Profiles with a thin gallery lose the click to the competitor whose "
            "work you can actually see.",
        fix=f"Get to at least {want} real photos: the premises, the team, vehicles, "
            "and above all finished work. Real photos, taken on site -- Google's "
            "guidelines require them to represent the business.",
    )


@rule
def m2_recent_photo(s: Snapshot, cfg: dict) -> Finding:
    if "media" not in s.available:
        return _unknown("M2", "Photos added recently", "media", "photos")
    days = int(cfg.get("photo_freshness_days", 30))
    newest = None
    for m in s.media:
        age = s.days_since(m.get("createTime"))
        if age is not None and (newest is None or age < newest):
            newest = age
    ok = newest is not None and newest <= days
    return Finding(
        "M2", "Photos added recently", "high", "media", ok,
        detail=(f"Newest photo is {newest:.0f} days old." if newest is not None
                else "No dated photos found."),
        why="A steady trickle of new photos is an activity signal. A gallery that "
            "stopped two years ago reads as a business that may have stopped too.",
        fix=f"Upload a few real photos at least every {days} days. Finished jobs are "
            "the best kind -- they are new content and social proof at once.",
    )


@rule
def m4_media_cadence(s: Snapshot, cfg: dict) -> Finding:
    if "media" not in s.available:
        return _unknown("M4", "Media is added regularly", "media", "photos")
    window = int(cfg.get("media_window_days", 30))
    want = int(cfg.get("min_media_per_month", 4))

    recent = 0
    for m in s.media:
        # Customer-contributed media carries an attribution block. It is good
        # to have, but it is not the business being active, so it does not
        # count towards a cadence the owner controls.
        if m.get("attribution"):
            continue
        age = s.days_since(m.get("createTime"))
        if age is not None and age <= window:
            recent += 1

    ok = recent >= want
    return Finding(
        "M4", "Media is added regularly", "medium", "media", ok,
        detail=f"{recent} photo(s) or video(s) added by the business in the "
               f"last {window} days.",
        why="M1 asks whether there are enough photos; this asks whether any are "
            "still arriving. Forty photos uploaded once two years ago and "
            "nothing since is not the same signal as one or two a week -- the "
            "second reads as a business that is still trading.",
        fix=f"Upload {want} or more real photos a month, or a short video. "
            "Finished jobs are the best kind: new content and social proof at "
            "the same time. Real photos taken on site, not stock.",
    )


@rule
def m3_video(s: Snapshot, cfg: dict) -> Finding:
    if "media" not in s.available:
        return _unknown("M3", "At least one video", "media", "photos")
    videos = [m for m in s.media if m.get("mediaFormat") == "VIDEO"]
    ok = bool(videos)
    return Finding(
        "M3", "At least one video", "low", "media", ok,
        detail=f"{len(videos)} video(s)." if videos else "No video on the profile.",
        why="Video is still rare on local profiles, so it stands out, and it holds "
            "attention longer than a photo.",
        fix="Add one 30-second phone video: a walkthrough, or a job before and after.",
    )


# ===================================================================== reviews

@rule
def r1_review_count(s: Snapshot, cfg: dict) -> Finding:
    if "reviews" not in s.available:
        return _unknown("R1", "Enough reviews", "reviews", "reviews")
    want = int(cfg.get("min_reviews", 25))
    n = len(s.reviews)
    ok = n >= want
    return Finding(
        "R1", "Enough reviews", "high", "reviews", ok,
        detail=f"{n} reviews.",
        why="Review count is part of the 'prominence' factor Google ranks on, and it "
            "is the first thing a customer compares between three profiles. Below "
            "about 20 you are usually invisible next to an established competitor.",
        fix=f"Get to {want}+ by asking every satisfied customer at the moment the "
            "job finishes. Ask in person or by text with the review link -- never "
            "buy reviews, and never offer anything in exchange.",
    )


@rule
def r2_average_rating(s: Snapshot, cfg: dict) -> Finding:
    if "reviews" not in s.available or not s.reviews:
        return _unknown("R2", "Rating is healthy", "reviews", "reviews")
    stars = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
    vals = [stars.get(r.get("starRating", ""), 0) for r in s.reviews]
    vals = [v for v in vals if v]
    avg = sum(vals) / len(vals) if vals else 0
    floor = float(cfg.get("min_rating", 4.0))
    ok = avg >= floor
    return Finding(
        "R2", "Rating is healthy", "high", "reviews", ok,
        detail=f"Average rating {avg:.2f} across {len(vals)} reviews.",
        why="Below about 4.0 the click-through collapses -- people filter by rating "
            "before they read anything. Google also uses rating as a quality signal.",
        fix="Reply to every negative review, fix what caused it, then ask happy "
            "customers so the average recovers. Do not try to remove honest "
            "negatives; volume of good ones is what works.",
    )


@rule
def r3_response_rate(s: Snapshot, cfg: dict) -> Finding:
    if "reviews" not in s.available or not s.reviews:
        return _unknown("R3", "Every review is answered", "reviews", "reviews")
    answered = sum(1 for r in s.reviews if r.get("reviewReply"))
    rate = answered / len(s.reviews)
    ok = rate >= float(cfg.get("min_response_rate", 0.95))
    return Finding(
        "R3", "Every review is answered", "critical", "reviews", ok,
        detail=f"{answered} of {len(s.reviews)} answered ({rate:.0%}).",
        why="Google states plainly that responding to reviews improves local "
            "ranking. It is the highest-value thing on this whole list, it is free, "
            "and most competitors do not bother.",
        fix="Reply to every review, positive and negative. This tool can do it "
            "automatically -- see `python run.py reviews`.",
        fixable=True, fix_key="reviews",
    )


@rule
def r4_unanswered_age(s: Snapshot, cfg: dict) -> Finding:
    if "reviews" not in s.available or not s.reviews:
        return _unknown("R4", "No review left waiting", "reviews", "reviews")
    limit = int(cfg.get("max_reply_days", 7))
    stale = 0
    for r in s.reviews:
        if r.get("reviewReply"):
            continue
        age = s.days_since(r.get("createTime"))
        if age is not None and age > limit:
            stale += 1
    ok = stale == 0
    return Finding(
        "R4", "No review left waiting", "high", "reviews", ok,
        detail="Nothing waiting." if ok else
               f"{stale} review(s) unanswered for more than {limit} days.",
        why="A reply weeks later is seen by nobody -- the reviewer has moved on and "
            "the next customer has already read the silence.",
        fix=f"Reply within {limit} days, ideally within 24 hours for anything "
            "negative.",
        fixable=True, fix_key="reviews",
    )


@rule
def r5_review_velocity(s: Snapshot, cfg: dict) -> Finding:
    if "reviews" not in s.available or not s.reviews:
        return _unknown("R5", "Reviews are still coming in", "reviews", "reviews")
    window = int(cfg.get("velocity_days", 90))
    recent = sum(1 for r in s.reviews
                 if (a := s.days_since(r.get("createTime"))) is not None and a <= window)
    want = int(cfg.get("min_recent_reviews", 3))
    ok = recent >= want
    return Finding(
        "R5", "Reviews are still coming in", "high", "reviews", ok,
        detail=f"{recent} review(s) in the last {window} days.",
        why="Steady recent reviews matter more than a large old pile. A profile "
            "whose last review was two years ago looks dormant to both Google and "
            "the customer.",
        fix=f"Aim for at least {want} new reviews every {window} days. Build the ask "
            "into the end of every job rather than doing it in bursts -- a sudden "
            "spike looks bought and can get them filtered.",
    )


# =============================================================== google posts

@rule
def p1_recent_post(s: Snapshot, cfg: dict) -> Finding:
    if "posts" not in s.available:
        return _unknown("P1", "Posted recently", "posts", "posts")
    days = int(cfg.get("post_freshness_days", 7))
    newest = None
    for p in s.posts:
        age = s.days_since(p.get("createTime"))
        if age is not None and (newest is None or age < newest):
            newest = age
    ok = newest is not None and newest <= days
    return Finding(
        "P1", "Posted recently", "high", "posts", ok,
        detail=(f"Last post was {newest:.0f} days ago." if newest is not None
                else "No posts found."),
        why="A What's New post stops being shown prominently after about a week. "
            "Posting weekly keeps fresh content on the profile and is an activity "
            "signal; almost no small competitor does it.",
        fix=f"Post at least once every {days} days. This tool can write and schedule "
            "them -- see `python run.py post`.",
        fixable=True, fix_key="posts",
    )


@rule
def p2_post_cadence(s: Snapshot, cfg: dict) -> Finding:
    if "posts" not in s.available:
        return _unknown("P2", "Posting regularly", "posts", "posts")
    recent = sum(1 for p in s.posts
                 if (a := s.days_since(p.get("createTime"))) is not None and a <= 90)
    want = int(cfg.get("min_posts_90d", 8))
    ok = recent >= want
    return Finding(
        "P2", "Posting regularly", "medium", "posts", ok,
        detail=f"{recent} post(s) in the last 90 days.",
        why="One post then silence does nothing. The signal is consistency.",
        fix=f"Keep to roughly weekly, so at least {want} posts a quarter.",
        fixable=True, fix_key="posts",
    )


@rule
def p3_post_cta(s: Snapshot, cfg: dict) -> Finding:
    if "posts" not in s.available or not s.posts:
        return _unknown("P3", "Posts have a call to action", "posts", "posts")
    with_cta = sum(1 for p in s.posts if p.get("callToAction"))
    ok = with_cta >= max(1, int(len(s.posts) * 0.7))
    return Finding(
        "P3", "Posts have a call to action", "medium", "posts", ok,
        detail=f"{with_cta} of {len(s.posts)} posts have a button.",
        why="A post without a button is an advert with no way to respond. The Call "
            "and Book buttons are the whole point.",
        fix="Add a Call, Book or Learn more button to every post.",
        fixable=True, fix_key="posts",
    )


@rule
def r6_reply_relevance(s: Snapshot, cfg: dict) -> Finding:
    if "reviews" not in s.available or not s.reviews:
        return _unknown("R6", "Replies use words worth indexing", "reviews",
                        "reviews")
    replies = [(r.get("reviewReply", {}) or {}).get("comment", "")
               for r in s.reviews]
    replies = [t for t in replies if t]
    if not replies:
        return _unknown("R6", "Replies use words worth indexing", "reviews",
                        "any owner reply")

    cat = s.primary_category.get("displayName", "")
    place = s.locality
    relevant = 0
    for text in replies:
        low = text.lower()
        if (cat and _mentions(low, cat)) or (place and place.lower() in low):
            relevant += 1

    rate = relevant / len(replies)
    want = float(cfg.get("min_reply_relevance", 0.4))
    ok = rate >= want
    return Finding(
        "R6", "Replies use words worth indexing", "low", "reviews", ok,
        detail=f"{relevant} of {len(replies)} replies mention the service or "
               f"the area ({rate:.0%}).",
        why="A reply is owner-written text attached to the profile. It is the "
            "one place in the reviews section where you choose the words, and "
            "most owners spend it on \"thanks!\".",
        fix="Name the job and the area naturally: \"glad we got the boiler "
            "going again in Chester-le-Street\". Do NOT template it -- the same "
            "sentence under every review is obvious to a customer reading them "
            "in order, and to Google.",
    )


# =========================================================== questions/answers

@rule
def p4_posts_deep_link(s: Snapshot, cfg: dict) -> Finding:
    if "posts" not in s.available or not s.posts:
        return _unknown("P4", "Post buttons go to the right page", "posts",
                        "posts")
    urls = [(p.get("callToAction", {}) or {}).get("url", "")
            for p in s.posts]
    urls = [u for u in urls if u]
    if not urls:
        return _unknown("P4", "Post buttons go to the right page", "posts",
                        "any post with a link")

    def is_deep(url: str) -> bool:
        # Anything past the domain counts as deep. "/" and "" do not.
        path = re.sub(r"^https?://[^/]+", "", url).split("?")[0].split("#")[0]
        return len(path.strip("/")) > 0

    deep = sum(1 for u in urls if is_deep(u))
    rate = deep / len(urls)
    want = float(cfg.get("min_post_deep_link_rate", 0.6))
    ok = rate >= want
    return Finding(
        "P4", "Post buttons go to the right page", "medium", "posts", ok,
        detail=f"{deep} of {len(urls)} post buttons point at a specific page "
               f"rather than the home page ({rate:.0%}).",
        why="Sending every post to the home page throws away that post's "
            "topical relevance, and makes the reader hunt for the thing they "
            "just clicked about. A drain-cleaning post should land on the "
            "drain-cleaning page.",
        fix="Point each post's button at the matching service or location page. "
            "If the page does not exist yet, that is worth knowing too.",
    )


@rule
def q1_unanswered_questions(s: Snapshot, cfg: dict) -> Finding:
    if "questions" not in s.available:
        return _unknown("Q1", "No unanswered questions", "qanda", "questions")
    unanswered = [q for q in s.questions if not (q.get("topAnswers") or [])]
    ok = not unanswered
    return Finding(
        "Q1", "No unanswered questions", "high", "qanda", ok,
        detail="All questions answered." if ok else
               f"{len(unanswered)} question(s) with no answer.",
        why="Anyone can answer a question on your profile, including a competitor "
            "or someone guessing. An unanswered question is public and it is "
            "usually the exact thing a buyer wanted to know.",
        fix="Answer every question from the business account so the answer is "
            "labelled as the owner's.",
    )


@rule
def q2_seeded_questions(s: Snapshot, cfg: dict) -> Finding:
    if "questions" not in s.available:
        return _unknown("Q2", "Common questions are seeded", "qanda", "questions")
    want = int(cfg.get("min_questions", 5))
    ok = len(s.questions) >= want
    return Finding(
        "Q2", "Common questions are seeded", "medium", "qanda", ok,
        detail=f"{len(s.questions)} question(s) on the profile.",
        why="Q&A is shown high on the mobile profile and is keyword-matched. You are "
            "allowed to post your own questions and answer them, and doing so puts "
            "your own words where a competitor's guess would otherwise sit.",
        fix=f"Seed at least {want} real questions customers ask -- pricing, "
            "call-out areas, emergency availability, guarantees -- and answer each "
            "from the business account.",
    )


# ===================================================================== website

def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


@rule
def w1_site_reachable(s: Snapshot, cfg: dict) -> Finding:
    if "site" not in s.available:
        return _unknown("W1", "Website is reachable", "website", "the website")
    ok = bool(s.site and s.site.get("ok"))
    note = (s.site or {}).get("error", "")
    return Finding(
        "W1", "Website is reachable", "high", "website", ok,
        detail="The linked website loads and has readable content." if ok else
               f"Could not read the linked website{(' -- ' + note) if note else '.'}",
        why="Google follows the link on your profile. A site that is down, "
            "blocked, or renders only through JavaScript gives Google nothing "
            "to connect the profile to, and gives a customer who clicks nothing "
            "at all.",
        fix="Check the site loads for a logged-out visitor. If the content only "
            "appears after JavaScript runs, get the important text server-"
            "rendered -- crawlers and previews often will not wait.",
    )


@rule
def w2_phone_matches(s: Snapshot, cfg: dict) -> Finding:
    if "site" not in s.available or not (s.site or {}).get("ok"):
        return _unknown("W2", "Phone matches the website", "website",
                        "the website")
    profile_phone = _digits(s.get("phoneNumbers.primaryPhone", ""))
    site_phones = [_digits(p) for p in (s.site.get("phones") or [])]
    if not profile_phone:
        return _unknown("W2", "Phone matches the website", "website",
                        "the profile phone")
    if not site_phones:
        return Finding(
            "W2", "Phone matches the website", "medium", "website", False,
            detail="No phone number was found anywhere on the website.",
            why="NAP consistency -- the same name, address and phone everywhere "
                "-- is one of the things Google uses to decide a business is "
                "real. A site with no visible number also loses the calls.",
            fix="Put the same number that is on the profile in the site header "
                "and footer, as click-to-call on mobile.",
        )
    # Compare on the last 9 digits so +44 191 555 0142 and 0191 555 0142 match.
    tail = profile_phone[-9:]
    ok = any(tail and tail in p for p in site_phones)
    return Finding(
        "W2", "Phone matches the website", "high", "website", ok,
        detail="The profile number appears on the website." if ok else
               f"The profile number ({s.get('phoneNumbers.primaryPhone')}) does "
               f"not appear on the website. Found instead: "
               f"{', '.join((s.site.get('phones') or [])[:3])}",
        why="A different number on the site and the profile is a NAP "
            "inconsistency. Google treats mismatched details as a sign the "
            "listing may be stale or wrong, and it damages map pack ranking.",
        fix="Make them the same. If one is a call-tracking number, put the "
            "tracking number on the WEBSITE and keep the real number on the "
            "profile and every citation -- never the other way round.",
    )


@rule
def w3_local_schema(s: Snapshot, cfg: dict) -> Finding:
    if "site" not in s.available or not (s.site or {}).get("ok"):
        return _unknown("W3", "Website has LocalBusiness schema", "website",
                        "the website")
    ok = bool(s.site.get("has_local_schema"))
    return Finding(
        "W3", "Website has LocalBusiness schema", "medium", "website", ok,
        detail="LocalBusiness structured data found." if ok else
               "No LocalBusiness structured data on the home page.",
        why="Schema tells Google explicitly what the business is, where it is "
            "and how to reach it, instead of leaving it to be inferred. It is "
            "the cheapest way to reinforce everything on the profile.",
        fix="Add LocalBusiness JSON-LD to the home page with the same name, "
            "address, phone, hours and URL as the Google profile. The details "
            "must match the profile exactly, or it works against you.",
    )


@rule
def w4_website_deep_link(s: Snapshot, cfg: dict) -> Finding:
    """Where the profile's website field points.

    Only judged for a multi-location business, because for a single location
    the home page IS the right target and marking it wrong would be bad advice.
    Set business.multi_location in config.yaml to turn this on.
    """
    if not cfg.get("multi_location"):
        return _unknown("W4", "Website field points at this location's page",
                        "website", "multi-location")
    uri = s.location.get("websiteUri", "") or ""
    if not uri:
        return _unknown("W4", "Website field points at this location's page",
                        "website", "a linked website")
    path = re.sub(r"^https?://[^/]+", "", uri).split("?")[0]
    ok = len(path.strip("/")) > 0
    return Finding(
        "W4", "Website field points at this location's page", "medium",
        "website", ok,
        detail=(f"Points at {uri}" if ok else
                f"Points at the site root ({uri}), not this location's page."),
        why="On a multi-location business, every branch pointing at the same "
            "home page gives Google nothing to distinguish them, and sends the "
            "customer somewhere they have to search again for the branch they "
            "just clicked.",
        fix="Point each location's website field at that location's own page, "
            "with its own address, hours and phone on it.",
    )


@rule
def w5_service_area_pages(s: Snapshot, cfg: dict) -> Finding:
    if "site" not in s.available or not (s.site or {}).get("ok"):
        return _unknown("W5", "Site has pages per service and area", "website",
                        "the website")
    known = int(s.site.get("page_count") or 0)
    if not known:
        return _unknown("W5", "Site has pages per service and area", "website",
                        "a readable sitemap")

    services = len(s.location.get("serviceItems", []) or []) or \
        (1 + len(s.additional_categories))
    areas = len(s.get("serviceArea.places.placeInfos", []) or []) or 1
    # Not services x areas -- that is a page-farm and Google treats it as one.
    # The honest target is a page per main service, plus a page per main area.
    want = max(3, min(services, 8) + min(areas, 6))
    ok = known >= want
    return Finding(
        "W5", "Site has pages per service and area", "low", "website", ok,
        detail=f"{known} page(s) found on the site; roughly {want} would cover "
               f"{min(services, 8)} main service(s) and {min(areas, 6)} area(s).",
        why="A profile can only rank for what the linked site backs up. One "
            "page listing every service and every town gives Google one thing "
            "to rank; a page each gives it a set of specific things to rank.",
        fix="Build a page per main service, and a page per main area you serve. "
            "Write each one properly -- a service page with the town swapped "
            "out is duplicate content and will not rank.",
    )


# ============================================================= search keywords

@rule
def kw1_terms_available(s: Snapshot, cfg: dict) -> Finding:
    if "keywords" not in s.available:
        return _unknown("KW1", "Search terms people used", "keywords",
                        "search keyword")
    k = s.keywords
    total = int(k.get("total") or 0)
    return Finding(
        "KW1", "Search terms people used", "low", "keywords", True,
        informational=True,
        detail=(f"{total} search term(s) over {k.get('months', 'the period')}, "
                f"{int(k.get('impressions') or 0):,} impressions. "
                f"{int(k.get('discovery') or 0)} are not brand searches."),
        why="", fix="",
    )


@rule
def kw2_coverage(s: Snapshot, cfg: dict) -> Finding:
    if "keywords" not in s.available:
        return _unknown("KW2", "Profile uses the words people search for",
                        "keywords", "search keyword")
    k = s.keywords
    disc = int(k.get("discovery") or 0)
    if disc < int(cfg.get("min_keywords_to_judge", 5)):
        return _unknown("KW2", "Profile uses the words people search for",
                        "keywords", "enough search keyword")
    rate = float(k.get("covered_rate") or 0.0)
    want = float(cfg.get("min_keyword_coverage", 0.6))
    ok = rate >= want
    gaps = int(k.get("gap_count") or 0)
    return Finding(
        "KW2", "Profile uses the words people search for", "high", "keywords",
        ok,
        detail=(f"{rate:.0%} of the {disc} non-brand search terms appear "
                f"somewhere on the profile. {gaps} appear nowhere."),
        why="Google is telling you the exact words customers type to find you. "
            "A term you rank for but never mention is a term you rank for by "
            "accident, and a competitor who does mention it will take it. "
            "Putting those words back into the services and posts is the "
            "cheapest relevance you will ever buy.",
        fix="Add the missing terms to the Services section, each with a real "
            "description, and use them in posts. This tool can draft the "
            "services from the search data -- see `python run.py keywords`.",
        fixable=True, fix_key="services",
    )


@rule
def kw3_top_term_missing(s: Snapshot, cfg: dict) -> Finding:
    if "keywords" not in s.available:
        return _unknown("KW3", "Biggest search terms are covered", "keywords",
                        "search keyword")
    top = s.keywords.get("top_gap")
    ok = not top
    return Finding(
        "KW3", "Biggest search terms are covered", "high", "keywords", ok,
        detail=("Every high-volume term is reflected somewhere." if ok else
                f"\"{top.get('term')}\" showed the profile "
                f"{top.get('label')} times and appears nowhere on it."),
        why="The highest-volume term you are found for is the one worth "
            "defending. If the profile never says those words, the ranking "
            "rests on Google's inference rather than on anything you control.",
        fix="Add it as a named service with a description that uses the phrase "
            "naturally, and write a post about it.",
        fixable=True, fix_key="services",
    )


# ================================================================= competitors

@rule
def x1_reviews_vs_top3(s: Snapshot, cfg: dict) -> Finding:
    if "competitors" not in s.available:
        return _unknown("X1", "Reviews against the businesses beating you",
                        "competitors", "competitor")
    c = s.competitors
    ours, theirs = c.get("our_reviews"), c.get("avg_reviews")
    if ours is None or theirs is None:
        return _unknown("X1", "Reviews against the businesses beating you",
                        "competitors", "comparable review")

    # Within this share of the top-3 average is competitive. Being ahead is
    # obviously fine; the rule is about being far enough behind to be filtered
    # out before anyone reads the profile.
    want = float(cfg.get("min_review_share_of_top3", 0.7))
    share = ours / theirs if theirs else 1.0
    ok = share >= want
    gap = max(0, round(theirs - ours))
    return Finding(
        "X1", "Reviews against the businesses beating you", "high",
        "competitors", ok,
        detail=(f"You have {ours:,}. The top {c.get('rival_count', 3)} in your "
                f"map pack average {theirs:,.0f}"
                + (f" -- about {gap:,} behind." if gap else ".")),
        why="A fixed target like \"get 25 reviews\" is a guess at an average "
            "market. What matters is the gap to whoever is actually ranking "
            "above you, because that is who the customer is comparing you "
            "against in the same three-result list.",
        fix=(f"Closing {gap:,} reviews at a steady rate is the single highest-"
             f"value thing on this list. Ask every satisfied customer as the "
             f"job finishes. Never buy them and never offer anything in "
             f"exchange -- a sudden spike gets filtered and can cost the "
             f"profile."
             if gap else "Hold the lead by keeping the ask part of every job."),
    )


@rule
def x2_missing_categories(s: Snapshot, cfg: dict) -> Finding:
    if "competitors" not in s.available:
        return _unknown("X2", "Categories your competitors use", "competitors",
                        "competitor")
    c = s.competitors
    if not c.get("rival_count"):
        return _unknown("X2", "Categories your competitors use", "competitors",
                        "comparable competitor")
    missing = c.get("missing_categories") or []
    ok = not missing
    return Finding(
        "X2", "Categories your competitors use", "medium", "competitors", ok,
        detail=("No category is shared by your competitors and missing from "
                "your profile." if ok else
                f"{len(missing)} category(ies) used by two or more of the top "
                f"{c.get('rival_count')} and not on your profile: "
                f"{', '.join(missing[:6])}."),
        why="When two of the three businesses ranking above you carry the same "
            "category, that is how Google understands this market. A category "
            "you are missing is a set of searches you are not eligible for at "
            "all, whatever else the profile says.",
        fix="Add the ones you genuinely offer as secondary categories. Only "
            "those -- a category for work you do not do will bring calls you "
            "have to turn down, and dilutes the ones that matter.",
    )


@rule
def x3_photos_vs_top3(s: Snapshot, cfg: dict) -> Finding:
    if "competitors" not in s.available:
        return _unknown("X3", "Photos against the businesses beating you",
                        "competitors", "competitor")
    c = s.competitors
    ours, theirs = c.get("our_photos"), c.get("avg_photos")
    if ours is None or theirs is None:
        return _unknown("X3", "Photos against the businesses beating you",
                        "competitors", "comparable photo")

    want = float(cfg.get("min_photo_share_of_top3", 0.6))
    share = ours / theirs if theirs else 1.0
    ok = share >= want
    gap = max(0, round(theirs - ours))
    return Finding(
        "X3", "Photos against the businesses beating you", "medium",
        "competitors", ok,
        detail=(f"You have {ours:,}. The top {c.get('rival_count', 3)} average "
                f"{theirs:,.0f}"
                + (f" -- about {gap:,} behind." if gap else ".")),
        why="A thin gallery next to a competitor with three times the photos "
            "loses the click before anything else on the profile is read. Like "
            "reviews, the number that matters is theirs, not a fixed target.",
        fix="Add real photos of finished work until you are within reach of "
            "them, then keep adding a couple a week. Photos of the actual "
            "business, taken on site -- Google's guidelines require it.",
    )


@rule
def ci2_nap_consistency(s: Snapshot, cfg: dict) -> Finding:
    """Phone consistency across directory listings.

    There is no CI1. "Be on 40 to 50 directories" is a number training material
    repeats and citation vendors sell; consistency has evidence behind it,
    volume past the main aggregators does not. Scoring a profile down for
    having 30 listings instead of 50 would invent a problem.
    """
    if "citations" not in s.available:
        return _unknown("CI2", "Directory listings show the same phone number",
                        "offpage", "directory listing")
    c = s.citations
    if not c.get("read"):
        return _unknown("CI2", "Directory listings show the same phone number",
                        "offpage", "readable directory")

    bad = c.get("mismatched") or []
    ok = not bad
    names = ", ".join(b["domain"] for b in bad[:4])
    return Finding(
        "CI2", "Directory listings show the same phone number", "high",
        "offpage", ok,
        detail=(f"All {c['read']} readable listing(s) match." if ok else
                f"{len(bad)} of {c['read']} readable listing(s) show a "
                f"different number: {names}."),
        why="The same name, address and phone everywhere is one of the ways "
            "Google decides a business is real and its details are current. A "
            "number that disagrees across listings weakens that, and sends real "
            "customers to a line nobody answers.",
        fix="Claim each listing and correct the number to match the Google "
            "profile exactly. If one of them is an old tracking number, retire "
            "it -- tracking numbers belong on your own website, never on "
            "citations.",
    )


# ================================================================= performance

@rule
def pf1_discovery_share(s: Snapshot, cfg: dict) -> Finding:
    if "performance" not in s.available or not s.performance:
        return _unknown("PF1", "Found by people who did not know you", "performance",
                        "performance data")
    series = s.performance.get("multiDailyMetricTimeSeries", []) or []
    totals: dict[str, int] = {}
    for block in series:
        for item in block.get("dailyMetricTimeSeries", []) or []:
            metric = item.get("dailyMetric", "")
            points = (item.get("timeSeries", {}) or {}).get("datedValues", []) or []
            totals[metric] = totals.get(metric, 0) + sum(
                int(p.get("value", 0) or 0) for p in points)
    impressions = sum(v for k, v in totals.items() if "IMPRESSIONS" in k)
    actions = sum(totals.get(k, 0) for k in
                  ("CALL_CLICKS", "WEBSITE_CLICKS", "BUSINESS_DIRECTION_REQUESTS"))
    rate = (actions / impressions) if impressions else 0
    return Finding(
        "PF1", "Views turn into contacts", "medium", "performance", True,
        informational=True,
        detail=(f"{impressions:,} views and {actions:,} actions "
                f"(calls, clicks, directions) -- {rate:.1%} acted."),
        why="", fix="",
    )


def run_all(snapshot: Snapshot, cfg: dict | None = None) -> list[Finding]:
    cfg = cfg or {}
    return [fn(snapshot, cfg) for fn in RULES]
