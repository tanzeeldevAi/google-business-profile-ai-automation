"""Apply the fixes the audit found, through the API.

Rules this module obeys, without exception:

  1. Dry run is the default. Writing to a live profile requires --apply.
  2. It never invents a fact. The description is rewritten from what is already
     on the profile plus what you put in config.yaml. It will not claim an
     award, a certification, a year of founding or a price that it was not
     given.
  3. It shows you the exact before and after before writing anything.
  4. It writes narrow updateMasks, so a patch to the description cannot
     accidentally blank the phone number.

Only two things are auto-fixable. Everything else in the audit needs a person,
either because Google gives no write access or because the honest answer is a
judgement about the business.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import db, holidays, keywords, llm, site
from .api import Client
from .audit import AuditResult
from .rules import Snapshot

MAX_DESCRIPTION = 750


@dataclass
class Fix:
    key: str
    title: str
    before: str
    after: str
    update_mask: str
    body: dict[str, Any]
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ description

DESCRIPTION_SYSTEM = """You write Google Business Profile descriptions.

Hard rules, all enforced by Google or by the reader:
- 750 characters maximum. Aim for 600-740.
- No URLs, no email addresses, no phone numbers. Google strips them.
- No promotional claims, prices, discounts or "call now". Google rejects them.
- No superlatives you cannot prove: best, number one, leading, premier.
- State ONLY facts given to you. Never invent a founding year, a certification,
  an award, a number of staff, a guarantee or a price.
- Plain sentences. No marketing throat-clearing, no em-dashes, no bullet points.
- First sentence must say what the business does and where it operates.

Write in the third person, as the business. Output the description only."""


def _description_facts(snap: Snapshot, cfg: dict,
                       site_data: "site.Site | None" = None) -> str:
    loc = snap.location
    cat = snap.primary_category.get("displayName", "")
    extra = [c.get("displayName", "") for c in snap.additional_categories]
    services = []
    for item in loc.get("serviceItems", []) or []:
        label = (item.get("freeFormServiceItem", {}).get("label", {}) or {})
        name = label.get("displayName") or ""
        if name:
            services.append(name)
    areas = [p.get("placeName", "") for p in
             (snap.get("serviceArea.places.placeInfos", []) or [])]

    lines = [
        f"Business name: {snap.title}",
        f"Main category: {cat}",
        f"Other categories: {', '.join(c for c in extra if c) or 'none listed'}",
        f"City: {snap.locality or 'not set'}",
        f"Areas served: {', '.join(a for a in areas if a) or 'not set'}",
        f"Services on the profile: {', '.join(services) or 'none listed'}",
    ]
    existing = snap.get("profile.description", "") or ""
    if existing:
        lines.append(f"\nCurrent description (rewrite, keep any true fact in it):"
                     f"\n{existing}")
    owner = cfg.get("business", {}).get("facts", [])
    if owner:
        lines.append("\nExtra facts the owner has confirmed as true "
                     "(you may use these, and nothing beyond them):")
        lines += [f"- {f}" for f in owner]

    # The business's own website, when we could read it. This is what lets the
    # description use the company's real vocabulary and real service names
    # instead of a category label and a guess.
    if site_data is not None and site_data.ok:
        block = site.business_block(site_data)
        if block:
            lines.append("\nThe business's own website says the following. "
                         "You may use anything factual from it, and nothing "
                         "beyond it:\n" + block)
        if site_data.services:
            names = [p.h1 or p.title for p in site_data.services.values()]
            lines.append("\nService pages on the website: "
                         + "; ".join(n for n in names if n))
    return "\n".join(lines)


def plan_description(snap: Snapshot, cfg: dict,
                     site_data: "site.Site | None" = None) -> Fix | None:
    before = snap.get("profile.description", "") or ""
    facts = _description_facts(snap, cfg, site_data)
    prompt = (
        f"Write a Google Business Profile description from these facts.\n\n"
        f"{facts}\n\n"
        f"Remember: only the facts above. If a detail is not listed, leave it out."
    )
    text = llm.generate(prompt, system=DESCRIPTION_SYSTEM,
                        cfg=cfg.get("llm", {}))
    text = llm.clean(text)

    notes: list[str] = []
    if len(text) > MAX_DESCRIPTION:
        # Trim on a sentence boundary rather than mid-word.
        cut = text[:MAX_DESCRIPTION]
        dot = cut.rfind(". ")
        text = (cut[:dot + 1] if dot > 400 else cut).strip()
        notes.append(f"Trimmed to {len(text)} characters to fit Google's limit.")

    if not text or text == before:
        return None
    return Fix(
        key="description", title="Business description",
        before=before, after=text,
        update_mask="profile.description",
        body={"profile": {"description": text}},
        notes=notes,
    )


# --------------------------------------------------------------- holiday hours

def _period_for(day: date, closed: bool, open_h: int, close_h: int) -> dict:
    p: dict[str, Any] = {
        "startDate": {"year": day.year, "month": day.month, "day": day.day},
        "endDate": {"year": day.year, "month": day.month, "day": day.day},
        "closed": closed,
    }
    if not closed:
        p["openTime"] = {"hours": open_h, "minutes": 0}
        p["closeTime"] = {"hours": close_h, "minutes": 0}
    return p


def plan_holiday_hours(snap: Snapshot, cfg: dict,
                       site_data: "site.Site | None" = None) -> Fix | None:
    hcfg = cfg.get("holidays", {}) or {}
    region = snap.region_code or hcfg.get("region_code", "")
    if not region:
        return None

    horizon = int(hcfg.get("horizon_days", 60))
    upcoming = holidays.upcoming(region, horizon, extra=hcfg.get("extra"))
    if not upcoming:
        return None

    existing = snap.get("specialHours.specialHourPeriods", []) or []
    have = set()
    for p in existing:
        d = p.get("startDate", {})
        if d.get("year"):
            have.add((d["year"], d.get("month"), d.get("day")))

    default_closed = bool(hcfg.get("closed_by_default", True))
    open_h = int(hcfg.get("open_hour", 9))
    close_h = int(hcfg.get("close_hour", 17))
    overrides = {str(k): v for k, v in (hcfg.get("open_on") or {}).items()}

    added: list[str] = []
    periods = list(existing)
    for day, name in upcoming:
        if (day.year, day.month, day.day) in have:
            continue
        stay_open = str(day) in overrides or name in overrides
        periods.append(_period_for(day, not stay_open, open_h, close_h))
        added.append(f"{day} {name} -- {'open' if stay_open else 'closed'}")

    if not added:
        return None

    notes = [f"{len(added)} holiday(s) will be added:"] + [f"  {a}" for a in added]
    if holidays.needs_manual_dates(region):
        notes.append(
            f"NOTE: {region} has public holidays this tool will not guess "
            "(lunar or announced late). Add them under holidays.extra in "
            "config.yaml so they are not missed.")
    if default_closed:
        notes.append("Days default to CLOSED. If you trade on any of these, list "
                     "them under holidays.open_on before applying.")

    return Fix(
        key="holiday_hours", title="Holiday opening hours",
        before=f"{len(existing)} special-hours entries",
        after=f"{len(periods)} special-hours entries",
        update_mask="specialHours",
        body={"specialHours": {"specialHourPeriods": periods}},
        notes=notes,
    )


# -------------------------------------------------------------------- services

# Google's limits on a free-form service item.
MAX_SERVICE_NAME = 120
MAX_SERVICE_DESC = 300

SERVICES_SYSTEM = """You name services for a Google Business Profile.

