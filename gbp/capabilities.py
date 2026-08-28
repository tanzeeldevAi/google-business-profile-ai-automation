"""What this Google project can actually do, right now.

Google splits the Business Profile across several APIs, and each one can be
off for its own reason. The failure that matters most is silent: publishing a
post to a project without the legacy API enabled returns 403, the job carries
on, and the operator is left looking at a profile with no post on it and no
idea why. That happened, and this module exists because of it.

Every probe answers three things:

    can we do it        yes / no
    why not             in words, not a status code
    what to click       the exact Cloud Console URL, with the project filled in

Probes are cheap reads. They are cached for a few minutes because an operator
who has just enabled an API will retry within seconds, and telling them it is
still off would be worse than useless.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from .api import ApiError, Client, split_location_id

# Each capability, the API behind it, and what stops working without it.
CAPABILITIES = [
    ("profile", "Profile, categories, hours, description",
     "mybusinessbusinessinformation.googleapis.com",
     "My Business Business Information API",
     "the audit, and every automatic fix"),
    ("performance", "Search terms and performance",
     "businessprofileperformance.googleapis.com",
     "Business Profile Performance API",
     "the words people typed to find this business"),
    ("reviews", "Reviews",
     "mybusiness.googleapis.com", "Google My Business API",
     "reading reviews and replying to them"),
    ("posts", "Google Posts",
     "mybusiness.googleapis.com", "Google My Business API",
     "publishing posts"),
    ("media", "Photos",
     "mybusiness.googleapis.com", "Google My Business API",
     "reading the photo gallery and photo cadence checks"),
    ("questions", "Questions and answers",
     "mybusinessqanda.googleapis.com", "My Business Q&A API",
     "the Q&A checks"),
]


@dataclass
class Capability:
    key: str
    label: str
    ok: bool
    reason: str = ""
    fix: str = ""
    link: str = ""
    breaks: str = ""


@dataclass
class Report:
    capabilities: list[Capability] = field(default_factory=list)
    project: str = ""
    checked_at: float = 0.0

    @property
    def blocked(self) -> list[Capability]:
        return [c for c in self.capabilities if not c.ok]

    @property
    def all_ok(self) -> bool:
        return not self.blocked

    def get(self, key: str) -> Capability | None:
        return next((c for c in self.capabilities if c.key == key), None)


_cache: dict[str, tuple[float, Report]] = {}


def _parse_403(exc: ApiError) -> tuple[str, str, str]:
    """Turn Google's 403 into (reason, what to do, link).

    The two 403s look identical from the outside and need completely different
    responses, so they are told apart here rather than reported as one thing:

        SERVICE_DISABLED  the API is off in your project. Two minutes to fix.
        anything else     the project is not approved for the API. A form, and
                          a wait of days.
    """
    body = exc.body or ""
    project = ""
    try:
        err = json.loads(body).get("error", {})
        message = err.get("message", "")
        reason = ""
        for detail in err.get("details", []) or []:
            reason = reason or detail.get("reason", "")
        match = re.search(r"project[s]?[/ ](\d+)", message)
        project = match.group(1) if match else ""

        if reason == "SERVICE_DISABLED" or "has not been used in project" in message:
            link = ""
            match = re.search(r"(https://console\.developers\.google\.com\S*?)\s", message + " ")
            if match:
                link = match.group(1).rstrip(".")
            return ("The API is switched off in your Google Cloud project.",
                    "Open the link, press ENABLE, then wait a minute and retry. "
                    "Nothing else needs changing.", link)

        if "not been allowlisted" in message or "PERMISSION_DENIED" in str(reason):
            return ("Your Google Cloud project is not approved for this API.",
                    "Fill in Google's Business Profile API access request form. "
                    "Approval takes a day to a couple of weeks.",
                    "https://developers.google.com/my-business/content/prereqs")
        return (message[:200] or "Google refused the request.", "", "")
    except (json.JSONDecodeError, AttributeError):
        pass

    # The body was not valid JSON (truncated, or an HTML error page). The two
    # things worth knowing are still findable in the raw text, so look for them
    # rather than showing the operator a wall of braces.
    if "has not been used in project" in body or "SERVICE_DISABLED" in body:
        link = ""
        match = re.search(r'https://console\.developers\.google\.com[^\s"\\]+', body)
        if match:
            link = match.group(0).rstrip(".")
        return ("The API is switched off in your Google Cloud project.",
                "Open the link, press ENABLE, then wait a minute and retry. "
                "Nothing else needs changing.", link)
    if "allowlist" in body.lower() or "not been approved" in body.lower():
        return ("Your Google Cloud project is not approved for this API.",
                "Fill in Google's Business Profile API access request form.",
                "https://developers.google.com/my-business/content/prereqs")

    message = re.search(r'"message"\s*:\s*"([^"]{10,300})"', body)
    return ((message.group(1) if message else "Google refused the request."),
            "", "")


def probe(client: Client, account: str, location: str,
          *, max_age: float = 180, force: bool = False) -> Report:
    """Try one cheap read per capability and record what happened."""
    now = time.time()
    if not force and location in _cache:
        when, cached = _cache[location]
        if now - when < max_age:
            return cached

    location_id = split_location_id(location)
    report = Report(checked_at=now)

    def attempt(fn):
        try:
            fn()
            return True, "", "", ""
        except ApiError as exc:
            if exc.status == 403:
                reason, fix, link = _parse_403(exc)
                return False, reason, fix, link
            if exc.status == 404:
                return (False, "Not available for this profile.",
                        "Some profile types do not expose this at all.", "")
            return False, f"Google returned {exc.status}.", "", ""
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}", "", ""

    checks = {
        "profile": lambda: client.location(location, read_mask="name,title"),
        "performance": lambda: client.search_keywords(
            location_id, _last_month()[0], _last_month()[1], max_pages=1),
        "reviews": lambda: client.reviews(account, location_id),
        "posts": lambda: client.local_posts(account, location_id),
        "media": lambda: client.media(account, location_id),
        "questions": lambda: client.questions(location),
    }

    for key, label, _host, api_name, breaks in CAPABILITIES:
        ok, reason, fix, link = attempt(checks[key])
        if not ok and not fix and "switched off" in reason:
            fix = f"Enable the {api_name} in Google Cloud Console."
        report.capabilities.append(Capability(
            key=key, label=label, ok=ok, reason=reason, fix=fix, link=link,
            breaks=breaks))
        if link and not report.project:
            match = re.search(r"project=(\d+)", link)
            report.project = match.group(1) if match else ""

    _cache[location] = (now, report)
    return report


def _last_month():
    """A one-month window the Performance API will accept."""
    from datetime import date, timedelta
    end = date.today().replace(day=1) - timedelta(days=1)
    return end.replace(day=1), end


def to_dict(report: Report) -> dict:
    return {
        "project": report.project,
        "checked_at": report.checked_at,
        "all_ok": report.all_ok,
        "capabilities": [
            {"key": c.key, "label": c.label, "ok": c.ok, "reason": c.reason,
             "fix": c.fix, "link": c.link, "breaks": c.breaks}
            for c in report.capabilities],
    }
