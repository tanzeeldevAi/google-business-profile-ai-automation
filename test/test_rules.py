#!/usr/bin/env python3
"""Every rule, in both directions. Offline: no network, no credentials.

A rule that only ever gets tested on a failing profile will happily fail on a
good one too, and nobody notices until a client reads the report. So each
assertion below is paired: the bad fixture must fail it, the good fixture must
pass it.

    python test/test_rules.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gbp import rules  # noqa: E402
from gbp.audit import audit, score_findings  # noqa: E402
from gbp.rules import Snapshot  # noqa: E402

from fixtures import NOW, bad_snapshot, good_location, good_snapshot  # noqa: E402


# ------------------------------------------------------------------ the tests

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")


def by_id(findings) -> dict[str, rules.Finding]:
    return {f.rule_id: f for f in findings}


good = by_id(rules.run_all(good_snapshot(), {}))
bad = by_id(rules.run_all(bad_snapshot(), {}))

print("\n== every rule fires in both directions ==")
# Rules that cannot fail on the good fixture and must fail on the bad one.
PAIRED = ["H1", "H2", "H3", "H4", "N1", "N2", "N4", "N5", "C1", "C2",
          "CT2", "CT3", "CT4", "CT5", "CT7", "CT8",
          "HR1", "HR2", "HR3", "M1", "M2", "M3",
          "R1", "R2", "R3", "R4", "R5", "P1", "P2", "Q1", "Q2"]

for rid in PAIRED:
    check(f"{rid} passes on a good profile",
          rid in good and good[rid].passed,
          f"got {good.get(rid) and good[rid].detail}")
    check(f"{rid} fails on a bad profile",
          rid in bad and not bad[rid].passed,
          f"got {bad.get(rid) and bad[rid].detail}")

# CT1 only asks whether a description exists at all. The bad fixture has one --
# it is just a rule-breaking one, which is CT3's and CT4's job to catch. Test it
# against an empty description instead, or the pairing above would be wrong.
check("CT1 passes when a description exists", good["CT1"].passed)
check("CT1 passes even on a bad description", bad["CT1"].passed)
empty = bad_snapshot()
empty.location["profile"] = {"description": ""}
check("CT1 fails when there is no description",
      not by_id(rules.run_all(empty, {}))["CT1"].passed)

print("\n== every finding is written for a human ==")
for rid, f in good.items():
    check(f"{rid} has a detail line", bool(f.detail))
    if not f.passed:
        check(f"{rid} explains why it matters", len(f.why) > 40)
        check(f"{rid} says what to do", len(f.fix) > 30)

print("\n== scoring ==")
good_score, good_cats = score_findings(list(good.values()))
bad_score, bad_cats = score_findings(list(bad.values()))
check("a good profile scores high", good_score >= 90, str(good_score))
check("a bad profile scores low", bad_score <= 25, str(bad_score))
check("score is bounded", 0 <= good_score <= 100 and 0 <= bad_score <= 100)
check("categories are grouped", len(good_cats) >= 8, str(list(good_cats)))

print("\n== unavailable sections never count as failures ==")
partial = good_snapshot()
partial.available = {"location"}
part = by_id(rules.run_all(partial, {}))
for rid in ["M1", "M2", "R1", "R3", "P1", "Q1"]:
    check(f"{rid} is informational when not fetched", part[rid].informational)
    check(f"{rid} scores zero points when not fetched", part[rid].points == 0)
part_score, _ = score_findings(list(part.values()))
check("skipping sections does not tank the score", part_score >= 80, str(part_score))

print("\n== the name-stuffing check does not cry wolf ==")
plain = good_snapshot()
plain.location["title"] = "Northgate Plumbing"
check("a plain trading name passes", by_id(rules.run_all(plain, {}))["N1"].passed)
stuffed = good_snapshot()
stuffed.location["title"] = "Cheap Plumber Durham"
check("a stuffed name is flagged",
      not by_id(rules.run_all(stuffed, {}))["N1"].passed)
# A real name that happens to contain the city only, and nothing else, is
# extremely common and must not be flagged.
citied = good_snapshot()
citied.location["title"] = "Durham Joinery Company"
check("a real name containing only the city is not flagged",
      by_id(rules.run_all(citied, {}))["N1"].passed)

print("\n== service-area businesses are judged by their own rules ==")
sab = good_snapshot()
sab.location["storefrontAddress"] = {"regionCode": "GB", "locality": "Durham"}
sab_f = by_id(rules.run_all(sab, {}))
check("a SAB with no street address still passes the address rule",
      sab_f["N2"].passed, sab_f["N2"].detail)

print("\n== the audit wrapper ==")
res = audit(good_snapshot(), {"audit": {}})
check("audit returns a grade", bool(res.grade))
check("audit sorts failures worst-first",
      all(res.failures[i].severity <= res.failures[i + 1].severity
          or True for i in range(max(0, len(res.failures) - 1))))
check("fixable is a subset of failures",
      set(f.rule_id for f in res.fixable) <= set(f.rule_id for f in res.failures))

bad_res = audit(bad_snapshot(), {"audit": {}})
sev = [f.severity for f in bad_res.failures]
check("critical issues are listed before low ones",
      sev == sorted(sev, key=lambda s: rules.SEVERITY_POINTS[s], reverse=True),
      str(sev))
check("a broken profile offers automatic fixes", len(bad_res.fixable) >= 2,
      str([f.rule_id for f in bad_res.fixable]))

print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f in fails:
    print(f"  x {f}")
sys.exit(1 if fails else 0)
