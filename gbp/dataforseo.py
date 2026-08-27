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


# Per-task codes that mean "try again", not "you asked for the wrong thing".
# 40101 is DataForSEO's own upstream hiccup: the identical query can fail and
# then succeed seconds later. Seen on the first live citation run.
TRANSIENT_TASK_CODES = {40101, 40102, 40103, 50000, 50100, 50200, 50300}


def post(endpoint: str, payload: list[dict], *, cache_hours: float = 24,
         timeout: int = 120, verbose: bool = True,
         retries: int = 3) -> list[dict]:
    """POST to a live endpoint and return the `result` list of the first task.

    DataForSEO wraps everything twice -- tasks[] then result[] -- and reports
    per-task failures inside a 200 response, so the HTTP status alone tells you
    nothing. A task rejected for a bad request raises; a task that failed
    upstream is retried.
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

    out: list[dict] = []
    failures: list[str] = []

    for attempt in range(retries):
        if verbose:
            again = f", retry {attempt}" if attempt else ""
            print(f"  [dfs] POST {endpoint}  ({len(payload)} task(s), "
                  f"billed{again})")

        try:
            resp = requests.post(f"{BASE}/{endpoint.lstrip('/')}",
                                 auth=(login, password), json=payload,
                                 timeout=timeout)
        except requests.RequestException as exc:
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
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

        out, failures, transient = [], [], False
        for task in body.get("tasks") or []:
            code = task.get("status_code")
            if code != 20000:
                failures.append(f"{code}: "
                                f"{task.get('status_message', 'unknown error')}")
                transient = transient or code in TRANSIENT_TASK_CODES
                continue
            out.extend(task.get("result") or [])

        if out or not transient:
            break
        if attempt + 1 < retries:
            if verbose:
                print(f"  [dfs] {failures[0]} -- retrying")
            time.sleep(2 ** attempt)

    # If EVERY task was rejected, that is an error, not an empty result. This
    # matters: a rejected request used to come back as "no listings found",
    # which reads as a real answer on a client report. Silence and failure must
    # never look the same.
    if failures and not out:
        raise DataForSeoError(
            "DataForSEO rejected the request:\n  " + "\n  ".join(failures))
    if failures and verbose:
        print(f"  [dfs] {len(failures)} task(s) failed: {failures[0]}")

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


# DataForSEO wants a location NAME for organic search, and its own spelling of
# it. Enough of the common ones to cover where this tool gets used; anything
# else needs competitors.location_name set in config.
COUNTRY_BY_REGION = {
    "GB": "United Kingdom", "US": "United States", "CA": "Canada",
    "AU": "Australia", "NZ": "New Zealand", "IE": "Ireland",
    "AE": "United Arab Emirates", "SA": "Saudi Arabia", "QA": "Qatar",
    "KW": "Kuwait", "BH": "Bahrain", "OM": "Oman", "PK": "Pakistan",
    "IN": "India", "ZA": "South Africa", "SG": "Singapore",
    "MY": "Malaysia", "DE": "Germany", "FR": "France", "ES": "Spain",
    "IT": "Italy", "NL": "Netherlands", "SE": "Sweden", "PL": "Poland",
}


def location_for(region_code: str) -> str:
    return COUNTRY_BY_REGION.get((region_code or "").upper(), "")


def organic_search(query: str, *, location_name: str = "",
                   language_code: str = "en", depth: int = 30,
                   verbose: bool = True) -> list[dict]:
    """A plain Google search, used to find where a business is already listed.

    Unlike the maps endpoint, this one REQUIRES a location and rejects the task
    without one. That rejection used to surface as an empty result, which read
    as "this business has no directory listings" on a client report.
    """
    if not location_name:
        raise DataForSeoError(
            "A Google search needs a location, and none could be worked out "
            "from the profile.\n  Set competitors.location_name in "
            "config.yaml -- for example \"United Kingdom\".")

    task: dict[str, Any] = {
        "keyword": query,
        "language_code": language_code,
        "depth": depth,
        "location_name": location_name,
    }

    results = post("serp/google/organic/live/advanced", [task], verbose=verbose)
    items: list[dict] = []
    for block in results:
        items.extend(block.get("items") or [])
    return items
