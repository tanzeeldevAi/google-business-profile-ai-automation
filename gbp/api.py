"""A thin client over the Google Business Profile APIs.

Google split this product across several hosts and never finished the job, so
knowing which host serves what is most of the battle:

    accounts                -> mybusinessaccountmanagement  (v1)
    locations, attributes   -> mybusinessbusinessinformation (v1)
    reviews, posts, photos  -> mybusiness                    (v4, LEGACY)
    insights                -> businessprofileperformance    (v1)
    questions and answers   -> mybusinessqanda               (v1)

The v4 host is the one that catches people out. It is deprecated, it is the
only way to touch reviews, posts and photos, and access to it is granted
separately from the other APIs. A 403 from v4 while v1 works fine means your
project has not been approved for it -- see README, "Getting API access".

Everything here returns plain dicts. Nothing in this module interprets the
data; that is audit.py's job.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Any, Iterator

import requests
from google.auth.transport.requests import Request as GoogleRequest

from .auth import HOSTS, AuthError

# Every field the Business Information API will give us for a location.
# locations.get REQUIRES a readMask and silently returns almost nothing if you
# pass a short one, which looks exactly like an empty profile. Ask for it all.
FULL_READ_MASK = ",".join([
    "name", "languageCode", "storeCode", "title", "phoneNumbers", "categories",
    "storefrontAddress", "websiteUri", "regularHours", "specialHours",
    "serviceArea", "labels", "adWordsLocationExtensions", "latlng", "openInfo",
    "metadata", "profile", "relationshipData", "moreHours", "serviceItems",
])

# Metrics worth pulling. The Performance API renamed everything from the old
# Insights vocabulary; these are the current names.
DAILY_METRICS = [
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "BUSINESS_CONVERSATIONS",
    "BUSINESS_DIRECTION_REQUESTS",
    "CALL_CLICKS",
    "WEBSITE_CLICKS",
    "BUSINESS_BOOKINGS",
]

RETRY_STATUS = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    """An API call failed in a way the caller should see, with the reason."""

    def __init__(self, message: str, status: int | None = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


_CATEGORY_CACHE: dict[str, list[dict]] = {}


def _category_cache_path(key: str):
    from . import config
    return config.DATA_DIR / "categories" / f"{key}.json"


class Client:
    """Authenticated, retrying, rate-limit-aware GBP client."""

    def __init__(self, creds, *, timeout: int = 30, max_retries: int = 4,
                 min_interval: float = 0.25, verbose: bool = False):
        self._creds = creds
        self._session = requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        # Approved quota is 300 requests/minute. 0.25s between calls keeps us
        # at 240/min with no burst, which never trips it.
        self.min_interval = min_interval
        self.verbose = verbose
        self._last_call = 0.0

    # ---------------------------------------------------------------- plumbing

    def _headers(self) -> dict[str, str]:
        if not self._creds.valid:
            self._creds.refresh(GoogleRequest())
        return {
            "Authorization": f"Bearer {self._creds.token}",
            "Content-Type": "application/json",
        }

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def request(self, method: str, url: str, *, params: dict | None = None,
                json_body: dict | None = None) -> dict[str, Any]:
        last_error = ""
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self._session.request(
                    method, url, headers=self._headers(), params=params,
                    json=json_body, timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = str(exc)
                time.sleep(2 ** attempt)
                continue

            if self.verbose:
                print(f"  [api] {method} {resp.status_code} {url.split('?')[0]}")

            if resp.status_code < 300:
                if not resp.content:
                    return {}
                try:
                    return resp.json()
                except ValueError:
                    return {}

            # Keep enough of the body to be parseable. Google's 403 carries the
            # reason, the project id and the exact Cloud Console link inside a
            # JSON payload well past 600 characters, and truncating it turned a
            # fixable "the API is switched off, here is the button" into an
            # unreadable blob.
            body = resp.text[:8000]

            if resp.status_code in RETRY_STATUS:
                # Respect Retry-After when Google sends one, else back off.
                wait = resp.headers.get("Retry-After")
                delay = float(wait) if wait and wait.isdigit() else 2 ** attempt
                last_error = f"{resp.status_code}: {body}"
                time.sleep(delay)
                continue

            if resp.status_code == 401:
                raise AuthError(
                    "Google rejected the login (401).\n"
                    "  Run:  python run.py login"
                )
            if resp.status_code == 403:
                hint = ""
                if "/v4/" in url:
                    hint = (
                        "\n\n  This is the LEGACY v4 API (reviews, posts, photos).\n"
                        "  A 403 here while everything else works means your Google Cloud\n"
                        "  project has not been granted v4 access yet. See the README,\n"
                        "  'Getting API access' -- it is a form, and it takes a few days."
                    )
                raise ApiError(
                    f"Google refused the request (403).{hint}\n\n  {body}",
                    403, body)
            if resp.status_code == 404:
                raise ApiError(
                    f"Not found (404). The account or location id is probably wrong.\n\n  {body}",
                    404, body)

            raise ApiError(f"{method} failed ({resp.status_code}).\n\n  {body}",
                           resp.status_code, body)

        raise ApiError(f"{method} {url} failed after {self.max_retries} attempts. "
                       f"Last error: {last_error}")

    def _paged(self, url: str, key: str, params: dict | None = None) -> Iterator[dict]:
        """Walk a paged list endpoint, yielding items."""
        params = dict(params or {})
        while True:
            page = self.request("GET", url, params=params)
            for item in page.get(key, []) or []:
                yield item
            token = page.get("nextPageToken")
            if not token:
                return
            params["pageToken"] = token

    # ---------------------------------------------------------------- accounts

    def accounts(self) -> list[dict]:
        return list(self._paged(f"{HOSTS['account']}/accounts", "accounts",
                                {"pageSize": 20}))

    # --------------------------------------------------------------- locations

    def locations(self, account: str, read_mask: str = FULL_READ_MASK) -> list[dict]:
        """All locations on an account. `account` is like 'accounts/12345'."""
        return list(self._paged(
            f"{HOSTS['info']}/{account}/locations", "locations",
            {"readMask": read_mask, "pageSize": 100},
        ))

    def location(self, location: str, read_mask: str = FULL_READ_MASK) -> dict:
        """One location. `location` is like 'locations/12345'."""
        return self.request("GET", f"{HOSTS['info']}/{location}",
                            params={"readMask": read_mask})

    def patch_location(self, location: str, body: dict, update_mask: str) -> dict:
        """Write changes. update_mask decides what is touched -- anything not
        named is left alone, so this is safe to call with a partial body."""
        return self.request("PATCH", f"{HOSTS['info']}/{location}",
                            params={"updateMask": update_mask}, json_body=body)

    def attributes(self, location: str) -> dict:
        return self.request("GET", f"{HOSTS['info']}/{location}/attributes")

    def patch_attributes(self, location: str, attributes: list[dict],
                         attribute_mask: str) -> dict:
        return self.request(
            "PATCH", f"{HOSTS['info']}/{location}/attributes",
            params={"attributeMask": attribute_mask},
            json_body={"name": f"{location}/attributes", "attributes": attributes},
        )

    def available_attributes(self, category_id: str, region_code: str,
                             language_code: str = "en") -> list[dict]:
        """Which attributes this category can even have. Ask before writing --
        setting an attribute a category does not support is a 400."""
        return list(self._paged(
            f"{HOSTS['info']}/attributes", "attributeMetadata",
            {"categoryName": category_id, "regionCode": region_code,
             "languageCode": language_code, "pageSize": 100},
        ))

    def all_categories(self, region_code: str,
                       language_code: str = "en") -> list[dict]:
        """Every category Google offers in this country.

        There is no server-side search. `categories:search` is a v4 endpoint
        that no longer exists and returns a 404 HTML page, and the v1 `filter`
        parameter only does exact matches on displayName -- asking it for
        "makeup" returns nothing at all, which reads as "no such category"
        when the truth is "wrong query shape". So the whole list is paged once
        and searched here.
        """
        key = f"{region_code}-{language_code}"
        cached = _CATEGORY_CACHE.get(key)
        if cached:
            return cached

        # 4,000 categories is 41 round trips. Doing that once per keystroke in
        # a category picker would be unusable, so it is cached in memory and on
        # disk. The list changes perhaps a few times a year.
        path = _category_cache_path(key)
        if path.exists():
            try:
                disk = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(disk, list) and disk:
                    _CATEGORY_CACHE[key] = disk
                    return disk
            except (json.JSONDecodeError, OSError):
                pass

        out: list[dict] = []
        token = None
        for _ in range(60):  # ~4,000 categories at 100 a page, with headroom
            params = {"regionCode": region_code, "languageCode": language_code,
                      "view": "BASIC", "pageSize": 100}
            if token:
                params["pageToken"] = token
            page = self.request("GET", f"{HOSTS['info']}/categories",
                                params=params)
            out += page.get("categories", []) or []
            token = page.get("nextPageToken")
            if not token:
                break

        if out:
            _CATEGORY_CACHE[key] = out
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(out), encoding="utf-8")
            except OSError:
                pass  # a cache that cannot be written is not worth failing over
        return out

    def search_categories(self, query: str, region_code: str,
                          language_code: str = "en", limit: int = 10) -> list[dict]:
        """Categories whose name contains `query`, best match first.

        Punctuation is ignored on both sides. Google writes "Make-up artist"
        with a hyphen, so a search for "makeup" would otherwise come back empty
        and read as "Google has no makeup category" -- which is exactly the
        wrong conclusion to hand someone editing a live profile.
        """
        def flatten(text: str) -> str:
            # Separators are dropped, not turned into spaces: Google writes
            # "Make-up artist", and a search for "makeup" must still find it.
            return re.sub(r"[^a-z0-9]+", "", text.lower())

        needle = flatten(query)
        if not needle:
            return []
        scored = []
        for cat in self.all_categories(region_code, language_code):
            name = flatten(cat.get("displayName") or "")
            if needle not in name:
                continue
            # Exact, then starts-with, then contains -- so "beauty salon"
            # outranks "beauty products vending machine".
            rank = 0 if name == needle else 1 if name.startswith(needle) else 2
            scored.append((rank, len(name), cat))
        scored.sort(key=lambda x: (x[0], x[1]))
        return [c for _r, _l, c in scored[:limit]]

    def google_updates(self, location: str) -> dict:
        """Edits Google has applied or is proposing to the profile. This is the
        early-warning signal for someone hijacking a listing."""
        return self.request("GET", f"{HOSTS['info']}/{location}:getGoogleUpdated",
                            params={"readMask": FULL_READ_MASK})

    # ----------------------------------------------------- reviews (legacy v4)

    def reviews(self, account: str, location_id: str) -> list[dict]:
        """`location_id` is the bare numeric id, not 'locations/123'."""
        url = f"{HOSTS['legacy']}/{account}/locations/{location_id}/reviews"
        return list(self._paged(url, "reviews", {"pageSize": 50}))

    def reply_to_review(self, review_name: str, comment: str) -> dict:
        """`review_name` is the full name from the review object."""
        return self.request("PUT", f"{HOSTS['legacy']}/{review_name}/reply",
                            json_body={"comment": comment})

    # ------------------------------------------------------- posts (legacy v4)

    def local_posts(self, account: str, location_id: str) -> list[dict]:
        url = f"{HOSTS['legacy']}/{account}/locations/{location_id}/localPosts"
        return list(self._paged(url, "localPosts", {"pageSize": 100}))

    def create_local_post(self, account: str, location_id: str, post: dict) -> dict:
        url = f"{HOSTS['legacy']}/{account}/locations/{location_id}/localPosts"
        return self.request("POST", url, json_body=post)

    # ------------------------------------------------------- media (legacy v4)

    def media(self, account: str, location_id: str) -> list[dict]:
        url = f"{HOSTS['legacy']}/{account}/locations/{location_id}/media"
        return list(self._paged(url, "mediaItems", {"pageSize": 100}))

    def create_media(self, account: str, location_id: str, item: dict) -> dict:
        url = f"{HOSTS['legacy']}/{account}/locations/{location_id}/media"
        return self.request("POST", url, json_body=item)

    # ---------------------------------------------------------- place actions

    def place_action_links(self, location: str) -> list[dict]:
        """Booking, appointment and ordering links. Their own host again."""
        return list(self._paged(
            f"{HOSTS['placeactions']}/{location}/placeActionLinks",
            "placeActionLinks", {"pageSize": 100},
        ))

    def create_place_action_link(self, location: str, uri: str,
                                 action_type: str = "APPOINTMENT") -> dict:
        return self.request(
            "POST", f"{HOSTS['placeactions']}/{location}/placeActionLinks",
            json_body={"uri": uri, "placeActionType": action_type},
        )

    # ------------------------------------------------------------------- Q & A

    def questions(self, location: str) -> list[dict]:
        return list(self._paged(f"{HOSTS['qanda']}/{location}/questions",
                                "questions", {"pageSize": 50}))

    def answer_question(self, question_name: str, text: str) -> dict:
        return self.request("PATCH", f"{HOSTS['qanda']}/{question_name}/answers:upsert",
                            json_body={"answer": {"text": text}})

    # ------------------------------------------------------------- performance

    def performance(self, location_id: str, start: date, end: date) -> dict:
        """Daily metric time series for a date range. `location_id` is bare.

        Note the snake_case inside the query keys. The Performance API is the
        one Business Profile API that wants `start_date` rather than
        `startDate`, and it returns an empty series rather than an error when
        you get it wrong.
        """
        params: list[tuple[str, str]] = [("dailyMetrics", m) for m in DAILY_METRICS]
        params += [
            ("dailyRange.start_date.year", str(start.year)),
            ("dailyRange.start_date.month", str(start.month)),
            ("dailyRange.start_date.day", str(start.day)),
            ("dailyRange.end_date.year", str(end.year)),
            ("dailyRange.end_date.month", str(end.month)),
            ("dailyRange.end_date.day", str(end.day)),
        ]
        url = (f"{HOSTS['performance']}/locations/{location_id}"
               f":fetchMultiDailyMetricsTimeSeries")
        return self._request_multi(url, params)

    def search_keywords(self, location_id: str, start: date, end: date,
                        max_pages: int = 20) -> list[dict]:
        """The search terms people actually used to find this profile.

        This is what the Performance tab calls "Searches showed your Business
        Profile in the search results", and it is the single most useful thing
        Google gives away: the exact words real customers typed.

        Two quirks worth knowing:

          * The range is MONTHLY, not daily, and Google allows at most the
            last 12 months. The current month is usually not available yet.
          * A term's count comes back as either `value` (an exact number) or
            `threshold` (meaning "fewer than this"). Low-volume terms are
            always thresholded for privacy, and there are a lot of them.
        """
        params: list[tuple[str, str]] = [
            ("monthlyRange.start_month.year", str(start.year)),
            ("monthlyRange.start_month.month", str(start.month)),
            ("monthlyRange.end_month.year", str(end.year)),
            ("monthlyRange.end_month.month", str(end.month)),
            ("pageSize", "100"),
        ]
        url = (f"{HOSTS['performance']}/locations/{location_id}"
               f"/searchkeywords/impressions/monthly")

        out: list[dict] = []
        token = ""
        for _ in range(max_pages):
            page_params = list(params)
            if token:
                page_params.append(("pageToken", token))
            page = self._request_multi(url, page_params)
            out.extend(page.get("searchKeywordsCounts", []) or [])
            token = page.get("nextPageToken", "")
            if not token:
                break
        return out

    def _request_multi(self, url: str, params: list[tuple[str, str]]) -> dict:
        """requests needs a list of pairs for repeated query keys; the normal
        dict path cannot express `dailyMetrics` appearing nine times."""
        for attempt in range(self.max_retries):
            self._throttle()
            resp = self._session.get(url, headers=self._headers(), params=params,
                                     timeout=self.timeout)
            if resp.status_code < 300:
                return resp.json() if resp.content else {}
            if resp.status_code in RETRY_STATUS:
                time.sleep(2 ** attempt)
                continue
            raise ApiError(f"performance failed ({resp.status_code}).\n\n"
                           f"  {resp.text[:500]}", resp.status_code, resp.text[:500])
        raise ApiError("performance failed after retries")


def split_location_id(location_name: str) -> str:
    """'locations/12345' -> '12345'. The v4 and performance APIs want the bare
    id; the v1 APIs want the prefixed name. Mixing them up is a 404."""
    return location_name.split("/")[-1]
