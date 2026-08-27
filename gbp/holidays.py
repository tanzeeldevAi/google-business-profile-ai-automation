"""Which public holidays are coming up.

Deliberately conservative. A wrong holiday date published to a live profile
sends customers to a locked door, so this only ever returns dates it can be
certain about:

  * fixed-date holidays for the countries below
  * Easter, and the holidays anchored to it, by computation
  * US and Canadian Thanksgiving, by rule

Anything lunar or observation-based -- Eid al-Fitr, Eid al-Adha, Diwali,
Chinese New Year -- is NOT computed here, because the observed date varies by
country and is sometimes announced only days ahead. Those must be listed in
config.yaml under `holidays.extra`. The tool tells you when a country probably
needs them rather than inventing a date.
"""
from __future__ import annotations

from datetime import date, timedelta

# Countries whose main public holidays are lunar or otherwise not computable
# here. For these we warn rather than pretend the built-in list is complete.
NEEDS_MANUAL = {"AE", "SA", "PK", "QA", "KW", "OM", "BH", "EG", "MY", "ID",
                "BD", "TR", "MA", "JO", "IN", "CN", "SG", "VN"}

# month, day, name
FIXED: dict[str, list[tuple[int, int, str]]] = {
    "GB": [(1, 1, "New Year's Day"), (12, 25, "Christmas Day"),
           (12, 26, "Boxing Day")],
    "US": [(1, 1, "New Year's Day"), (7, 4, "Independence Day"),
           (11, 11, "Veterans Day"), (12, 25, "Christmas Day")],
    "CA": [(1, 1, "New Year's Day"), (7, 1, "Canada Day"),
           (11, 11, "Remembrance Day"), (12, 25, "Christmas Day"),
           (12, 26, "Boxing Day")],
    "AU": [(1, 1, "New Year's Day"), (1, 26, "Australia Day"),
           (4, 25, "Anzac Day"), (12, 25, "Christmas Day"),
           (12, 26, "Boxing Day")],
    "IE": [(1, 1, "New Year's Day"), (3, 17, "St Patrick's Day"),
           (12, 25, "Christmas Day"), (12, 26, "St Stephen's Day")],
    "NZ": [(1, 1, "New Year's Day"), (2, 6, "Waitangi Day"),
           (4, 25, "Anzac Day"), (12, 25, "Christmas Day"),
           (12, 26, "Boxing Day")],
    "AE": [(1, 1, "New Year's Day"), (12, 2, "UAE National Day")],
    "PK": [(2, 5, "Kashmir Day"), (3, 23, "Pakistan Day"),
           (8, 14, "Independence Day"), (12, 25, "Quaid-e-Azam Day")],
    "SA": [(9, 23, "Saudi National Day")],
    "IN": [(1, 26, "Republic Day"), (8, 15, "Independence Day"),
           (10, 2, "Gandhi Jayanti")],
    "ZA": [(1, 1, "New Year's Day"), (12, 25, "Christmas Day"),
           (12, 26, "Day of Goodwill")],
}

EASTER_ANCHORED = {
    "GB": [(-2, "Good Friday"), (1, "Easter Monday")],
    "IE": [(-2, "Good Friday"), (1, "Easter Monday")],
    "AU": [(-2, "Good Friday"), (1, "Easter Monday")],
    "NZ": [(-2, "Good Friday"), (1, "Easter Monday")],
    "CA": [(-2, "Good Friday")],
    "ZA": [(-2, "Good Friday"), (1, "Family Day")],
}


def easter(year: int) -> date:
    """Anonymous Gregorian algorithm. Exact for any year in range."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth weekday of a month. weekday: Monday=0 .. Sunday=6."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _computed(year: int, region: str) -> list[tuple[date, str]]:
    out: list[tuple[date, str]] = []
    e = easter(year)
    for delta, name in EASTER_ANCHORED.get(region, []):
        out.append((e + timedelta(days=delta), name))
    if region == "US":
        out.append((_nth_weekday(year, 11, 3, 4), "Thanksgiving"))   # 4th Thu
        out.append((_nth_weekday(year, 9, 0, 1), "Labor Day"))       # 1st Mon
        out.append((_nth_weekday(year, 5, 0, 5) if
                    _nth_weekday(year, 5, 0, 5).month == 5 else
                    _nth_weekday(year, 5, 0, 4), "Memorial Day"))    # last Mon
    if region == "CA":
        out.append((_nth_weekday(year, 10, 0, 2), "Thanksgiving"))   # 2nd Mon
    if region == "GB":
        out.append((_nth_weekday(year, 5, 0, 1), "Early May bank holiday"))
        aug = _nth_weekday(year, 8, 0, 5)
        out.append((aug if aug.month == 8 else _nth_weekday(year, 8, 0, 4),
                    "Summer bank holiday"))
    return out


def upcoming(region_code: str, within_days: int = 60,
             today: date | None = None,
             extra: list[dict] | None = None) -> list[tuple[date, str]]:
    """Holidays in the next `within_days`, soonest first.

    `extra` comes from config.yaml and is merged in, so a business can add the
    lunar dates this module refuses to guess:
        holidays:
          extra:
            - {date: 2026-03-20, name: Eid al-Fitr}
    """
    today = today or date.today()
    region = (region_code or "").upper()
    horizon = today + timedelta(days=within_days)

    found: list[tuple[date, str]] = []
    for year in {today.year, horizon.year}:
        for month, day, name in FIXED.get(region, []):
            try:
                found.append((date(year, month, day), name))
            except ValueError:
                continue
        found += _computed(year, region)

    for item in extra or []:
        try:
            d = item["date"]
            d = d if isinstance(d, date) else date.fromisoformat(str(d))
            found.append((d, str(item.get("name", "Holiday"))))
        except (KeyError, ValueError, TypeError):
            continue

    seen: set[tuple[date, str]] = set()
    out = []
    for d, name in sorted(found):
        if today <= d <= horizon and (d, name) not in seen:
            seen.add((d, name))
            out.append((d, name))
    return out


def needs_manual_dates(region_code: str) -> bool:
    return (region_code or "").upper() in NEEDS_MANUAL
