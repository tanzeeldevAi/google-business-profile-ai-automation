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

print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f_ in fails:
    print(f"  x {f_}")
sys.exit(1 if fails else 0)
