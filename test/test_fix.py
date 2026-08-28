"""The fixers: what they propose, and what they refuse to propose.

These matter more than most tests here, because a fix writes to a profile a
real customer reads. A service invented by mistake is a promise the business
did not make.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fixtures import bad_snapshot  # noqa: E402
from gbp import fix  # noqa: E402

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")


def svc(name: str) -> dict:
    return {"freeFormServiceItem": {"label": {"displayName": name}}}


def snap_with(names, locality="Peshawar"):
    s = bad_snapshot()
    s.location["serviceItems"] = [svc(n) for n in names]
    s.location["storefrontAddress"] = {"locality": locality}
    return s


print("\n== putting the city into service names ==\n")

plain = [f"Service {i}" for i in range(20)]
f = fix.plan_service_areas(snap_with(plain), {})
check("it proposes something when nothing names the area", f is not None)

if f:
    check("it renames only a handful, not the whole list",
          len(f.proposed) == 5, f"renamed {len(f.proposed)}")
    check("every rename ends in the city",
          all(p["name"].endswith("in Peshawar") for p in f.proposed))
    check("the body still carries every service, not just the renamed ones",
          len(f.body["serviceItems"]) == 20,
          str(len(f.body["serviceItems"])))
    check("it writes through the service list field",
          f.update_mask == "serviceItems")
    renamed = {p["name"] for p in f.proposed}
    kept = [i["freeFormServiceItem"]["label"]["displayName"]
            for i in f.body["serviceItems"]]
    check("renaming does not drop or duplicate anything",
          len(kept) == len(set(kept)) == 20)
    check("the renamed names are the ones in the body",
          renamed.issubset(set(kept)))

# Already done is done. Proposing a rename that changes nothing wastes a write
# and makes the audit look like it never clears.
enough = [f"S{i} in Peshawar" for i in range(5)] + plain[5:]
check("it proposes nothing once enough services already name the area",
      fix.plan_service_areas(snap_with(enough), {}) is None)

check("it proposes nothing when there are no services at all",
      fix.plan_service_areas(snap_with([]), {}) is None)

# Without a city there is nothing to add, and guessing one would put a place
# the business does not serve onto its own service list.
check("it refuses when the profile has no locality",
      fix.plan_service_areas(snap_with(plain, locality=""), {}) is None)

# Google's own structured service types carry a fixed label that is not ours
# to rewrite.
s = bad_snapshot()
s.location["serviceItems"] = [{"structuredServiceItem": {"serviceTypeId": "x"}}] * 6
s.location["storefrontAddress"] = {"locality": "Peshawar"}
check("it will not rename Google's own structured service types",
      fix.plan_service_areas(s, {}) is None)

print("\n== the plan survives being turned into data ==\n")

f = fix.plan_service_areas(snap_with(plain), {})
d = fix.to_dict(f)
check("the payload and field mask reach the app",
      d["update_mask"] == "serviceItems" and "serviceItems" in d["body"])
check("the proposals reach the app",
      len(d["proposed"]) == 5)
check("before and after are both shown",
      bool(d["before"]) and bool(d["after"]) and d["before"] != d["after"])

print()
for f_ in fails:
    print(f"  x {f_}")
print(f"\n  {pass_count} passed, {len(fails)} failed\n")
sys.exit(1 if fails else 0)
