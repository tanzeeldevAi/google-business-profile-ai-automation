"""Is this machine's clock right?

A question that looks irrelevant to a Business Profile tool, until it costs an
afternoon. Google signs OAuth codes and tokens against real time. If the local
clock is out by more than a few minutes, every sign-in fails with
`invalid_grant` -- a message that says nothing about clocks and sends you
hunting through OAuth settings, redirect URIs and client secrets instead.

This was not hypothetical. The first machine this ran on was a full day behind,
and the only symptom was "sign in shows invalid grant".

Cheap to check: an HTTPS HEAD request has a `Date` header, so no time server or
extra dependency is needed.
"""
from __future__ import annotations

import email.utils
import time

import requests

# Google's own tolerance is small. A minute is generous for OAuth; five minutes
# is where token validation starts failing outright.
WARN_SECONDS = 60
FAIL_SECONDS = 300

_cached: tuple[float, float] | None = None  # (checked_at, skew)


def skew(timeout: int = 10, max_age: float = 300) -> float | None:
    """Seconds this machine is AHEAD of real time. Negative means behind.

    Returns None when the check itself could not run -- offline, blocked, or a
    server that sends no Date header. A failed check is never reported as a
    clock problem.
    """
    global _cached
    now = time.monotonic()
    if _cached and (now - _cached[0]) < max_age:
        return _cached[1]

    for url in ("https://accounts.google.com", "https://www.google.com"):
        try:
            resp = requests.head(url, timeout=timeout)
            header = resp.headers.get("Date")
            if not header:
                continue
            real = email.utils.parsedate_to_datetime(header).timestamp()
            # Take the reading at the midpoint of the request, so the round
            # trip is not counted as drift.
            value = time.time() - real
            _cached = (now, value)
            return value
        except (requests.RequestException, ValueError, TypeError):
            continue
    return None


def check(timeout: int = 10) -> dict:
    """A verdict the caller can show without doing any arithmetic."""
    value = skew(timeout=timeout)
    if value is None:
        return {"checked": False, "skew": None, "ok": True, "message": ""}

    off = abs(value)
    if off < WARN_SECONDS:
        return {"checked": True, "skew": round(value, 1), "ok": True,
                "message": f"Clock is accurate (within {off:.0f}s)."}

    direction = "ahead of" if value > 0 else "behind"
    if off >= 3600:
        amount = f"{off / 3600:.1f} hours"
    elif off >= 60:
        amount = f"{off / 60:.0f} minutes"
    else:
        amount = f"{off:.0f} seconds"

    return {
        "checked": True,
        "skew": round(value, 1),
        "ok": off < FAIL_SECONDS,
        "message": (
            f"This machine's clock is {amount} {direction} real time.\n"
            f"  Google signs sign-in codes against real time, so this makes "
            f"every sign-in\n  fail with 'invalid_grant' no matter what else "
            f"is configured.\n\n"
            f"  Fix it, then sign in again:\n"
            f"    Windows  Settings > Time & language > Date & time >\n"
            f"             Sync now  (and turn ON 'Set time automatically')\n"
            f"             or, in an admin terminal:  w32tm /resync /force\n"
            f"    macOS    System Settings > General > Date & Time >\n"
            f"             Set time and date automatically\n"
            f"    Linux    sudo timedatectl set-ntp true"
        ),
    }
