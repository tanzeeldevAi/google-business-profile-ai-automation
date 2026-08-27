"""A small DataForSEO client, used by the competitor and citation checks.

Everything else in this tool runs on Google's own API and costs nothing. This
one module talks to a paid third party, so it is deliberately separate and
deliberately optional: without credentials the features that need it report
"not checked", exactly the way the legacy v4 API does.

Cost. Every call here is a live request billed per use. The numbers are small
(fractions of a cent) but they are real, so:

  * every function says how many requests it will make before making them
  * `compare` caps itself at 5 keywords
  * results are cached to data/dataforseo/ so re-running an audit on the same
    day does not pay twice

Set credentials in .env:

    DATAFORSEO_LOGIN=...
    DATAFORSEO_PASSWORD=...
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

from . import config

BASE = "https://api.dataforseo.com/v3"


class NotConfigured(RuntimeError):
    """No credentials. The caller should degrade, not crash."""


class DataForSeoError(RuntimeError):
    pass


def available() -> bool:
    return bool(config.env("DATAFORSEO_LOGIN")
                and config.env("DATAFORSEO_PASSWORD"))


def _auth() -> tuple[str, str]:
    login = config.env("DATAFORSEO_LOGIN")
    password = config.env("DATAFORSEO_PASSWORD")
    if not (login and password):
        raise NotConfigured(
            "DataForSEO credentials are not set.\n\n"
            "  This check needs a DataForSEO account -- it reads the live map "
            "pack,\n  which Google's own API cannot tell you about.\n\n"
            "  Put these in .env:\n"
            "    DATAFORSEO_LOGIN=your-login\n"
            "    DATAFORSEO_PASSWORD=your-password\n\n"
            "  Everything else in this tool works without it.")
    return login, password


def _cache_path(endpoint: str, payload: list[dict]) -> Path:
    key = hashlib.sha256(
        (endpoint + json.dumps(payload, sort_keys=True)).encode()).hexdigest()[:20]
    d = config.DATA_DIR / "dataforseo"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def post(endpoint: str, payload: list[dict], *, cache_hours: float = 24,
         timeout: int = 120, verbose: bool = True) -> list[dict]:
    """POST to a live endpoint and return the `result` list of the first task.

    DataForSEO wraps everything twice -- tasks[] then result[] -- and reports
    per-task failures inside a 200 response, so the status code alone tells you
    nothing.
    """
    login, password = _auth()
    path = _cache_path(endpoint, payload)

    if path.exists() and cache_hours > 0:
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h < cache_hours:
            if verbose:
                print(f"  [dfs] cached ({age_h:.0f}h old) {endpoint}")
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    if verbose:
        print(f"  [dfs] POST {endpoint}  ({len(payload)} task(s), billed)")

    try:
        resp = requests.post(f"{BASE}/{endpoint.lstrip('/')}",
                             auth=(login, password), json=payload,
                             timeout=timeout)
    except requests.RequestException as exc:
        raise DataForSeoError(f"Could not reach DataForSEO: {exc}") from exc

    if resp.status_code == 401:
        raise DataForSeoError("DataForSEO rejected the login. Check "
                              "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD.")
    if resp.status_code >= 300:
        raise DataForSeoError(f"DataForSEO returned {resp.status_code}: "
                              f"{resp.text[:300]}")

    body = resp.json()
    if body.get("status_code") not in (20000, None):
        raise DataForSeoError(f"DataForSEO: {body.get('status_message')}")

    tasks = body.get("tasks") or []
    if not tasks:
        return []

    out: list[dict] = []
    for task in tasks:
        # 20000 is success. Anything else is a per-task failure inside a 200.
        if task.get("status_code") != 20000:
            message = task.get("status_message", "unknown error")
            if verbose:
                print(f"  [dfs] task failed: {message}")
            continue
        out.extend(task.get("result") or [])

    try:
        path.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


def maps_search(keyword: str, *, latitude: float | None = None,
                longitude: float | None = None, location_name: str = "",
                language_code: str = "en", depth: int = 10,
                verbose: bool = True) -> list[dict]:
    """One Google Maps search, as a searcher standing at that point would see it.

    Coordinates beat a location name for map-pack work: the pack is distance-
    weighted, so "Durham" as a name gives you the city centroid rather than
    where the business actually is.
    """
    task: dict[str, Any] = {
        "keyword": keyword,
        "language_code": language_code,
        "depth": depth,
    }
    if latitude is not None and longitude is not None:
        # lat,lng,zoom -- zoom 14 is roughly a town-sized view.
        task["location_coordinate"] = f"{latitude},{longitude},14"
    elif location_name:
        task["location_name"] = location_name
    else:
        raise DataForSeoError("A maps search needs coordinates or a location "
                              "name.")

    results = post("serp/google/maps/live/advanced", [task], verbose=verbose)
    items: list[dict] = []
    for block in results:
        items.extend(block.get("items") or [])
    return items


def organic_search(query: str, *, location_name: str = "",
                   language_code: str = "en", depth: int = 30,
                   verbose: bool = True) -> list[dict]:
    """A plain Google search, used to find where a business is already listed."""
    task: dict[str, Any] = {
        "keyword": query,
        "language_code": language_code,
        "depth": depth,
    }
    if location_name:
        task["location_name"] = location_name

    results = post("serp/google/organic/live/advanced", [task], verbose=verbose)
    items: list[dict] = []
    for block in results:
        items.extend(block.get("items") or [])
    return items