You are given search terms real customers typed to find this business, grouped
by the job they describe, plus the business's own website copy.

For each group, output ONE line:

    Service name | description

Rules:
- The service NAME is what a customer would call the job, in title case, under
  8 words. Use the customer's own words from the search terms, not jargon.
- The DESCRIPTION is 2 to 3 plain sentences, under 300 characters. Say what
  the job covers, roughly how it works, and who it is for. Use the search
  phrasing naturally inside it, without repeating it word for word.
- Take every factual detail from the website copy provided. If the website
  does not say it, do not claim it. No prices, no timeframes, no guarantees,
  no numbers unless they appear in the copy.
- No marketing language, no superlatives, no "we are proud to".
- One line per group, same order as given, nothing else in your output."""


def _service_body(name: str, description: str, category_id: str,
                  language: str = "en") -> dict:
    item: dict[str, Any] = {
        "freeFormServiceItem": {
            "category": category_id,
            "label": {
                "displayName": name[:MAX_SERVICE_NAME],
                "description": description[:MAX_SERVICE_DESC],
                "languageCode": language,
            },
        }
    }
    return item


def plan_services(snap: Snapshot, cfg: dict,
                  site_data: "site.Site | None" = None,
                  analysis: "keywords.Analysis | None" = None) -> Fix | None:
    """Turn the search terms the profile ignores into named services.

    This is the highest-leverage thing in the tool. Google reports the exact
    words customers used; most profiles never say those words anywhere. Adding
    them as services with real descriptions puts the customer's own language
    back on the page they land on.

    It proposes, it does not decide. Every service is shown with the search
    terms that justified it, because a search term is evidence of demand, not
    proof the business offers the thing.
    """
    if analysis is None or not analysis.gaps:
        return None

    category_id = snap.primary_category.get("name", "")
    if not category_id:
        return None

    scfg = cfg.get("services", {}) or {}
    max_new = int(scfg.get("max_new", 6))

    groups = [g for g in keywords.cluster(analysis.gaps,
                                          max_groups=max_new * 2,
                                          drop=analysis.drop_stems)
              if keywords.worth_a_service(g)][:max_new]
    if not groups:
        return None

    site_block = (site.business_block(site_data, max_chars=1500)
                  if site_data and site_data.ok else "")
    existing = snap.location.get("serviceItems", []) or []
    existing_names = []
    for item in existing:
        label = (item.get("freeFormServiceItem", {}).get("label", {}) or {})
        if label.get("displayName"):
            existing_names.append(label["displayName"])

    lines = []
    for i, g in enumerate(groups, 1):
        terms = ", ".join(f'"{k.term}" ({k.label})' for k in g["terms"][:6])
        lines.append(f"{i}. {terms}")

    prompt = (
        f"Business: {snap.title}\n"
        f"Category: {snap.primary_category.get('displayName', '')}\n"
        f"City: {snap.locality}\n"
        f"Services already listed: {', '.join(existing_names) or 'none'}\n\n"
        f"Search term groups to name as services:\n" + "\n".join(lines)
        + (f"\n\nThe business's own website:\n{site_block}" if site_block else "")
        + f"\n\nOutput exactly {len(groups)} lines, one per group."
    )

    raw = llm.generate(prompt, system=SERVICES_SYSTEM, cfg=cfg.get("llm", {}))

    proposed: list[tuple[str, str, dict]] = []
    for line, group in zip(
            [l for l in raw.splitlines() if "|" in l], groups):
        name, _, desc = line.partition("|")
        name = re.sub(r"^\s*\d+[.)]\s*", "", name).strip()
        desc = desc.strip()
        if not name:
            continue
        # A number the website does not contain must not go on the profile.
        sources = (site_data.all_text if site_data and site_data.ok else "") + \
            " ".join(cfg.get("business", {}).get("facts", []) or [])
        bad = site.unverified_numbers(desc, sources) if sources.strip() else []
        if bad:
            desc = re.sub(r"[^.]*\b(" + "|".join(re.escape(b) for b in bad)
                          + r")\b[^.]*\.", "", desc).strip()
        proposed.append((name, desc, group))

    if not proposed:
        return None

    items = list(existing) + [
        _service_body(n, d, category_id,
                      cfg.get("posts", {}).get("language", "en"))
        for n, d, _g in proposed
    ]

    notes = [f"{len(proposed)} service(s) proposed from search terms the "
             f"profile does not mention:"]
    for name, desc, group in proposed:
        terms = ", ".join(k.term for k in group["terms"][:4])
        notes.append(f"  {name}")
        notes.append(f"      from: {terms}")
        notes.append(f"      {desc[:150]}")
    notes.append("")
    notes.append("A search term proves people looked for it. It does NOT prove "
                 "this business")
    notes.append("offers it. Read every line and remove anything they do not "
                 "actually do")
    notes.append("before applying -- a service on a profile is a promise.")

    return Fix(
        key="services", title="Services from search terms",
        before=f"{len(existing)} service(s) listed",
        after=f"{len(items)} service(s) listed",
        update_mask="serviceItems",
        body={"serviceItems": items},
        notes=notes,
    )


# ------------------------------------------------------------------- the driver

PLANNERS = {
    "description": plan_description,
    "holiday_hours": plan_holiday_hours,
    "services": plan_services,
}


def plan(result: AuditResult, snap: Snapshot, cfg: dict,
         only: list[str] | None = None,
         site_data: "site.Site | None" = None,
         analysis: "keywords.Analysis | None" = None) -> list[Fix]:
    """Build a fix for each failing rule that declares itself auto-fixable."""
    wanted: list[str] = []
    for f in result.failures:
        if f.fixable and f.fix_key in PLANNERS and f.fix_key not in wanted:
            if only and f.fix_key not in only:
                continue
            wanted.append(f.fix_key)

    fixes: list[Fix] = []
    for key in wanted:
        try:
            planner = PLANNERS[key]
            if key == "services":
                fix = planner(snap, cfg, site_data, analysis)
            else:
                fix = planner(snap, cfg, site_data)
        except llm.LLMError as exc:
            print(f"  ! could not plan '{key}': {exc}")
            continue
        if fix:
            fixes.append(fix)
    return fixes


def show(fixes: list[Fix]) -> None:
    if not fixes:
        print("\n  Nothing to fix automatically.\n")
        return
    for f in fixes:
        print("\n" + "-" * 72)
        print(f"  {f.title}   [{f.key}]")
        print("-" * 72)
        print(f"\n  BEFORE:\n    {f.before or '(empty)'}\n")
        print(f"  AFTER:\n    {f.after}\n")
        for n in f.notes:
            print(f"  {n}")
    print()


def apply(fixes: list[Fix], client: Client, location_name: str,
          *, dry_run: bool = True) -> int:
    """Write the fixes. Returns how many were actually sent."""
    if dry_run:
        print("  DRY RUN -- nothing was written. Re-run with --apply to write.")
        for f in fixes:
            db.record_action(location_name, "fix", f.key, f.after[:500],
                             dry_run=True)
        return 0

    done = 0
    for f in fixes:
        try:
            client.patch_location(location_name, f.body, f.update_mask)
        except Exception as exc:
            print(f"  x {f.title}: {exc}")
            continue
        db.record_action(location_name, "fix", f.key, f.after[:500])
        print(f"  + {f.title} updated.")
        done += 1
    if done:
        print("\n  Google can take a few minutes to show the change, and may "
              "hold larger edits for review.")
    return done
