"""The HTTP API behind the React app.

    uvicorn api.main:app --port 8790

Everything the UI can do goes through here. Two kinds of endpoint:

  READ    answer straight from the database or a live API call. Fast, safe,
          used to paint a screen.
  JOB     start one of the CLI commands and stream its output back. Slow,
          sometimes writes, always shows you exactly what it ran.

Jobs shell out to `run.py` rather than importing the code. That is deliberate:
the CLI, the old dashboard and this API then cannot drift apart about what a
command does, and a job that crashes takes a subprocess down rather than the
server.

SAFETY, in the same three rules the CLI obeys:
  * dry run unless `apply` is explicitly true, and only on commands that write
  * one job at a time -- two writes to one profile is how you corrupt it
  * bound to localhost unless a token is set
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gbp import auth, config, db, profiles  # noqa: E402
from gbp.api import ApiError, Client, split_location_id  # noqa: E402
from gbp.auth import AuthError  # noqa: E402

TOKEN = os.environ.get("GBP_API_TOKEN", "")

# The only commands the API may run, and the only flags each accepts. A
# whitelist, not a filter: the browser never assembles an argv.
COMMANDS: dict[str, dict] = {
    "doctor":    {"writes": False, "flags": {}},
    "audit":     {"writes": False, "flags": {"no-report": "bool"}},
    "site":      {"writes": False, "flags": {"refresh": "bool", "url": "str"}},
    "keywords":  {"writes": False, "flags": {"csv": "bool", "limit": "int"}},
    "compare":   {"writes": False, "flags": {"keywords": "str"}},
    "citations": {"writes": False, "flags": {}},
    "watch":     {"writes": False, "flags": {}},
    "holidays":  {"writes": False, "flags": {"region": "str", "days": "int"}},
    "locations": {"writes": False, "flags": {}},
    "login":     {"writes": False, "flags": {}},
    "fix":       {"writes": True,  "flags": {"only": "str"}},
    "reviews":   {"writes": True,  "flags": {"include-held": "bool"}},
    "post":      {"writes": True,  "flags": {"topic": "str", "url": "str",
                                             "no-image": "bool",
                                             "force": "bool"}},
    "daily":     {"writes": True,  "flags": {"with-post": "bool",
                                             "no-image": "bool"}},
}

app = FastAPI(title="GBP Autopilot", version="1.0")

# The UI is served by Next on another port in development, so it is a different
# origin. Restricted to localhost: this API holds a live Google login.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------- jobs

class Job:
    def __init__(self, command: str, argv: list[str], location: str = ""):
        self.id = secrets.token_hex(8)
        self.command = command
        self.argv = argv
        self.location = location
        self.lines: list[str] = []
        self.started = time.time()
        self.finished: float | None = None
        self.exit_code: int | None = None
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.finished is None

    def _append(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)
            if len(self.lines) > 5000:
                del self.lines[:1500]

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            return {
                "id": self.id, "command": self.command, "argv": self.argv,
                "location": self.location, "running": self.running,
                "exit_code": self.exit_code,
                "elapsed": round((self.finished or time.time()) - self.started),
                "total": len(self.lines), "lines": self.lines[since:],
            }

    def run(self) -> None:
        env = dict(os.environ)
        # Unbuffered so the UI sees output as it happens, and UTF-8 because a
        # profile in Khobar returns Arabic search terms that cp1252 cannot
        # encode -- which killed a whole run once.
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", "run.py", *self.argv],
                cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", bufsize=1)
        except OSError as exc:
            self._append(f"could not start: {exc}")
            self.exit_code = -1
            self.finished = time.time()
            return
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self._append(line.rstrip("\n"))
        self._proc.wait()
        self.exit_code = self._proc.returncode
        self.finished = time.time()

    def stop(self) -> bool:
        if self._proc and self.running:
            self._proc.terminate()
            return True
        return False


class Jobs:
    def __init__(self):
        self.current: Job | None = None
        self.past: list[Job] = []
        self._lock = threading.Lock()

    def start(self, command: str, argv: list[str], location: str = "") -> Job:
        with self._lock:
            if self.current and self.current.running:
                raise HTTPException(
                    409, f"'{self.current.command}' is still running. Wait for "
                         f"it, or stop it first.")
            job = Job(command, argv, location)
            self.current = job
            self.past.append(job)
            del self.past[:-60]
        threading.Thread(target=job.run, daemon=True).start()
        return job

    def find(self, job_id: str) -> Job | None:
        for job in reversed(self.past):
            if job.id == job_id:
                return job
        return None


JOBS = Jobs()


def build_argv(command: str, options: dict, apply: bool,
               location: str = "") -> list[str]:
    spec = COMMANDS.get(command)
    if spec is None:
        raise HTTPException(400, f"'{command}' is not a command this app runs.")

    argv = [command]
    for key, value in (options or {}).items():
        kind = spec["flags"].get(key)
        if kind is None:
            raise HTTPException(400, f"'{command}' does not take --{key}.")
        if kind == "bool":
            if value:
                argv.append(f"--{key}")
        elif value not in (None, ""):
            text = str(value)
            if kind == "int" and not text.isdigit():
                raise HTTPException(400, f"--{key} must be a number.")
            if any(c in text for c in "\r\n\x00"):
                raise HTTPException(400, f"--{key} contains a control character.")
            argv += [f"--{key}", text]

    if apply:
        if not spec["writes"]:
            raise HTTPException(
                400, f"'{command}' never writes, so Apply does not apply.")
        argv.append("--apply")

    # login and locations act on the account, not one profile.
    if location and command not in ("login", "locations", "doctor", "holidays"):
        argv += ["--location", location]
    return argv


# ------------------------------------------------------------------- plumbing

def guard(request: Request) -> None:
    if not TOKEN:
        return
    given = (request.headers.get("x-token")
             or request.query_params.get("t") or "")
    if not secrets.compare_digest(given, TOKEN):
        raise HTTPException(401, "token required")


def cfg() -> dict:
    try:
        return config.load()
    except SystemExit:
        # A missing config.yaml must not 500 the whole app -- the UI needs to
        # come up and tell the operator what to do about it.
        return {}


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


# ------------------------------------------------------------------ endpoints

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "root": str(ROOT)}


@app.get("/api/status")
def status(request: Request) -> dict:
    """Everything the shell of the app needs: who is connected, what is set up."""
    guard(request)
    db.init()
    c = cfg()
    age = auth.token_age_days()
    llm_cfg = (c.get("llm", {}) or {})
    return {
        "configured": bool(c),
        "google": {
            "signed_in": age is not None,
            "token_age_days": round(age, 1) if age is not None else None,
            # Google expires refresh tokens weekly while the OAuth consent
            # screen is in Testing. Surfacing this before it bites is the
            # difference between a warning and a mystery outage.
            "expiring_soon": bool(age is not None and age > 5),
        },
        "llm": {
            "backend": llm_cfg.get("backend", "claude"),
            "ready": bool(config.env("ANTHROPIC_API_KEY"))
            if llm_cfg.get("backend") == "api" else True,
        },
        "dataforseo": bool(config.env("DATAFORSEO_LOGIN")
                           and config.env("DATAFORSEO_PASSWORD")),
        "images": (c.get("images", {}) or {}).get("backend", "none"),
        "active": profiles.active(),
        "job": JOBS.current.snapshot(10**9) if JOBS.current else None,
    }


# ----------------------------------------------------------------- sign-in
#
# A real OAuth redirect, not a subprocess. The CLI's `login` blocks on a local
# server and -- if a valid token already exists -- returns instantly without
# ever showing a browser, so "sign in as a different account" did nothing. This
# owns the redirect, so switching accounts works and the user gets feedback.

# One-shot CSRF states. A callback carrying a state we did not issue is either
# stale or forged, and is refused.
_STATES: dict[str, float] = {}


def _redirect_uri(request: Request) -> str:
    # Must match what was sent to Google exactly. The client is a Desktop type,
    # for which Google accepts any loopback port, so nothing needs registering.
    return f"http://127.0.0.1:{request.url.port or 8790}/api/auth/callback"


@app.get("/api/auth/start")
def auth_start(request: Request) -> dict:
    guard(request)
    state = secrets.token_urlsafe(24)
    now = time.time()
    # Drop anything older than ten minutes rather than growing forever.
    for old, when in list(_STATES.items()):
        if now - when > 600:
            _STATES.pop(old, None)
    _STATES[state] = now
    try:
        return {"url": auth.auth_url(_redirect_uri(request), state)}
    except AuthError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/auth/callback")
def auth_callback(request: Request, code: str | None = None,
                  state: str | None = None, error: str | None = None):
    """Where Google sends the browser back. Returns a page, not JSON."""
    def page(title: str, body: str, ok: bool) -> HTMLResponse:
        colour = "#4ADE80" if ok else "#F87171"
        return HTMLResponse(
            f"""<!doctype html><meta charset="utf-8">
