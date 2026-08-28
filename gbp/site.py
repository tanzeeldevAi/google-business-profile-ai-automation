"""Reading the business's own website.

Two jobs, both about the same thing: stop the tool making things up.

  1. When a profile is connected, its website is fetched automatically. That
     gives the description writer, the post writer and the image prompt the
     business's real words -- its actual service names, areas, and the way it
     talks about the work -- instead of a category label and a guess.

  2. You can point it at specific service page URLs. Posts then rotate through
     only those services, and every post is written FROM that page. A claim in
     a post has to be traceable back to the page it came from.

Nothing here trusts the network. A site that is down, slow, blocked or hostile
must never stop an audit or a review reply, so every failure degrades to "no
site content" and the rest of the run continues.

Fetched pages are cached to data/site/ so a daily run does not hammer a client's
server, and so you can see exactly what the writer was given.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from . import config

UA = ("Mozilla/5.0 (compatible; gbp-autopilot/1.0; "
      "+https://github.com/tanzeeldevAi/google-business-profile-ai-automation)")

# Paths that usually mean "this describes one thing we sell".
SERVICE_HINTS = re.compile(
    r"/(services?|our-services?|what-we-do|treatments?|repairs?|installations?|"
    r"solutions?|specialit(?:y|ies)|specialt(?:y|ies))(/|$)", re.I)

# Paths that never do. Cheap to exclude, and keeps the discovered list clean.
# Note `wp-` is a PREFIX rule, not a whole segment -- /wp-admin/index.php has
# to be caught, and requiring a following slash would miss it.
SKIP_HINTS = re.compile(
    r"/(blog|news|category|tag|author|privacy|terms|cookie|sitemap|feed|"
    r"cart|checkout|account|login|search|basket|my-account)(/|$)"
    r"|/wp-"
    r"|\.(pdf|jpg|jpeg|png|gif|webp|zip|xml|json|css|js)$", re.I)

# Elements that are never body copy.
STRIP_TAGS = ["script", "style", "nav", "header", "footer", "noscript",
              "form", "svg", "iframe", "aside"]


@dataclass
class Page:
    url: str
    title: str = ""
    h1: str = ""
    meta_description: str = ""
    headings: list[str] = field(default_factory=list)
    text: str = ""
    links: list[str] = field(default_factory=list)
    has_local_schema: bool = False
    phones: list[str] = field(default_factory=list)
    error: str = ""
    fetched_at: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.text)

    def summary(self, max_chars: int = 2600) -> str:
        """The block handed to the writer. Headings first, because they are the
        page's own summary of itself, then body text up to the cap."""
        bits = [f"PAGE: {self.url}"]
        if self.title:
            bits.append(f"Title: {self.title}")
        if self.h1 and self.h1 != self.title:
            bits.append(f"Heading: {self.h1}")
        if self.meta_description:
            bits.append(f"Meta description: {self.meta_description}")
        if self.headings:
            bits.append("Sections: " + " | ".join(self.headings[:12]))
        body = self.text[:max_chars]
        bits.append(f"\nPage content:\n{body}")
        return "\n".join(bits)


@dataclass
class Site:
    base_url: str = ""
    home: Page | None = None
    services: dict[str, Page] = field(default_factory=dict)
    fetched_at: float = 0.0
    notes: list[str] = field(default_factory=list)
    # Every URL the sitemap or the home page revealed. Not fetched, just known
    # to exist -- enough for W5 to judge whether the site has real depth.
    known_urls: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool((self.home and self.home.ok) or self.services)

    @property
    def pages(self) -> list[Page]:
        out = [self.home] if self.home and self.home.ok else []
        return out + [p for p in self.services.values() if p.ok]

    @property
    def all_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def page_for(self, url: str) -> Page | None:
        return self.services.get(_normalise(url))


# ------------------------------------------------------------------- fetching

def _normalise(url: str) -> str:
    """Trailing slashes and fragments are not different pages."""
    if not url:
        return ""
    url = url.split("#", 1)[0].strip()
    return url.rstrip("/") or url


