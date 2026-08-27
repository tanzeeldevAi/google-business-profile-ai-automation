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

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import db, holidays, llm
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


def _description_facts(snap: Snapshot, cfg: dict) -> str:
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
    return "\n".join(lines)


def plan_description(snap: Snapshot, cfg: dict) -> Fix | None:
    before = snap.get("profile.description", "") or ""
    facts = _description_facts(snap, cfg)
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


def plan_holiday_hours(snap: Snapshot, cfg: dict) -> Fix | None:
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


# ------------------------------------------------------------------- the driver

PLANNERS = {
    "description": plan_description,
    "holiday_hours": plan_holiday_hours,
}


def plan(result: AuditResult, snap: Snapshot, cfg: dict,
         only: list[str] | None = None) -> list[Fix]:
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
            fix = PLANNERS[key](snap, cfg)
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