<title>{title}</title>
<body style="margin:0;background:#0F1115;color:#E8EAEE;font:16px/1.6 system-ui,
sans-serif;display:grid;place-items:center;height:100vh;text-align:center">
<div style="max-width:30rem;padding:2rem">
  <div style="font-size:2rem;color:{colour};margin-bottom:.5rem">
    {"&#10003;" if ok else "&#10007;"}</div>
  <h1 style="font-size:1.25rem;margin:0 0 .5rem">{title}</h1>
  <p style="color:#A2ABB8;margin:0 0 1.5rem">{body}</p>
  <p style="color:#6C7685;font-size:.85rem">You can close this tab.</p>
</div>
<script>setTimeout(function(){{ window.close(); }}, 2500);</script>
</body>""", status_code=200 if ok else 400)

    if error:
        return page("Sign-in cancelled", f"Google said: {error}", False)
    if not code or not state or state not in _STATES:
        return page("Sign-in could not be completed",
                    "That link was already used or has expired. Start again "
                    "from the Connect screen.", False)
    _STATES.pop(state, None)

    try:
        auth.exchange(code, _redirect_uri(request))
    except AuthError as exc:
        return page("Sign-in failed", str(exc).replace("\n", " "), False)
    except Exception as exc:
        return page("Sign-in failed", f"{type(exc).__name__}: {exc}", False)

    # Discover straight away, so the app has businesses to show when the user
    # switches back to it rather than an empty picker.
    found = 0
    try:
        db.init()
        client = Client(auth.credentials(interactive=False))
        for acct in client.accounts():
            for loc in client.locations(
                    acct["name"], read_mask="name,title,storefrontAddress"):
                addr = loc.get("storefrontAddress") or {}
                profiles.upsert(loc["name"], acct["name"], loc.get("title", ""),
                                addr.get("locality", ""))
                found += 1
        if found and not profiles.active():
            profiles.set_active(profiles.all_profiles()[0]["location"])
    except Exception:
        # Signing in worked even if discovery did not. Say so honestly rather
        # than reporting a failed sign-in.
        return page("Signed in", "Could not list your businesses yet — press "
                                 "Find my business profiles on the Connect "
                                 "screen.", True)

    return page("Signed in",
                f"Found {found} business profile{'' if found == 1 else 's'}.", True)


@app.post("/api/auth/signout")
def auth_signout(request: Request) -> dict:
    guard(request)
    return {"signed_out": auth.sign_out()}


@app.get("/api/profiles")
def list_profiles(request: Request) -> dict:
    guard(request)
    db.init()
    out = []
    for p in profiles.all_profiles():
        history = db.audit_history(p["location"], limit=8)
        out.append({
            "location": p["location"], "account": p["account"],
            "title": p["title"], "city": p["city"],
            "settings": p["settings"],
            "score": history[0]["score"] if history else None,
            "grade": history[0]["grade"] if history else None,
            "last_audit": iso(history[0]["created_at"]) if history else None,
            "history": [{"score": r["score"], "when": iso(r["created_at"])}
                        for r in reversed(history)],
            "alerts": len(db.open_alerts(p["location"])),
        })
    return {"profiles": out, "active": profiles.active()}


@app.post("/api/profiles/discover")
def discover(request: Request) -> dict:
    """Ask Google what this account manages, and remember all of it.

    This is what "connect a business" actually means: sign in once, then every
    profile the account manages shows up in the picker.
    """
    guard(request)
    db.init()
    try:
        client = Client(auth.credentials(interactive=False))
        found = []
        for acct in client.accounts():
            for loc in client.locations(
                    acct["name"],
                    read_mask="name,title,storefrontAddress,metadata"):
                addr = loc.get("storefrontAddress") or {}
                profiles.upsert(loc["name"], acct["name"],
                                loc.get("title", ""), addr.get("locality", ""))
                found.append({"location": loc["name"],
                              "title": loc.get("title", ""),
                              "city": addr.get("locality", "")})
    except AuthError as exc:
        raise HTTPException(401, str(exc))
    except ApiError as exc:
        raise HTTPException(502, str(exc))

    if found and not profiles.active():
        profiles.set_active(found[0]["location"])
    return {"found": found, "active": profiles.active()}


class Select(BaseModel):
    location: str


@app.post("/api/profiles/select")
def select(body: Select, request: Request) -> dict:
    guard(request)
    if not profiles.get(body.location):
        raise HTTPException(404, "that profile is not connected")
    profiles.set_active(body.location)
    return {"active": profiles.active()}


@app.delete("/api/profiles/{location:path}")
def forget(location: str, request: Request) -> dict:
    guard(request)
    return {"removed": profiles.forget(location)}


class Settings(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


@app.put("/api/profiles/{location:path}/settings")
def put_settings(location: str, body: Settings, request: Request) -> dict:
    guard(request)
    if not profiles.get(location):
        raise HTTPException(404, "that profile is not connected")
    profiles.save_settings(location, body.settings)
    return {"settings": (profiles.get(location) or {}).get("settings", {})}


@app.get("/api/audit/{location:path}")
def latest_audit(location: str, request: Request) -> dict:
    """The most recent stored audit, with every finding. Painted instantly --
    no API calls, so opening the app is fast."""
    guard(request)
    db.init()
    with db.conn() as cx:
        row = cx.execute(
            "SELECT * FROM audits WHERE location=? ORDER BY created_at DESC "
            "LIMIT 1", (location,)).fetchone()
    if not row:
        return {"audit": None}
    try:
        findings = json.loads(row["findings"])
    except json.JSONDecodeError:
        findings = []
    # Rows written before findings were stored in full carry only a summary.
    # Fill the gaps so the UI renders them rather than showing blanks.
    for f in findings:
        f.setdefault("rule_id", f.get("id", ""))
        for key, default in (("category", ""), ("why", ""), ("fix", ""),
                             ("fixable", False), ("informational", False),
                             ("command", None), ("severity", "low"),
                             ("detail", ""), ("title", f.get("rule_id", ""))):
            f.setdefault(key, default)
    return {"audit": {
        "score": row["score"], "grade": row["grade"], "title": row["title"],
        "when": iso(row["created_at"]), "findings": findings,
        "previous": db.previous_score(location),
    }}


@app.get("/api/activity/{location:path}")
def activity(location: str, request: Request, limit: int = 40) -> dict:
    guard(request)
    db.init()
    return {"actions": [
        {"kind": r["kind"], "target": r["target"], "detail": r["detail"],
         "dry_run": bool(r["dry_run"]), "when": iso(r["created_at"])}
        for r in db.recent_actions(location, limit=limit)]}


@app.get("/api/alerts/{location:path}")
def alerts(location: str, request: Request) -> dict:
    guard(request)
    db.init()
    return {"alerts": [
        {"severity": r["severity"], "message": r["message"],
         "when": iso(r["created_at"])} for r in db.open_alerts(location)]}


@app.post("/api/alerts/{location:path}/ack")
def ack(location: str, request: Request) -> dict:
    guard(request)
    return {"acknowledged": db.acknowledge_alerts(location)}


@app.get("/api/reports")
def reports(request: Request) -> dict:
    guard(request)
    if not config.REPORT_DIR.exists():
        return {"reports": []}
    files = sorted(config.REPORT_DIR.glob("*.html"),
                   key=lambda p: p.stat().st_mtime, reverse=True)[:40]
    return {"reports": [{"name": f.name, "when": iso(f.stat().st_mtime),
                         "size": f.stat().st_size} for f in files]}


@app.get("/api/reports/{name}")
def report_file(name: str, request: Request):
    guard(request)
    # Reports carry a client's name and findings. Confirm the resolved path is
    # really inside the reports folder before opening it, so a crafted name
    # cannot walk out to token.json.
    try:
        target = (config.REPORT_DIR / name).resolve()
        target.relative_to(config.REPORT_DIR.resolve())
    except (ValueError, OSError):
        raise HTTPException(403, "outside the reports folder")
    if not target.is_file():
        raise HTTPException(404, "no such report")
    return FileResponse(target, media_type="text/html")


class RunBody(BaseModel):
    command: str
    options: dict[str, Any] = Field(default_factory=dict)
    apply: bool = False
    location: str | None = None


@app.post("/api/run")
def run_command(body: RunBody, request: Request) -> dict:
    guard(request)
    db.init()
    location = body.location or profiles.active()
    argv = build_argv(body.command, body.options, body.apply, location)
    job = JOBS.start(body.command, argv, location)
    return job.snapshot()


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str, request: Request, since: int = 0) -> dict:
    guard(request)
    job = JOBS.find(job_id)
    if job is None:
        raise HTTPException(404, "no such job")
    return job.snapshot(since)


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request,
                     t: str | None = Query(default=None)):
    """Server-sent events, so the UI shows output as it happens rather than
    polling and stuttering."""
    guard(request)
    job = JOBS.find(job_id)
    if job is None:
        raise HTTPException(404, "no such job")

    async def events():
        sent = 0
        while True:
            if await request.is_disconnected():
                return
            snap = job.snapshot(sent)
            sent = snap["total"]
            if snap["lines"] or not snap["running"]:
                yield f"data: {json.dumps(snap)}\n\n"
            if not snap["running"]:
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/jobs/stop")
def stop_job(request: Request) -> dict:
    guard(request)
    job = JOBS.current
    return {"stopped": job.stop() if job else False}


@app.get("/api/commands")
def commands(request: Request) -> dict:
    guard(request)
    return {"commands": {k: {"writes": v["writes"], "flags": v["flags"]}
                         for k, v in COMMANDS.items()}}