def _clean_text(soup: BeautifulSoup) -> str:
    for tag in soup(STRIP_TAGS):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(" ", strip=True)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


PHONE_RE = re.compile(r"(?:\+?\d[\d\s().-]{7,16}\d)")

# Dates look exactly like phone numbers to the pattern above. 2026-08-07
# reduces to 20260807, which then fails to match the profile's real number and
# reports a NAP mismatch that does not exist. Caught on a live site.
DATE_RE = re.compile(
    r"\b(19|20)\d{2}[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b"
    r"|\b(0?[1-9]|[12]\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](19|20)\d{2}\b")


def extract_phones(text: str, limit: int = 10,
                   tel_links: list[str] | None = None) -> list[str]:
    """Phone numbers on a page, as digit strings.

    Deliberately strict, because the only thing these are used for is deciding
    whether the profile's number appears on the site. A false positive there
    tells a client their details are inconsistent when they are not, which is
    worse than finding nothing.

    Pass VISIBLE text, not raw HTML. Analytics ids, timestamps and asset
    hashes inside script tags look exactly like phone numbers and produced five
    false positives on the first live site this was pointed at. `tel:` links
    are taken as-is, because they are unambiguous.
    """
    out: list[str] = []

    for href in tel_links or []:
        digits = re.sub(r"[^\d+]", "", href)
        if 9 <= len(digits.lstrip("+")) <= 15:
            out.append(digits)

    for match in PHONE_RE.finditer(text):
        candidate = match.group(0)
        if DATE_RE.search(candidate):
            continue
        digits = re.sub(r"[^\d+]", "", candidate)
        bare = digits.lstrip("+")
        # Real numbers are 9 to 15 digits. A date is 8, a year is 4, and a
        # 16-digit run is a card number or an id, not a phone.
        if not (9 <= len(bare) <= 15):
            continue
        # A run of digits with no separators and no leading + or 0 is almost
        # always an id, a timestamp or a price in minor units.
        if candidate == bare and not bare.startswith("0"):
            continue
        out.append(digits)
    return list(dict.fromkeys(out))[:limit]


def fetch_page(url: str, timeout: int = 45, user_agent: str = "") -> Page:
    """Read one page.

    The timeout is generous and a slow read is retried once, because the sites
    this reads are small-business sites on shared hosting. A real client's site
    answered in anything from 1.4 to 17 seconds depending on whether its cache
    was warm; against the old 20-second limit that surfaced as "could not reach
    it (ReadTimeout)", and the audit reported the business's own working
    website as unreachable. Being slow is not the same as being down, and
    saying so cost the operator a wrong high-severity finding.
    """
    page = Page(url=_normalise(url), fetched_at=time.time())
    resp = None
    for attempt in range(2):
        try:
            resp = requests.get(url, timeout=timeout,
                                headers={"User-Agent": user_agent or UA,
                                         "Accept": "text/html,*/*"})
            break
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == 0:
                time.sleep(1.5)  # a cold cache usually warms on the second ask
                continue
            page.error = (f"could not reach it ({type(exc).__name__} twice, "
                          f"{timeout}s each)")
            return page
        except requests.RequestException as exc:
            page.error = f"could not reach it ({type(exc).__name__})"
            return page
    if resp is None:
        page.error = "could not reach it"
        return page

    if resp.status_code in (401, 403, 406, 429):
        # Cloudflare and friends block anything that identifies as a bot. The
        # default user agent here is honest about what it is, which is the
        # right default -- but this is usually your own client's site, so
        # website.user_agent in config.yaml lets you say otherwise.
        page.error = (f"returned {resp.status_code} (the site blocks automated "
                      f"requests -- set website.user_agent in config.yaml)")
        return page
    if resp.status_code >= 400:
        page.error = f"returned {resp.status_code}"
        return page
    if "html" not in resp.headers.get("Content-Type", "").lower():
        page.error = "not an HTML page"
        return page

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        page.error = f"could not be parsed ({exc})"
        return page

    raw = resp.text
    page.title = (soup.title.get_text(strip=True) if soup.title else "")[:200]
    h1 = soup.find("h1")
    page.h1 = h1.get_text(" ", strip=True)[:200] if h1 else ""
    md = soup.find("meta", attrs={"name": "description"})
    page.meta_description = (md.get("content", "") if md else "")[:400]
    page.headings = [h.get_text(" ", strip=True)[:120]
                     for h in soup.find_all(["h2", "h3"])[:20]
                     if h.get_text(strip=True)]

    # Links before the body is stripped of navigation.
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        if href.startswith(base):
            page.links.append(_normalise(href))
    page.links = list(dict.fromkeys(page.links))

    page.has_local_schema = bool(
        re.search(r'"@type"\s*:\s*"[^"]*(LocalBusiness|Plumber|Dentist|'
                  r'HomeAndConstructionBusiness|ProfessionalService|Store|'
                  r'Restaurant|MedicalBusiness|AutoRepair)', raw, re.I))

    # tel: links first -- unambiguous, and usually the header click-to-call.
    tel_links = [a["href"] for a in soup.find_all("a", href=True)
                 if a["href"].lower().startswith("tel:")]

    # Visible text INCLUDING the header, which is where the number usually is.
    # _clean_text drops the header for body copy, so the phone scan gets its
    # own pass over everything except scripts and styles.
    visible = BeautifulSoup(raw, "html.parser")
    for tag in visible(["script", "style", "noscript"]):
        tag.decompose()
    page.phones = extract_phones(visible.get_text(" ", strip=True),
                                 tel_links=tel_links)

    page.text = _clean_text(soup)
    if not page.text:
        page.error = "no readable text (it may be JavaScript-rendered)"
    return page


