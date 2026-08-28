"""The facts on the profile: address, categories, phone, website.

The audit and the fixers deal with things that can be judged automatically --
is the description compliant, are the holidays set, do the services cover what
people search for. This module deals with the things only a person knows: the
business moved, it added a treatment room, the number changed.

Those edits were missing from the tool entirely, which meant the one time a
client actually moved, the answer was "log into Google and do it by hand". So
they live here, and they follow the same shape as the fixers: plan first,
render the before and after, write only when told.

Two rules run through all of it.

    Narrow masks.  Every write names exactly the field it touches. A profile
                   is a business's shopfront, and an address edit that blanks
                   the phone number because the mask was too wide is not a bug
                   you get to apologise for afterwards.

    No invention.  Nothing here writes a value it was not given. There is no
                   model in this file.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .api import Client

# Google's cap. One primary plus nine additional.
MAX_CATEGORIES = 10


@dataclass
class Change:
    """One field, what it is now, what it would become."""
    key: str
    title: str
    before: str
    after: str
    update_mask: str
    body: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


def _address_lines(address: dict) -> str:
    parts = list(address.get("addressLines") or [])
    for extra in ("locality", "administrativeArea", "postalCode"):
        if address.get(extra):
            parts.append(str(address[extra]))
    return ", ".join(p for p in parts if p)


def plan_address(location: dict, new_line: str, *,
                 locality: str = "", postal_code: str = "") -> Change | None:
    """Replace the street line, keeping every other part of the address.

    Only `addressLines` is rewritten. The country, city and postcode already on
    the profile are correct and are passed through untouched -- retyping them
    is how a good address becomes a broken one.
    """
    current = dict(location.get("storefrontAddress") or {})
    if not current:
        return None

    new_line = " ".join(new_line.split())
    if not new_line:
        return None

    updated = dict(current)
    updated["addressLines"] = [new_line]
    if locality:
        updated["locality"] = locality
    if postal_code:
        updated["postalCode"] = postal_code

    if updated == current:
        return None

    warnings = [
        "Google may ask the business to verify the profile again after an "
        "address change. A suite change inside the same building is usually "
        "accepted without that, but it is not guaranteed.",
    ]
    old_building = _building_hint(current.get("addressLines") or [])
    new_building = _building_hint([new_line])
    if old_building and new_building and old_building != new_building:
        warnings.append(
            f"The building name looks different ('{old_building}' -> "
            f"'{new_building}'). Re-verification is much more likely when the "
            f"business genuinely moves premises.")

    return Change(
        key="address", title="Street address",
        before=_address_lines(current), after=_address_lines(updated),
        update_mask="storefrontAddress",
        body={"storefrontAddress": updated},
        warnings=warnings,
    )


def _building_hint(lines: list[str]) -> str:
    """The building name from an address line, if one is recognisable.

    Only used to decide whether to warn harder about re-verification, so a
    miss costs nothing -- it just means the softer warning is shown.
    """
    for line in lines:
        for token in ("tower", "plaza", "centre", "center", "mall", "arcade",
                      "complex", "building"):
            lowered = line.lower()
            at = lowered.find(token)
            if at == -1:
                continue
            start = lowered.rfind(",", 0, at)
            return line[start + 1:at + len(token)].strip()
    return ""


def plan_categories(location: dict, primary: str = "",
                    additional: list[str] | None = None) -> Change | None:
    """Set the categories, by category id.

    `primary` and each entry of `additional` are ids like
    `categories/gcid:beauty_salon`. Names are not accepted, because two
    categories can read alike and guessing which one was meant is not
    something this should do on a live profile.
    """
    current = dict(location.get("categories") or {})
    now_primary = (current.get("primaryCategory") or {}).get("name", "")
    now_extra = [c.get("name", "")
                 for c in current.get("additionalCategories") or []]

    want_primary = primary or now_primary
    want_extra = list(additional) if additional is not None else list(now_extra)

    # The primary must not also appear in the additional list, and duplicates
    # are silently rejected by Google rather than reported.
    seen, deduped = {want_primary}, []
    for cat in want_extra:
        if cat and cat not in seen:
            seen.add(cat)
            deduped.append(cat)
    want_extra = deduped

    if want_primary == now_primary and want_extra == now_extra:
        return None

    warnings = []
    total = 1 + len(want_extra)
    if total > MAX_CATEGORIES:
        warnings.append(
            f"{total} categories requested but Google accepts "
            f"{MAX_CATEGORIES}. The last {total - MAX_CATEGORIES} would be "
            f"dropped.")
        want_extra = want_extra[:MAX_CATEGORIES - 1]
    if want_primary != now_primary:
        warnings.append(
            "The primary category is the single strongest ranking signal on a "
            "profile. Changing it can move the business in and out of results "
            "for its main searches.")
    for gone in now_extra:
        if gone not in want_extra:
            warnings.append(f"Removing a category: {_short(gone)}. The profile "
                            f"stops being eligible for searches that map to it.")

    body = {"categories": {
        "primaryCategory": {"name": want_primary},
        "additionalCategories": [{"name": c} for c in want_extra],
    }}
    return Change(
        key="categories", title="Categories",
        before=_describe_categories(now_primary, now_extra),
        after=_describe_categories(want_primary, want_extra),
        update_mask="categories", body=body, warnings=warnings,
    )


def _short(category_id: str) -> str:
    return category_id.replace("categories/gcid:", "").replace("_", " ")


def _describe_categories(primary: str, extra: list[str]) -> str:
    lines = [f"Primary: {_short(primary)}"]
    for cat in extra:
        lines.append(f"  also: {_short(cat)}")
    return "\n".join(lines)


def plan_simple(location: dict, *, phone: str = "",
                website: str = "") -> list[Change]:
    """Phone and website, which have no consequences beyond themselves."""
    out = []
    if phone:
        now = (location.get("phoneNumbers") or {}).get("primaryPhone", "")
        if phone.strip() != now:
            numbers = dict(location.get("phoneNumbers") or {})
            numbers["primaryPhone"] = phone.strip()
            out.append(Change(
                key="phone", title="Phone number", before=now or "(none)",
                after=phone.strip(), update_mask="phoneNumbers",
                body={"phoneNumbers": numbers}))
    if website:
        now = location.get("websiteUri", "")
        if website.strip() != now:
            out.append(Change(
                key="website", title="Website", before=now or "(none)",
                after=website.strip(), update_mask="websiteUri",
                body={"websiteUri": website.strip()}))
    return out


def show(changes: list[Change]) -> None:
    if not changes:
        print("\n  Nothing to change.\n")
        return
    for c in changes:
        print("\n" + "-" * 72)
        print(f"  {c.title}   [{c.key}]")
        print("-" * 72)
        print(f"\n  NOW:\n    {c.before or '(empty)'}\n")
        print(f"  AFTER:\n    {c.after}\n")
        for w in c.warnings:
            print(f"  ! {w}")
    print()


def apply(changes: list[Change], client: Client, location_name: str,
          *, dry_run: bool = True) -> int:
    """Write each change on its own, with its own narrow mask."""
    if dry_run:
        print("  DRY RUN -- nothing was written.")
        return 0

    done = 0
    for c in changes:
        try:
            client.patch_location(location_name, c.body, c.update_mask)
            print(f"  + {c.title} updated.")
            done += 1
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            print(f"  x {c.title} FAILED: {exc}")
    return done


def to_dict(change: Change) -> dict:
    return {"key": change.key, "title": change.title, "before": change.before,
            "after": change.after, "warnings": list(change.warnings)}


# --------------------------------------------------------------- service list

# Which category each service should hang off. Google requires the category on
# a free-form service to be one the business actually has, so this maps by
# subject rather than putting everything under the primary category -- a
# bridal makeup service filed under "skin care clinic" is technically valid and
# tells Google nothing.
SERVICE_CATEGORY_HINTS = [
    (("makeup", "bridal", "mehndi", "party"), "gcid:makeup_artist"),
    (("microblading", "lip blush", "brow"), "gcid:permanent_make_up_clinic"),
    (("lash",), "gcid:eyelash_salon"),
    (("hair rebonding", "keratin", "keratox", "hair botox", "nanoplastia",
      "olaplex", "haircut", "hair colour"), "gcid:hair_salon"),
    (("nail", "manicure", "pedicure"), "gcid:nail_salon"),
    (("waxing", "threading"), "gcid:waxing_hair_removal_service"),
    (("laser hair removal",), "gcid:laser_hair_removal_service"),
]


def _category_for(name: str, available: set[str], fallback: str) -> str:
    lowered = name.lower()
    for words, gcid in SERVICE_CATEGORY_HINTS:
        if any(w in lowered for w in words):
            full = f"categories/{gcid}"
            if full in available:
                return full
    return fallback


def plan_services(location: dict, spec: dict) -> Change | None:
    """Build the whole service list from a client-supplied price list.

    Two things happen at once, and they are different in kind:

      the structured items already on the profile keep their Google service
      type and gain a description, because Google's own types rank better than
      free text and throwing them away to retype them would be a downgrade;

      everything else is added as a free-form service with a price.

    Nothing here is generated. Every name, price and sentence comes from the
    spec file, which comes from the client's own price list.
    """
    existing = location.get("serviceItems") or []
    cats = location.get("categories") or {}
    primary = (cats.get("primaryCategory") or {}).get("name", "")
    available = {primary} | {c.get("name", "")
                             for c in cats.get("additionalCategories") or []}
    currency = spec.get("currency", "PKR")
    descriptions = spec.get("structured_descriptions") or {}

    items: list[dict] = []
    kept, described = 0, 0
    for item in existing:
        structured = item.get("structuredServiceItem")
        if not structured:
            continue  # free-form entries are rebuilt from the spec below
        type_id = structured.get("serviceTypeId", "")
        entry: dict[str, Any] = {"structuredServiceItem": {
            "serviceTypeId": type_id}}
        text = descriptions.get(type_id)
        if text:
            entry["structuredServiceItem"]["description"] = text
            described += 1
        if item.get("price"):
            entry["price"] = item["price"]
        items.append(entry)
        kept += 1

    added = 0
    for svc in spec.get("free_form") or []:
        name = (svc.get("name") or "").strip()
        if not name:
            continue
        entry = {"freeFormServiceItem": {
            "category": _category_for(name, available, primary),
            "label": {"displayName": name[:120],
                      "description": (svc.get("description") or "")[:300],
                      "languageCode": "en"},
        }}
        price = svc.get("price")
        if price:
            entry["price"] = {"currencyCode": currency,
                              "units": str(int(price)), "nanos": 0}
        items.append(entry)
        added += 1

    if not items:
        return None

    return Change(
        key="services", title="Service list",
        before=f"{len(existing)} service(s), "
               f"{sum(1 for i in existing if _has_description(i))} with a description",
        after=f"{len(items)} service(s): {kept} kept from Google's own types "
              f"({described} given a description) and {added} added with prices",
        update_mask="serviceItems",
        body={"serviceItems": items},
        warnings=["Every name and price here comes from the client's price "
                  "list. Check it still matches what they charge today."],
    )


def _has_description(item: dict) -> bool:
    structured = item.get("structuredServiceItem") or {}
    if structured.get("description"):
        return True
    label = (item.get("freeFormServiceItem") or {}).get("label") or {}
    return bool(label.get("description"))
