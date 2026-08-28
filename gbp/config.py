"""Config loading, paths, and environment.

One YAML file drives the whole agent. Secrets never go in it -- they live in
.env, which is gitignored. The split is deliberate: config.yaml is safe to
commit and safe to send to a client, .env is not.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
DB_PATH = DATA_DIR / "gbp.db"

# OAuth artefacts. Both are secrets; both are gitignored.
CLIENT_SECRET_PATH = DATA_DIR / "client_secret.json"
TOKEN_PATH = DATA_DIR / "token.json"
# Planned changes, one file per location, so the app can show what a dry run
# would actually write instead of only printing it.
PLAN_DIR = DATA_DIR / "plans"

load_dotenv(ROOT / ".env")


class Config(dict):
    """Dict with dotted access, so cfg.get_path('audit.min_photos') works."""

    def get_path(self, dotted: str, default=None):
        node = self
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def load(path: str | Path | None = None) -> Config:
    path = Path(path) if path else ROOT / "config.yaml"
    if not path.exists():
        example = ROOT / "config.example.yaml"
        raise SystemExit(
            f"config not found: {path}\n"
            f"  Copy the example first:\n"
            f"    copy {example.name} {path.name}      (Windows)\n"
            f"    cp   {example.name} {path.name}      (macOS/Linux)"
        )
    with open(path, "r", encoding="utf-8") as fh:
        return Config(yaml.safe_load(fh) or {})


def env(key: str, required: bool = False, default: str | None = None) -> str | None:
    val = os.environ.get(key, default)
    if required and not val:
        raise SystemExit(
            f"{key} is not set.\n"
            f"  Copy .env.example to .env and fill it in. See the README."
        )
    return val


def ensure_dirs() -> None:
    for d in (DATA_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)