# ------------------------------------------------------------------ discovery

def _from_sitemap(base: str, timeout: int, limit: int) -> list[str]:
    """Sitemaps are the honest list of a site's pages. Try them first."""
    found: list[str] = []
    for name in ("sitemap.xml", "sitemap_index.xml", "wp-sitemap.xml"):
        try:
            resp = requests.get(urljoin(base + "/", name), timeout=timeout,
                                headers={"User-Agent": UA})
        except requests.RequestException:
            continue
        if resp.status_code >= 400:
            continue
        urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", resp.text)
        # A sitemap index points at more sitemaps; follow one level only.
        children = [u for u in urls if u.endswith(".xml")][:5]
        for child in children:
            try:
                sub = requests.get(child, timeout=timeout,
                                   headers={"User-Agent": UA})
                urls += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sub.text)
            except requests.RequestException:
                continue
        found = [u for u in urls if not u.endswith(".xml")]
        if found:
            break
    return found[:limit * 8]


def discover_service_pages(base_url: str, home: Page | None, *,
                           limit: int = 8, timeout: int = 20) -> list[str]:
    """Best guess at which pages describe one service each."""
    base = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    candidates = _from_sitemap(base, timeout, limit)
    if not candidates and home:
        candidates = home.links

    scored: list[tuple[int, str]] = []
    for url in dict.fromkeys(candidates):
        if not url.startswith(base) or SKIP_HINTS.search(url):
            continue
        path = urlparse(url).path.strip("/")
        if not path:
            continue
        score = 0
        if SERVICE_HINTS.search(urlparse(url).path):
            score += 10
        depth = path.count("/")
        # A service page is usually one or two levels deep, not six.
        score += 3 if depth in (0, 1) else (1 if depth == 2 else -2)
        if len(path) > 90:
            score -= 3
        scored.append((score, url))

    scored.sort(key=lambda s: (-s[0], s[1]))
    return [u for score, u in scored if score > 0][:limit]


# -------------------------------------------------------------------- caching

