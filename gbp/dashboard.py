"""A local web dashboard for the whole tool.

    python run.py dashboard        ->  http://127.0.0.1:8770

Every button runs the SAME command you would type. The dashboard shells out to
`run.py`, streams its output back, and shows it. It does not reimplement any of
the logic, which means the CLI and the dashboard can never disagree about what
a command does -- a class of bug that is otherwise guaranteed.

Three rules it enforces, because this thing writes to real client profiles:

  1. **Dry run is the default.** Publishing needs the Apply switch turned on
     deliberately, and the switch resets after every run.
  2. **One job at a time.** Two commands writing to the same profile at once
     is how you get half-applied changes. A second request is refused while a
     job is running rather than queued silently.
  3. **Localhost only.** Bound to 127.0.0.1 with no auth. If you bind it
     anywhere else it demands a token first, because this holds a live Google
     login for somebody else's business.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import config, db

STATIC = Path(__file__).resolve().parent / "static"

# The only commands the dashboard may run, and the only flags each may carry.
# A whitelist, not a filter: the browser never gets to assemble an argv.
#
# "writes" marks the ones that can change a live profile. Those are the only
# ones the Apply switch applies to, and the UI colours them differently.
COMMANDS: dict[str, dict] = {
    "doctor":    {"writes": False, "flags": {}},
    "audit":     {"writes": False, "flags": {"no-report": "bool"}},
    "site":      {"writes": False, "flags": {"refresh": "bool", "url": "str"}},
    "keywords":  {"writes": False, "flags": {"csv": "bool", "limit": "int"}},
    "compare":   {"writes": False, "flags": {"keywords": "str"}},
    "citations": {"writes": False, "flags": {}},
    "watch":     {"writes": False, "flags": {}},
    "history":   {"writes": False, "flags": {}},
    "alerts":    {"writes": False, "flags": {"ack": "bool"}},
    "holidays":  {"writes": False, "flags": {"region": "str", "days": "int"}},
    "fix":       {"writes": True,  "flags": {"only": "str"}},
    "reviews":   {"writes": True,  "flags": {"include-held": "bool"}},
    "post":      {"writes": True,  "flags": {"topic": "str", "url": "str",
                                             "no-image": "bool",
                                             "force": "bool"}},
    "daily":     {"writes": True,  "flags": {"with-post": "bool",
                                             "no-image": "bool"}},
}


class Job:
    """One running command, with its output as it arrives."""

    def __init__(self, command: str, argv: list[str]):
        self.id = secrets.token_hex(8)
        self.command = command
        self.argv = argv
        self.lines: list[str] = []
        self.started = time.time()
        self.finished: float | None = None
        self.exit_code: int | None = None
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.finished is None

    def append(self, line: str) -> None:
        with self._lock:
            self.lines.append(line)
            # A runaway command must not eat the machine's memory.
            if len(self.lines) > 4000:
                del self.lines[:1000]

    def snapshot(self, since: int = 0) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "command": self.command,
                "running": self.running,
                "exit_code": self.exit_code,
                "elapsed": round((self.finished or time.time()) - self.started),
                "total": len(self.lines),
                "lines": self.lines[since:],
            }

    def run(self) -> None:
        env = dict(os.environ)
        # Python buffers when stdout is a pipe, and a dashboard that shows
        # nothing for two minutes looks broken. Also force UTF-8: the report
        # and the search terms contain characters cp1252 cannot encode, and
        # the CLI would die on its own output.
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-u", "run.py", *self.argv],
                cwd=str(config.ROOT), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as exc:
            self.append(f"could not start: {exc}")
            self.exit_code = -1
            self.finished = time.time()
            return

        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self.append(line.rstrip("\n"))
        self._proc.wait()
        self.exit_code = self._proc.returncode
        self.finished = time.time()

    def stop(self) -> bool:
        if self._proc and self.running:
            self._proc.terminate()
            return True
        return False


class State:
    """One job at a time, and the history of what has run."""

    def __init__(self):
        self.current: Job | None = None
        self.past: list[Job] = []
        self._lock = threading.Lock()

    def start(self, command: str, argv: list[str]) -> tuple[Job | None, str]:
        with self._lock:
            if self.current and self.current.running:
                return None, (f"'{self.current.command}' is still running. "
                              f"Wait for it, or stop it first.")
            job = Job(command, argv)
            self.current = job
            self.past.append(job)
            del self.past[:-40]
        threading.Thread(target=job.run, daemon=True).start()
        return job, ""

    def find(self, job_id: str) -> Job | None:
        for job in reversed(self.past):
            if job.id == job_id:
                return job
        return None


STATE = State()


def build_argv(command: str, options: dict, apply: bool) -> tuple[list[str], str]:
    """Turn a request into an argv, or explain why it is not allowed."""
    spec = COMMANDS.get(command)
    if spec is None:
        return [], f"'{command}' is not a command this dashboard can run."

    argv = [command]
    for key, value in (options or {}).items():
        kind = spec["flags"].get(key)
        if kind is None:
            return [], f"'{command}' does not take --{key}."
        if kind == "bool":
            if value:
                argv.append(f"--{key}")
        elif value not in (None, ""):
            text = str(value)
            if kind == "int" and not text.isdigit():
                return [], f"--{key} must be a number."
            # No shell is involved (Popen with a list), but a newline or a NUL
            # in an argument is never legitimate here.
            if re.search(r"[\r\n\x00]", text):
                return [], f"--{key} contains something it should not."
            argv += [f"--{key}", text]

    if apply:
        if not spec["writes"]:
            return [], f"'{command}' never writes anything, so Apply does not apply."
        argv.append("--apply")
    return argv, ""


def _latest_report() -> dict | None:
    if not config.REPORT_DIR.exists():
        return None
    files = sorted(config.REPORT_DIR.glob("*.html"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    newest = files[0]
    return {"name": newest.name,
            "when": datetime.fromtimestamp(newest.stat().st_mtime,
                                           timezone.utc).isoformat()}


def bootstrap(cfg: dict) -> dict:
    """Everything the page needs on load."""
    location = (cfg.get("location", {}) or {}).get("name", "")
    business = cfg.get("business", {}) or {}

    history: list[dict] = []
    alerts: list[dict] = []
    if location:
        try:
            history = [
                {"score": r["score"], "grade": r["grade"],
                 "when": datetime.fromtimestamp(
                     r["created_at"], timezone.utc).isoformat()}
                for r in db.audit_history(location, limit=12)]
            alerts = [{"severity": r["severity"], "message": r["message"],
                       "when": datetime.fromtimestamp(
                           r["created_at"], timezone.utc).isoformat()}
                      for r in db.open_alerts(location)]
        except Exception:
            # A missing or half-built database must not stop the page loading.
            pass

    return {
        "business": business.get("name") or "(not set in config.yaml)",
        "city": business.get("city", ""),
        "location": location,
        "commands": {k: v["writes"] for k, v in COMMANDS.items()},
        "history": history,
        "alerts": alerts,
        "report": _latest_report(),
        "dataforseo": bool(config.env("DATAFORSEO_LOGIN")
                           and config.env("DATAFORSEO_PASSWORD")),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "gbp-autopilot"
    cfg: dict = {}
    token: str = ""

    # -------------------------------------------------------------- plumbing

    def log_message(self, fmt, *args):
        pass  # the job output is the interesting log, not every GET

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # This page runs commands against a live Google account. Nothing about
        # it should ever be embedded, cached or sent anywhere else.
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorised(self) -> bool:
        if not self.token:
            return True
        given = (self.headers.get("X-Token")
                 or parse_qs(urlparse(self.path).query).get("t", [""])[0])
        return secrets.compare_digest(given, self.token)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > 100_000:
                return {}
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    # ------------------------------------------------------------------ GET

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)

        if url.path in ("/", "/index.html"):
            page = STATIC / "dashboard.html"
            if not page.exists():
                return self._send(500, b"dashboard.html is missing", "text/plain")
            return self._send(200, page.read_bytes(),
                              "text/html; charset=utf-8")

        if not self._authorised():
            return self._json(401, {"error": "token required"})

        if url.path == "/api/bootstrap":
            return self._json(200, bootstrap(self.cfg))

        if url.path == "/api/job":
            job = STATE.find(query.get("id", [""])[0])
            if job is None:
                return self._json(404, {"error": "no such job"})
            since = int(query.get("since", ["0"])[0] or 0)
            return self._json(200, job.snapshot(since))

        if url.path.startswith("/reports/"):
            return self._serve_report(url.path[len("/reports/"):])

        return self._json(404, {"error": "not found"})

    def _serve_report(self, name: str) -> None:
        # Reports carry a client's name and findings. Resolve and confirm the
        # path really is inside the reports directory before opening it, so a
        # crafted name cannot walk out to token.json.
        try:
            target = (config.REPORT_DIR / name).resolve()
            target.relative_to(config.REPORT_DIR.resolve())
        except (ValueError, OSError):
            return self._json(403, {"error": "outside the reports folder"})
        if not target.is_file():
            return self._json(404, {"error": "no such report"})
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), ctype)

    # ----------------------------------------------------------------- POST

    def do_POST(self):
        if not self._authorised():
            return self._json(401, {"error": "token required"})
        url = urlparse(self.path)

        if url.path == "/api/run":
            payload = self._body()
            command = str(payload.get("command", ""))
            argv, problem = build_argv(command, payload.get("options") or {},
                                       bool(payload.get("apply")))
            if problem:
                return self._json(400, {"error": problem})
            job, busy = STATE.start(command, argv)
            if job is None:
                return self._json(409, {"error": busy})
            return self._json(200, {"id": job.id, "argv": argv})

        if url.path == "/api/stop":
            job = STATE.current
            stopped = job.stop() if job else False
            return self._json(200, {"stopped": stopped})

        return self._json(404, {"error": "not found"})


def serve(cfg: dict, host: str = "127.0.0.1", port: int = 8770,
          token: str = "") -> None:
    Handler.cfg = cfg
    Handler.token = token

    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise SystemExit(
            "Refusing to serve on a public interface with no token.\n\n"
            "  This dashboard runs commands against a live Google Business\n"
            "  Profile and can publish to it. Anyone who reaches it can too.\n\n"
            "  Either leave it on 127.0.0.1, or pass --token <something long>.")

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}" + (f"/?t={token}" if token else "")
    print(f"\n  Dashboard: {url}\n")
    print("  Everything is a DRY RUN until you turn on Apply.")
    print("  Ctrl+C to stop.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
    finally:
        httpd.server_close()
