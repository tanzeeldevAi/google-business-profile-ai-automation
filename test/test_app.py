#!/usr/bin/env python3
"""The multi-business layer and the API's boundaries.

Offline: a temp database, no network, no server started.

The thing this file really guards is client separation. One install manages
several businesses, and `business.facts` is the ONLY thing the description
writer may assert. If those leaked between profiles, one client's claims would
end up on another client's public profile.

    python test/test_app.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="gbp-app-"))
from gbp import config  # noqa: E402
config.DATA_DIR = _tmp / "data"
config.REPORT_DIR = _tmp / "reports"
config.DB_PATH = config.DATA_DIR / "gbp.db"
# EVERY path, not just the database. Missing these two cost a real login: the
# sign-out test below deleted the operator's actual token.json because
# TOKEN_PATH still pointed at the live one. A test must never be able to touch
# real credentials.
config.TOKEN_PATH = config.DATA_DIR / "token.json"
config.CLIENT_SECRET_PATH = config.DATA_DIR / "client_secret.json"

from gbp import db, profiles, rules  # noqa: E402

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")


db.init()

print("\n== connecting businesses ==")
profiles.upsert("locations/1", "accounts/A", "Acme Plumbing", "Durham")
profiles.upsert("locations/2", "accounts/A", "Bright Dental", "Leeds")
check("both are listed", len(profiles.all_profiles()) == 2)
check("they are ordered by name",
      [p["title"] for p in profiles.all_profiles()] == ["Acme Plumbing", "Bright Dental"])

profiles.upsert("locations/1", "accounts/A", "Acme Plumbing Ltd", "Durham")
check("re-discovering updates rather than duplicating",
      len(profiles.all_profiles()) == 2)
check("the newer title wins",
      profiles.get("locations/1")["title"] == "Acme Plumbing Ltd")

print("\n== settings belong to ONE business ==")
profiles.save_settings("locations/1", {
    "business": {"facts": ["Gas Safe registered.", "Trading since 2009."]},
    "website": {"service_pages": ["https://acme.test/boiler-repair/"]},
})
profiles.save_settings("locations/2", {
    "business": {"facts": ["CQC registered."]},
})

BASE = {"business": {"name": "", "facts": []},
        "llm": {"model": "sonnet"}, "audit": {"min_photos": 20}}

one = profiles.settings_for(dict(BASE), "locations/1")
two = profiles.settings_for(dict(BASE), "locations/2")

check("each business gets its own facts",
      one["business"]["facts"] == ["Gas Safe registered.", "Trading since 2009."]
      and two["business"]["facts"] == ["CQC registered."])
check("one client's facts NEVER appear on another",
      "Gas Safe registered." not in two["business"]["facts"], str(two["business"]))
check("global settings survive the merge",
      one["llm"]["model"] == "sonnet" and one["audit"]["min_photos"] == 20)
check("the merged config points at the right location",
      one["location"] == {"account": "accounts/A", "name": "locations/1"})
check("the title fills in the business name when unset",
      one["business"]["name"] == "Acme Plumbing Ltd", one["business"]["name"])

check("a list REPLACES rather than merges",
      one["website"]["service_pages"] == ["https://acme.test/boiler-repair/"])

check("merging does not mutate the base config",
      BASE["business"]["facts"] == [], str(BASE))

print("\n== only per-business blocks may be stored ==")
profiles.save_settings("locations/1", {
    "business": {"facts": ["kept"]},
    "llm": {"model": "opus"},          # global: must not be storable per client
    "nonsense": {"x": 1},
})
stored = profiles.get("locations/1")["settings"]
check("a global block is refused", "llm" not in stored, str(stored.keys()))
check("an unknown block is refused", "nonsense" not in stored)
check("the real block is kept", stored["business"]["facts"] == ["kept"])

print("\n== which business is selected ==")
profiles.set_active("locations/2")
check("the active one is remembered", profiles.active() == "locations/2")
check("resolve prefers what was asked for",
      profiles.resolve({}, "locations/1") == ("accounts/A", "locations/1"))
check("resolve falls back to the active one",
      profiles.resolve({}, "") == ("accounts/A", "locations/2"))
check("a bare numeric id resolves",
      profiles.resolve({}, "1") == ("accounts/A", "locations/1"))
# The safety rule: asking for something that does not exist must NOT quietly
# act on whatever is selected. Acting on a different client than the one named
# is the worst failure this tool could have, so it returns nothing and the
# caller reports "no location matching ...".
check("an unknown location does NOT fall back to the active one",
      profiles.resolve({}, "zzz") == ("", ""))
check("an unknown location does NOT fall back to config.yaml either",
      profiles.resolve({"location": {"account": "accounts/Z", "name": "locations/9"}},
                       "zzz") == ("", ""))

profiles.set_active("")
check("config.yaml is the last resort when nothing was asked for",
      profiles.resolve({"location": {"account": "accounts/Z", "name": "locations/9"}},
                       "") == ("accounts/Z", "locations/9"))
check("nothing at all returns empty", profiles.resolve({}, "") == ("", ""))
profiles.set_active("locations/2")

print("\n== forgetting a business ==")
db.save_audit("locations/2", "Bright Dental", 71, "Needs work", [])
profiles.forget("locations/2")
check("it is removed from the list", profiles.get("locations/2") is None)
check("its audit history is KEPT",
      len(db.audit_history("locations/2")) == 1,
      "losing a client's before-and-after would be unrecoverable")
check("the selection clears when the selected one goes",
      profiles.active() == "")

print("\n== findings are stored in full ==")
f = rules.Finding("H1", "Profile is verified", "critical", "health", False,
                  "NOT verified.", "why it matters", "what to do",
                  fixable=True, fix_key="description")
d = f.to_dict()
for key in ("rule_id", "title", "severity", "category", "passed", "detail",
            "why", "fix", "fixable", "informational", "command"):
    check(f"to_dict carries {key}", key in d)
check("to_dict keeps the old id key for rows written by older versions",
      d["id"] == "H1")
check("the command that handles it is carried", d["command"] == "run.py fix",
      str(d["command"]))
check("a finding survives a JSON round trip",
      __import__("json").loads(__import__("json").dumps(d))["why"] == "why it matters")

print("\n== the API's command whitelist ==")
try:
    from fastapi import HTTPException
    from api.main import COMMANDS, build_argv

    argv = build_argv("audit", {}, False, "locations/1")
    check("a location is passed through",
          argv == ["audit", "--location", "locations/1"], str(argv))

    check("login is NOT given a location",
          "--location" not in build_argv("login", {}, False, "locations/1"))

    for bad in ["rm -rf /", "bash", "../run.py", ""]:
        try:
            build_argv(bad, {}, False, "")
            check(f"rejected: {bad!r}", False, "it built")
        except HTTPException:
            check(f"rejected: {bad!r}", True)

    try:
        build_argv("audit", {}, True, "")
        check("Apply refused on a read-only command", False)
    except HTTPException:
        check("Apply refused on a read-only command", True)

    try:
        build_argv("audit", {"evil": 1}, False, "")
        check("an unknown flag is refused", False)
    except HTTPException:
        check("an unknown flag is refused", True)

    for nasty in ["a\nb", "a\x00b"]:
        try:
            build_argv("compare", {"keywords": nasty}, False, "")
            check(f"control characters refused: {nasty!r}", False)
        except HTTPException:
            check(f"control characters refused: {nasty!r}", True)

    check("only these four commands write",
          {c for c, s in COMMANDS.items() if s["writes"]}
          == {"fix", "reviews", "post", "daily"})
except ImportError:
    check("fastapi is installed for the app tests", False,
          "pip install -r api/requirements.txt")

print("\n== signing in ==")
# The bug this replaced: `run.py login` returns instantly when a valid token
# already exists, without ever opening a browser — so "sign in as a different
# account" silently did nothing at all. The web flow owns the redirect instead,
# and forces the account picker.
import json as _json  # noqa: E402
import urllib.parse as _u  # noqa: E402
from gbp import auth as _auth  # noqa: E402

# A throwaway client, in the temp dir. Nothing here touches the real one.
config.CLIENT_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
config.CLIENT_SECRET_PATH.write_text(_json.dumps({"installed": {
    "client_id": "test.apps.googleusercontent.com",
    "client_secret": "not-a-real-secret",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["http://localhost"],
}}), encoding="utf-8")

_url = _auth.auth_url("http://127.0.0.1:8790/api/auth/callback", "st4te")
_q = dict(_u.parse_qsl(_u.urlparse(_url).query))
check("the consent URL points at Google",
      _u.urlparse(_url).netloc == "accounts.google.com", _url[:60])
check("it asks for offline access, so a refresh token comes back",
      _q.get("access_type") == "offline")
check("it forces the account picker, so switching accounts WORKS",
      "select_account" in _q.get("prompt", ""), str(_q.get("prompt")))
check("it carries the CSRF state", _q.get("state") == "st4te")
check("it asks for the one Business Profile scope",
      _q.get("scope") == "https://www.googleapis.com/auth/business.manage")
check("the redirect comes back to us",
      _q.get("redirect_uri") == "http://127.0.0.1:8790/api/auth/callback")

config.TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
config.TOKEN_PATH.write_text("{}", encoding="utf-8")
check("signing out removes the saved token", _auth.sign_out())
check("the token file is really gone", not config.TOKEN_PATH.exists())
check("signing out twice is harmless", _auth.sign_out() is False)

print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f_ in fails:
    print(f"  x {f_}")
sys.exit(1 if fails else 0)