def _cache_path(base_url: str) -> Path:
    host = urlparse(base_url).netloc or "site"
    safe = re.sub(r"[^a-z0-9.-]+", "-", host.lower())
    d = config.DATA_DIR / "site"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def _load_cache(base_url: str, max_age_hours: float) -> Site | None:
    path = _cache_path(base_url)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if (time.time() - raw.get("fetched_at", 0)) > max_age_hours * 3600:
        return None
    site = Site(base_url=raw.get("base_url", ""),
                fetched_at=raw.get("fetched_at", 0),
                notes=raw.get("notes", []),
                known_urls=raw.get("known_urls", []) or [])
    if raw.get("home"):
        site.home = Page(**raw["home"])
    site.services = {k: Page(**v) for k, v in (raw.get("services") or {}).items()}
    return site


def _save_cache(site: Site) -> None:
    try:
        _cache_path(site.base_url).write_text(json.dumps({
            "base_url": site.base_url,
            "fetched_at": site.fetched_at,
            "notes": site.notes,
            "known_urls": site.known_urls,
            "home": asdict(site.home) if site.home else None,
            "services": {k: asdict(v) for k, v in site.services.items()},
        }, indent=2), encoding="utf-8")
    except OSError:
        pass


# --------------------------------------------------------------------- loading

def load(cfg: dict, website_uri: str = "", *, force: bool = False,
         verbose: bool = True) -> Site:
    """Fetch the website, or return the cached copy.

    Order of preference for which site to read:
        website.url in config  ->  the websiteUri on the Google profile

    Order of preference for which service pages to read:
        website.service_pages in config  ->  discovered from the sitemap
    """
    wcfg = cfg.get("website", {}) or {}
    if not wcfg.get("auto_fetch", True) and not wcfg.get("service_pages"):
        return Site(notes=["website.auto_fetch is off"])

    base = (wcfg.get("url") or website_uri or "").strip()
    listed = [u for u in (wcfg.get("service_pages") or []) if u]

    if not base and listed:
        base = listed[0]
    if not base:
        return Site(notes=["no website on the profile and none in config"])
    if not base.startswith("http"):
        base = "https://" + base

    max_age = float(wcfg.get("cache_hours", 168))
    if not force:
        cached = _load_cache(base, max_age)
        if cached:
            if verbose:
                age = (time.time() - cached.fetched_at) / 3600
                print(f"  {'site ':.<15} cached, {age:.0f}h old "
                      f"({len(cached.services)} service page(s))")
            return cached

    timeout = int(wcfg.get("timeout_seconds", 45))
    limit = int(wcfg.get("max_service_pages", 8))
    ua = wcfg.get("user_agent", "") or ""
    site = Site(base_url=base, fetched_at=time.time())

    def say(msg: str) -> None:
        if verbose:
            print(f"  {msg}")

    say(f"{'site ':.<15} reading {base}")
    site.home = fetch_page(base, timeout, ua)
    if not site.home.ok:
        site.notes.append(f"home page: {site.home.error}")
        say(f"{'site ':.<15} home page {site.home.error}")

    # Everything the sitemap knows about, whether or not we fetch it. This is
    # what W5 counts to judge whether the site has a page per service and area.
    site.known_urls = [u for u in _from_sitemap(base, timeout, 200)
                       if not SKIP_HINTS.search(u)]
    if not site.known_urls and site.home and site.home.ok:
        site.known_urls = [u for u in site.home.links
                           if not SKIP_HINTS.search(u)]

    if listed:
        targets = [_normalise(u) for u in listed]
        say(f"{'site ':.<15} {len(targets)} service page(s) from config")
    else:
        targets = discover_service_pages(base, site.home, limit=limit,
                                         timeout=timeout)
        say(f"{'site ':.<15} found {len(targets)} likely service page(s), "
            f"{len(site.known_urls)} page(s) on the site")

    for url in targets[:limit]:
        page = fetch_page(url, timeout, ua)
        if page.ok:
            site.services[_normalise(url)] = page
        else:
            site.notes.append(f"{url}: {page.error}")
            say(f"                skipped {url} -- {page.error}")

    if not site.ok:
        site.notes.append("nothing readable was fetched")

    _save_cache(site)
    return site


