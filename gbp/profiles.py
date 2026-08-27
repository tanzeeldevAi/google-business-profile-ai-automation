"""The connected businesses, and which one you are working on.

This is what turns the tool from a script pointed at one profile into
something you can run an agency from. Instead of hand-editing config.yaml with
an account id and a location id, you connect a Google account once, the tool
discovers every profile it manages, and you pick one.

Two layers of settings, and the split matters:

    config.yaml    how the TOOL behaves -- thresholds, model, image backend,
                   rate limits. Shared by every business.
    the profile    what this BUSINESS is -- its name, its city, the facts it
                   has confirmed, its service page URLs, its competitor
                   keywords. Different for every business.

`settings_for()` merges them, profile over config, so a client's confirmed
facts can never leak into another client's description. That is not a
convenience: `business.facts` is the ONLY thing the description writer is
allowed to assert, so getting this wrong would put one business's claims on
another's public profile.
"""
from __future__ import annotations

import copy
import json
import time
from typing import Any

from . import db

# Only these blocks may be set per business. Everything else stays global,
# because it describes the tool rather than the client.
PER_PROFILE_KEYS = ("business", "website", "competitors", "holidays", "posts")

ACTIVE_KEY = "active_location"


def _merge(base: dict, over: dict) -> dict:
    """Deep merge, `over` winning. Lists replace rather than concatenate --
    a client's service pages are not an addition to the defaults."""
    out = copy.deepcopy(base)
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# ------------------------------------------------------------------- storage

def upsert(location: str, account: str, title: str = "", city: str = "") -> None:
    """Record a profile we can see. Never clobbers its saved settings."""
    now = time.time()
    with db.conn() as cx:
        cx.execute(
            "INSERT INTO profiles (location, account, title, city, settings, "
            "added_at, last_seen) VALUES (?,?,?,?,'{}',?,?) "
            "ON CONFLICT(location) DO UPDATE SET account=excluded.account, "
            "title=excluded.title, city=excluded.city, last_seen=excluded.last_seen",
            (location, account, title, city, now, now))


def all_profiles() -> list[dict]:
    with db.conn() as cx:
        rows = cx.execute(
            "SELECT * FROM profiles ORDER BY title COLLATE NOCASE").fetchall()
    return [_row(r) for r in rows]


def get(location: str) -> dict | None:
    with db.conn() as cx:
        row = cx.execute("SELECT * FROM profiles WHERE location=?",
                         (location,)).fetchone()
    return _row(row) if row else None


def _row(row) -> dict:
    d = dict(row)
    try:
        d["settings"] = json.loads(d.get("settings") or "{}")
    except json.JSONDecodeError:
        d["settings"] = {}
    return d


def forget(location: str) -> bool:
    """Remove a profile from the list. Its audit history is kept -- losing a
    client's before-and-after because somebody tidied the list would be bad."""
    with db.conn() as cx:
        changed = cx.execute("DELETE FROM profiles WHERE location=?",
                             (location,)).rowcount
    if active() == location:
        set_active("")
    return bool(changed)


def save_settings(location: str, settings: dict) -> None:
    """Replace this business's settings. Unknown blocks are dropped rather
    than stored, so the UI cannot smuggle in a global setting."""
    clean = {k: v for k, v in (settings or {}).items() if k in PER_PROFILE_KEYS}
    with db.conn() as cx:
        cx.execute("UPDATE profiles SET settings=? WHERE location=?",
                   (json.dumps(clean), location))


# -------------------------------------------------------------- which is live

def active() -> str:
    with db.conn() as cx:
        row = cx.execute("SELECT v FROM app_state WHERE k=?",
                         (ACTIVE_KEY,)).fetchone()
    return row["v"] if row else ""


def set_active(location: str) -> None:
    with db.conn() as cx:
        cx.execute("INSERT INTO app_state (k, v) VALUES (?,?) "
                   "ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                   (ACTIVE_KEY, location))


def resolve(cfg: dict, wanted: str = "") -> tuple[str, str]:
    """Work out which account and location to act on, without the network.

    Order, most explicit first:
        1. what was asked for (--location, or the dashboard's choice)
        2. the profile marked active
        3. config.yaml
    Returns ("", "") when it cannot tell, and the caller falls back to asking
    Google -- which is the slow path, so this exists to avoid it.
    """
    def find(candidate: str) -> tuple[str, str]:
        if not candidate:
            return "", ""
        profile = get(candidate)
        if profile:
            return profile["account"], profile["location"]
        # A bare numeric id is a reasonable thing to type.
        for p in all_profiles():
            if p["location"].split("/")[-1] == candidate.split("/")[-1]:
                return p["account"], p["location"]
        return "", ""

    if wanted:
        # Asked for something specific. If it does not resolve, say so by
        # returning nothing -- do NOT quietly fall back to whichever business
        # happens to be selected. Acting on a different client than the one
        # named is the worst failure this tool could have.
        return find(wanted)

    account, location = find(active())
    if account:
        return account, location

    loc_cfg = cfg.get("location", {}) or {}
    if loc_cfg.get("name") and loc_cfg.get("account"):
        return loc_cfg["account"], loc_cfg["name"]
    return "", ""


def settings_for(cfg: dict, location: str) -> dict:
    """config.yaml with this business's own settings layered on top."""
    profile = get(location)
    if not profile:
        return cfg
    merged = _merge(cfg, profile["settings"])
    # Keep the tool's own idea of what it is pointed at in step with the
    # profile, so anything still reading cfg["location"] agrees.
    merged["location"] = {"account": profile["account"],
                          "name": profile["location"]}
    # Fall back to what Google calls the business. `setdefault` is not enough:
    # config.yaml ships with these keys present but empty, and an empty name is
    # the same as no name for every writer that reads it.
    business = merged.setdefault("business", {})
    if not business.get("name"):
        business["name"] = profile.get("title") or ""
    if not business.get("city"):
        business["city"] = profile.get("city") or ""
    return merged


def describe(location: str) -> str:
    p = get(location)
    if not p:
        return location or "(nothing selected)"
    where = f" ({p['city']})" if p.get("city") else ""
    return f"{p.get('title') or p['location']}{where}"
