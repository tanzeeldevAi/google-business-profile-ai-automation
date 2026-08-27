"""Suspension and hijack watch.

A Google Business Profile can change without you touching it. Google applies
its own "updates", the public can suggest edits, a competitor can report the
listing, and reviews can be removed in bulk. The owner usually finds out weeks
later, when the phone stops ringing.

This takes a fingerprint of the fields that matter on every run and tells you
what moved since last time. It is the cheapest thing in this whole tool and it
is the one that saves an account.

Severity is about what the change costs you:

    critical  the profile is suspended, closed or unverified -- you are gone
              from the map pack right now
    high      identity changed under you (name, address, phone, website,
              primary category), or reviews disappeared
    medium    hours, categories or the description changed
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import db
from .rules import Snapshot

WATCHED_FIELDS = [
    ("title", "Business name"),
    ("websiteUri", "Website"),
    ("phoneNumbers.primaryPhone", "Phone number"),
    ("storefrontAddress.addressLines", "Street address"),
    ("storefrontAddress.locality", "City"),
    ("storefrontAddress.postalCode", "Postcode"),
    ("categories.primaryCategory.displayName", "Primary category"),
    ("openInfo.status", "Open status"),
    ("metadata.hasVoiceOfMerchant", "Verified"),
    ("metadata.hasPendingEdits", "Pending edits"),
    ("profile.description", "Description"),
]

HIGH = {"Business name", "Website", "Phone number", "Street address",
        "City", "Postcode", "Primary category"}
CRITICAL = {"Open status", "Verified"}


@dataclass
class Change:
    label: str
    before: Any
    after: Any
    severity: str

    def describe(self) -> str:
        def short(v: Any) -> str:
            s = "(empty)" if v in (None, "", [], {}) else str(v)
            return s if len(s) <= 90 else s[:87] + "..."
        return f"{self.label}: {short(self.before)}  ->  {short(self.after)}"


def fingerprint(snap: Snapshot) -> dict[str, Any]:
    fp: dict[str, Any] = {}
    for path, label in WATCHED_FIELDS:
        fp[label] = snap.get(path)
    fp["Category count"] = len(snap.additional_categories)
    fp["Review count"] = len(snap.reviews) if "reviews" in snap.available else None
    fp["Photo count"] = len(snap.media) if "media" in snap.available else None
    fp["Opening periods"] = len(snap.get("regularHours.periods", []) or [])
    fp["Special hours"] = len(snap.get("specialHours.specialHourPeriods", []) or [])
    return fp


def _severity(label: str, before: Any, after: Any) -> str:
    if label == "Verified" and before and not after:
        return "critical"
    if label == "Open status" and after not in ("OPEN", None, ""):
        return "critical"
    if label == "Pending edits" and after:
        return "high"
    if label == "Review count":
        # Reviews only ever going up is normal. A drop is Google removing them,
        # which is worth knowing about the same day.
        try:
            return "high" if int(after) < int(before) else "medium"
        except (TypeError, ValueError):
            return "medium"
    if label in CRITICAL:
        return "critical"
    if label in HIGH:
        return "high"
    return "medium"


def compare(previous: dict | None, current: dict) -> list[Change]:
    if not previous:
        return []
    changes: list[Change] = []
    for label, after in current.items():
        if label not in previous:
            continue
        before = previous[label]
        # A count we could not read this run is not a change.
        if after is None and before is not None:
            continue
        if before == after:
            continue
        changes.append(Change(label, before, after,
                              _severity(label, before, after)))
    order = {"critical": 0, "high": 1, "medium": 2}
    return sorted(changes, key=lambda c: order[c.severity])


def run(snap: Snapshot, location_name: str, *, save: bool = True) -> list[Change]:
    current = fingerprint(snap)
    previous = db.last_snapshot(location_name)
    changes = compare(previous, current)

    for c in changes:
        db.add_alert(location_name, c.severity, c.describe())

    if save:
        db.save_snapshot(location_name, current)
    return changes


def show(changes: list[Change], first_run: bool) -> None:
    if first_run:
        print("\n  First run -- baseline saved. From now on this reports what "
              "changed.\n")
        return
    if not changes:
        print("\n  Nothing changed since the last check.\n")
        return

    print(f"\n  {len(changes)} change(s) since the last check:\n")
    for c in changes:
        print(f"  {c.severity.upper():<9} {c.describe()}")

    if any(c.severity == "critical" for c in changes):
        print("\n  A CRITICAL change means the profile is not showing normally "
              "right now.")
        print("  Open Google Business Profile and check before doing anything "
              "else.")
    print()
