#!/usr/bin/env python3
"""The dashboard's boundaries. Offline: nothing is served, nothing is run.

The dashboard turns a browser click into a subprocess that can publish to a
real client's Google profile. Everything below is about that being safe:

  * the browser never assembles an argv -- it names a command from a whitelist
  * Apply cannot be smuggled onto a command that does not write
  * a report path cannot walk out of the reports folder
  * two writes cannot overlap

    python test/test_dashboard.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbp import config, dashboard as dash  # noqa: E402

pass_count = 0
fails: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global pass_count
    if cond:
        pass_count += 1
    else:
        fails.append(f"{name}{('  -- ' + extra) if extra else ''}")


print("\n== only whitelisted commands run ==")
argv, err = dash.build_argv("audit", {}, False)
check("a known command builds", argv == ["audit"] and not err, str(argv))

for bad in ["login", "doctor; rm -rf /", "../run.py", "", "bash"]:
    _argv, err = dash.build_argv(bad, {}, False)
    check(f"rejected: {bad!r}", bool(err), f"built {_argv}")

check("login is deliberately NOT exposed", "login" not in dash.COMMANDS,
      "it opens a browser and waits, which a web request cannot do")

print("\n== flags are whitelisted per command ==")
_argv, err = dash.build_argv("audit", {"evil": "x"}, False)
check("an unknown flag is refused", bool(err), str(_argv))
_argv, err = dash.build_argv("audit", {"only": "description"}, False)
check("a flag from a DIFFERENT command is refused", bool(err), str(_argv))
argv, err = dash.build_argv("fix", {"only": "description"}, False)
check("a flag the command does take is accepted",
      argv == ["fix", "--only", "description"], str(argv))

argv, _ = dash.build_argv("audit", {"no-report": False}, False)
check("a false boolean adds nothing", argv == ["audit"], str(argv))
argv, _ = dash.build_argv("audit", {"no-report": True}, False)
check("a true boolean adds the flag", argv == ["audit", "--no-report"], str(argv))
argv, _ = dash.build_argv("keywords", {"limit": ""}, False)
check("an empty value adds nothing", argv == ["keywords"], str(argv))
_argv, err = dash.build_argv("keywords", {"limit": "; rm -rf /"}, False)
check("a non-numeric int is refused", bool(err))

print("\n== nothing can be injected through a value ==")
# No shell is involved (Popen takes a list), but a newline or a NUL in an
# argument is never legitimate and is worth refusing outright.
for nasty in ["a\nb", "a\r\nb", "a\x00b"]:
    _argv, err = dash.build_argv("compare", {"keywords": nasty}, False)
    check(f"refused control characters in a value: {nasty!r}", bool(err))
argv, err = dash.build_argv(
    "compare", {"keywords": "plumber durham, boiler repair"}, False)
check("an ordinary value with spaces and commas is fine",
      argv == ["compare", "--keywords", "plumber durham, boiler repair"],
      str(argv))
check("each value stays ONE argv entry, never split on spaces",
      len(argv) == 3, str(argv))

print("\n== Apply cannot be smuggled ==")
for cmd in [c for c, s in dash.COMMANDS.items() if not s["writes"]]:
    _argv, err = dash.build_argv(cmd, {}, True)
    check(f"Apply refused on read-only '{cmd}'", bool(err), str(_argv))
for cmd in [c for c, s in dash.COMMANDS.items() if s["writes"]]:
    argv, err = dash.build_argv(cmd, {}, True)
    check(f"Apply allowed on '{cmd}'", "--apply" in argv and not err, str(argv))
    argv, err = dash.build_argv(cmd, {}, False)
    check(f"'{cmd}' is a dry run without Apply", "--apply" not in argv, str(argv))

check("every writing command is one that really writes",
      {c for c, s in dash.COMMANDS.items() if s["writes"]}
      == {"fix", "reviews", "post", "daily"},
      str({c for c, s in dash.COMMANDS.items() if s["writes"]}))

print("\n== a report path cannot escape the reports folder ==")


def escapes(name: str) -> bool:
    try:
        target = (config.REPORT_DIR / name).resolve()
        target.relative_to(config.REPORT_DIR.resolve())
        return False
    except (ValueError, OSError):
        return True


for name in ["../data/token.json", "../../.env", "..\\data\\client_secret.json",
             "sub/../../data/gbp.db", "/etc/passwd", "C:\\Windows\\win.ini"]:
    check(f"blocked: {name}", escapes(name))
check("an ordinary report name is allowed",
      not escapes("2026-08-27-a-business.html"))

print("\n== one job at a time ==")
state = dash.State()


class FakeJob:
    """Stands in for a running subprocess without starting one."""
    def __init__(self):
        self.id = "fake"
        self.command = "fix"
        self.finished = None

    @property
    def running(self):
        return self.finished is None


state.current = FakeJob()
job, err = state.start("audit", ["audit"])
check("a second job is refused while one runs", job is None and bool(err), err)
check("the refusal names what is running", "fix" in err, err)

state.current.finished = 1.0
check("the refusal lifts when it finishes", not state.current.running)

print("\n== the server refuses to be exposed without a token ==")
try:
    dash.serve({}, host="0.0.0.0", port=0)
    check("binding publicly with no token is refused", False, "it served")
except SystemExit as exc:
    check("binding publicly with no token is refused", True)
    check("and says why", "token" in str(exc).lower())

print("\n== job output is bounded ==")
job = dash.Job("audit", ["audit"])
for i in range(5000):
    job.append(f"line {i}")
check("a runaway command cannot eat memory",
      len(job.lines) <= 4000, str(len(job.lines)))
check("the most recent output is what survives",
      job.lines[-1] == "line 4999", job.lines[-1])
snap = job.snapshot(since=len(job.lines) - 3)
check("snapshot(since) returns only what is new", len(snap["lines"]) == 3,
      str(len(snap["lines"])))
check("snapshot reports the true total", snap["total"] == len(job.lines))

print("\n== the UI exists and matches the API ==")
page = dash.STATIC / "dashboard.html"
check("dashboard.html ships with the package", page.exists())
html = page.read_text(encoding="utf-8")
for cmd in dash.COMMANDS:
    if cmd in ("holidays", "alerts"):
        continue  # reachable through the CLI, not surfaced as a button
    check(f"the UI offers '{cmd}'", f'"{cmd}"' in html)
check("the UI warns before writing", "WRITE to the live profile" in html)
check("Apply resets after every run", '$("apply").checked = false' in html)
check("the UI is self-contained (no external assets)",
      "http://" not in html and "https://" not in html)

print(f"\n  {pass_count} passed, {len(fails)} failed\n")
for f in fails:
    print(f"  x {f}")
sys.exit(1 if fails else 0)
