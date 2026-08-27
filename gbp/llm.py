"""Text generation, through whichever backend is available.

Two backends, and the default costs nothing extra:

    claude   the Claude CLI you are already signed into. Runs on your existing
             subscription, so there is no API key and no per-review bill.
    api      the Anthropic API with a key, for servers with no CLI login.

Everything written here ends up on a public Google profile under a real
business's name, so `clean()` is not optional decoration -- it strips the
markdown, the em-dashes and the AI throat-clearing that make a reply obviously
machine-written.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

from . import config

# Phrases that mark a reply as machine-written to anyone who reads a lot of
# them. A business owner would never type these.
BANNED = [
    "we appreciate you taking the time", "thank you for taking the time",
    "we strive to", "we are thrilled", "we're thrilled", "delighted to hear",
    "valued customer", "your feedback is important", "we take all feedback",
    "at the end of the day", "rest assured", "we sincerely apologize",
    "it is our pleasure", "we look forward to serving you again",
    "please do not hesitate", "we pride ourselves",
]


class LLMError(RuntimeError):
    pass


def clean(text: str) -> str:
    """Strip the tells. Runs on every generated string before it is sent."""
    t = (text or "").strip()
    # Models like to wrap a reply in quotes or a code fence.
    t = re.sub(r"^```[a-z]*\n?|```$", "", t).strip()
    if len(t) > 1 and t[0] in "\"'“" and t[-1] in "\"'”":
        t = t[1:-1].strip()
    # Markdown has no meaning on a Google profile; it renders as literal stars.
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t)
    t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", t)
    t = re.sub(r"^#+\s*", "", t, flags=re.M)
    # Em and en dashes read as AI punctuation in a short business reply.
    t = t.replace("—", ", ").replace("–", "-")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("‘", "'").replace("’", "'")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def banned_hits(text: str) -> list[str]:
    low = (text or "").lower()
    return [p for p in BANNED if p in low]


# ------------------------------------------------------------------- backends

# Used when a caller passes no system prompt of its own. Something has to
# replace Claude Code's agent prompt, or the persona comes back.
_PLAIN_SYSTEM = (
    "You are a text generator. Return only the text that was asked for, with "
    "no preamble, no explanation, no offer of further help, and no questions "
    "back. You have no tools and no task beyond writing the text."
)

# Environment variables that tell a `claude` process it is a child of a
# running Claude Code session. Inheriting them makes the subprocess JOIN that
# session -- it answers the outer conversation instead of the prompt we sent.
_SESSION_ENV = re.compile(r"^(CLAUDE|CLAUDECODE|AI_AGENT|BAGGAGE)", re.I)


def _isolated_env() -> dict[str, str]:
    """A copy of the environment with the session handles taken out.

    This matters when gbp-autopilot is itself run from inside a Claude Code
    session -- which is the normal way it gets run here. The parent exports
    CLAUDE_CODE_SESSION_ID, CLAUDE_CODE_CHILD_SESSION and a messaging socket,
    and a nested `claude -p` picks them up and continues the PARENT's
    conversation. The prompt we pass is then ignored.

    The failure is not a crash and does not look like a bug. On the first live
    run the services planner was handed back the assistant's own reply to the
    operator -- a repo status report, in markdown, discussing this very tool --
    and the parser dutifully split it on colons and proposed "Where it stands
    (`data/gbp.db`, latest r" as a service to publish on a client's public
    profile. Rejecting bad output downstream is not enough; the subprocess has
    to be a clean text completion in the first place.
    """
    env = {k: v for k, v in os.environ.items() if not _SESSION_ENV.match(k)}
    # Keep the login. The credentials live in ~/.claude, found via HOME, so
    # nothing above removes them -- but be explicit that this is deliberate.
    return env


def _via_cli(prompt: str, system: str, model: str, timeout: int) -> str:
    exe = shutil.which("claude")
    if not exe:
        raise LLMError(
            "The `claude` CLI is not on your PATH.\n"
            "  Either install Claude Code and sign in, or set\n"
            "  llm.backend: api  in config.yaml and put ANTHROPIC_API_KEY in .env"
        )
    # Each of these turns a coding agent back into a text completion.
    #
    # --tools ""              it can otherwise read the working directory and
    #                         act on what it finds.
    # --strict-mcp-config     with no --mcp-config alongside it, this loads no
    #                         MCP servers at all. The operator's connectors
    #                         have no business in a client's review reply, and
    #                         not starting them makes every call faster.
    # --no-session-persistence  stops every draft leaving a saved session
    #                         behind in the operator's history.
    #
    # THE PROMPT GOES ON STDIN, NOT IN ARGV. Not a style preference: a
    # multi-line prompt passed as a command-line argument arrives truncated on
    # Windows, and the CLI sees only the first line. Every call in this module
    # was silently running on a one-line prompt, which looked like the model
    # misbehaving rather than the prompt never arriving -- a full services
    # brief came back as "Got it, Nour Solutions. What would you like me to do
    # for it?". Proven by sending the identical prompt both ways: argv gives
    # that, stdin gives the answer asked for.
    cmd = [exe, "-p", "--model", model, "--tools", "",
           "--strict-mcp-config", "--no-session-persistence"]

    # The SYSTEM prompt goes in a file for the same reason the user prompt goes
    # on stdin: every system prompt in this module is multi-line, and argv
    # truncates at the first line. With only line one of SERVICES_SYSTEM --
    # "You name services for a Google Business Profile." -- the model returned
    # a bare service name and none of the format, grounding or length rules
    # that follow it. The output looked merely disappointing rather than
    # broken, which is the dangerous kind of wrong.
    #
    # --system-prompt REPLACES, where --append-system-prompt only adds to
    # Claude Code's own agent prompt and leaves the persona, the skills and the
    # CLAUDE.md in charge. Appending got back "What would you like me to do for
    # it? I can build a site..." -- the agent answering the operator, with the
    # real instructions ignored underneath.
    handle, sys_path = tempfile.mkstemp(suffix=".txt", prefix="gbp-system-",
                                        text=True)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(system or _PLAIN_SYSTEM)
        cmd += ["--system-prompt-file", sys_path]
        try:
            # cwd is deliberately NOT the project directory. The CLI reads a
            # CLAUDE.md from wherever it starts, and instructions written for
            # working ON this repo have no business steering a review reply
            # written FOR a client.
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=timeout,
                env=_isolated_env(), cwd=tempfile.gettempdir())
        except subprocess.TimeoutExpired as exc:
            raise LLMError(
                f"The Claude CLI did not answer within {timeout}s.\n"
                f"  The services planner sends a large prompt -- the search "
                f"terms plus the\n  website copy -- and can take a few "
                f"minutes. Raise llm.timeout_seconds\n  in config.yaml. 300 "
                f"is a reasonable default.") from exc
    finally:
        try:
            os.unlink(sys_path)
        except OSError:
            pass

    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[:400]
        if "not logged in" in err.lower() or "authentication" in err.lower():
            raise LLMError("The Claude CLI is not signed in. Run `claude` once "
                           "in a terminal and log in, then try again.")
        if "unknown option" in err.lower() and "system-prompt-file" in err:
            raise LLMError(
                "This Claude CLI does not support --system-prompt-file.\n"
                "  Update Claude Code (`claude update`), or set\n"
                "  llm.backend: api  in config.yaml and put ANTHROPIC_API_KEY "
                "in .env")
        raise LLMError(f"The Claude CLI failed: {err}")
    return proc.stdout.strip()


def _via_api(prompt: str, system: str, model: str, timeout: int) -> str:
    import requests

    key = config.env("ANTHROPIC_API_KEY", required=True)
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": 1000, "system": system,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=timeout,
    )
    if resp.status_code >= 300:
        raise LLMError(f"Anthropic API returned {resp.status_code}: "
                       f"{resp.text[:300]}")
    data = resp.json()
    parts = [b.get("text", "") for b in data.get("content", [])
             if b.get("type") == "text"]
    return "".join(parts).strip()


def generate(prompt: str, *, system: str = "", cfg: dict | None = None,
             model: str | None = None, retries: int = 2) -> str:
    """Generate, clean, and reject anything carrying a banned phrase.

    A rejected draft is regenerated rather than patched, because a reply built
    around 'we appreciate you taking the time' does not improve by deleting the
    phrase. After the last attempt the best effort is returned anyway -- a
    slightly stiff reply beats no reply at all, and the caller can still
    decide.
    """
    cfg = cfg or {}
    backend = cfg.get("backend", "claude")
    model = model or cfg.get("model", "sonnet" if backend == "claude"
                             else "claude-sonnet-5")
    timeout = int(cfg.get("timeout_seconds", 300))

    last = ""
    for attempt in range(retries + 1):
        raw = (_via_cli if backend == "claude" else _via_api)(
            prompt, system, model, timeout)
        text = clean(raw)
        last = text
        hits = banned_hits(text)
        if not hits:
            return text
        if attempt < retries:
            prompt = (f"{prompt}\n\nYour previous attempt used these phrases, "
                      f"which are banned: {', '.join(hits)}. "
                      f"Write it again without them, and without reaching for a "
                      f"synonym of the same idea.")
    return last