# ------------------------------------------------------------------ grounding

# Numbers that are part of ordinary prose rather than a claim about the
# business. "24/7" and a four-digit year are checked against the source anyway;
# these are the ones that carry no factual weight on their own.
_SAFE_NUMBERS = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"}


def unverified_numbers(text: str, sources: str) -> list[str]:
    """Numbers in `text` that do not appear in `sources`.

    This is the guard that makes "write it from the page" mean something. A
    model asked to write about boiler servicing will cheerfully add "over 500
    boilers serviced" because it reads well. If the number is not on the page
    and not in the owner's confirmed facts, it does not go on a public profile.
    """
    src = re.sub(r"[,\s]", "", sources)
    out: list[str] = []
    for token in re.findall(r"\d[\d,.]*", text):
        bare = token.rstrip(".").replace(",", "")
        if not bare or bare in _SAFE_NUMBERS:
            continue
        if bare in src:
            continue
        out.append(token)
    return list(dict.fromkeys(out))


def service_block(page: Page, max_chars: int = 2600) -> str:
    """The prompt block for one service page."""
    return page.summary(max_chars)


def business_block(site: Site, max_chars: int = 1800) -> str:
    """A short 'here is the business in its own words' block, from the home
    page. Used by the description writer and the image prompt."""
    if not site.home or not site.home.ok:
        return ""
    h = site.home
    bits = []
    if h.title:
        bits.append(f"Website title: {h.title}")
    if h.meta_description:
        bits.append(f"Website description: {h.meta_description}")
    if h.headings:
        bits.append("Website sections: " + " | ".join(h.headings[:10]))
    if h.text:
        bits.append(f"Website copy:\n{h.text[:max_chars]}")
    return "\n".join(bits)


def to_snapshot_dict(site: Site) -> dict:
    """The flat summary the audit rules read.

    Deliberately small: the rules only need to know whether the site is
    readable, what phone numbers are on it, and whether it carries schema. The
    full text stays out of the Snapshot so an audit stays cheap to store.
    """
    home = site.home
    return {
        "ok": bool(home and home.ok),
        "url": site.base_url,
        "error": (home.error if home and not home.ok else ""),
        "phones": list(home.phones) if home and home.ok else [],
        "has_local_schema": bool(home.has_local_schema) if home and home.ok
        else False,
        "service_pages": len(site.services),
        "page_count": len(site.known_urls),
        "title": home.title if home and home.ok else "",
    }


def show(site: Site) -> None:
    """Print what was fetched, so you can see exactly what the writer is given."""
    if not site.base_url:
        print("\n  No website to read.")
        for n in site.notes:
            print(f"    {n}")
        print()
        return

    age = (time.time() - site.fetched_at) / 3600 if site.fetched_at else 0
    print(f"\n  {site.base_url}   (fetched {age:.0f}h ago)\n")

    if site.home and site.home.ok:
        print(f"  HOME  {site.home.title[:66]}")
        print(f"        {len(site.home.text):,} characters of copy, "
              f"{len(site.home.links)} internal links")
        print(f"        LocalBusiness schema: "
              f"{'yes' if site.home.has_local_schema else 'no'}")
        if site.home.phones:
            print(f"        phone numbers on the page: "
                  f"{', '.join(site.home.phones[:3])}")
    else:
        print("  HOME  not readable")

    if site.services:
        print(f"\n  SERVICE PAGES ({len(site.services)}) -- posts rotate "
              f"through these:\n")
        for url, p in site.services.items():
            print(f"    {p.h1 or p.title or '(no heading)'}")
            print(f"      {url}")
            print(f"      {len(p.text):,} characters")
    else:
        print("\n  No service pages. Posts will use the services on the Google")
        print("  profile instead. To target specific ones, list their URLs")
        print("  under website.service_pages in config.yaml.")

    if site.notes:
        print("\n  Notes:")
        for n in site.notes:
            print(f"    {n}")
    print()
