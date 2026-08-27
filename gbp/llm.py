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

def _via_cli(prompt: str, system: str, model: str, timeout: int) -> str:
    exe = shutil.which("claude")
    if not exe:
        raise LLMError(
            "The `claude` CLI is not on your PATH.\n"
            "  Either install Claude Code and sign in, or set\n"
            "  llm.backend: api  in config.yaml and put ANTHROPIC_API_KEY in .env"
        )
    cmd = [exe, "-p", prompt, "--model", model]
    if system:
        cmd += ["--append-system-prompt", system]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise LLMError(f"The Claude CLI did not answer within {timeout}s.") from exc
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[:400]
        if "not logged in" in err.lower() or "authentication" in err.lower():
            raise LLMError("The Claude CLI is not signed in. Run `claude` once "
                           "in a terminal and log in, then try again.")
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
    timeout = int(cfg.get("timeout_seconds", 120))

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
