#!/usr/bin/env python3
"""gbp-autopilot -- audit, fix and run a Google Business Profile.

    python run.py doctor          check everything before you touch a profile
    python run.py login           sign in to Google (once)
    python run.py locations       list the profiles this account manages
    python run.py audit           score the profile and write an HTML report
    python run.py fix             apply what can be fixed automatically
    python run.py reviews         reply to unanswered reviews
    python run.py post            write and publish a Google Post
    python run.py dashboard       a local web UI for all of the above
    python run.py watch           what changed since last time
    python run.py daily           audit + watch + reviews + post, in order

Everything that writes is a DRY RUN unless you add --apply.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from datetime import datetime, timezone

from gbp import (api, audit as audit_mod, auth, citations, competitors, config,
                 dashboard as dash,
                 dataforseo as dfs, db, fix as fix_mod, holidays, images,
                 keywords as kw_mod, llm, posts, report, reviews,
                 site as site_mod, watch)
from gbp.api import ApiError, Client, split_location_id
from gbp.auth import AuthError

# Windows consoles still default to a legacy code page (cp1252 in western
# locales), which cannot encode Arabic, Urdu, Chinese or an emoji. The first
# live run of this tool died here: a profile in Khobar returns its search terms
# in Arabic, and printing one killed the whole audit after all the work was
# done. Force UTF-8, and fall back to replacement characters rather than losing
# a run to an encoding error.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # already UTF-8, or not a real stream
        pass


# ------------------------------------------------------------------- plumbing

def _client(cfg: dict, interactive: bool = True) -> Client:
    creds = auth.credentials(interactive=interactive)
    return Client(creds, verbose=cfg.get("verbose", False))


def _resolve(client: Client, cfg: dict, args) -> tuple[str, str]:
    """Work out which account and location to act on.

    Order: the --location flag, then config.yaml, then -- if the account has
    exactly one location -- that one. Anything else is an error, because
    guessing which client's profile to write to is not a thing this tool does.
    """
    want = getattr(args, "location", None) or cfg.get("location", {}).get("name")
    account_cfg = cfg.get("location", {}).get("account")

    accounts = client.accounts()
    if not accounts:
        raise SystemExit(
            "This Google account manages no Business Profiles.\n"
            "  Check you signed in as the account that owns or manages the "
            "profile.")

    if want and account_cfg:
        return account_cfg, want

    candidates: list[tuple[str, dict]] = []
    for acct in accounts:
        for loc in client.locations(acct["name"], read_mask="name,title"):
            candidates.append((acct["name"], loc))

    if want:
        for acct_name, loc in candidates:
            if loc["name"] == want or split_location_id(loc["name"]) == \
                    split_location_id(want):
                return acct_name, loc["name"]
        raise SystemExit(f"No location matching '{want}'. "
                         f"Run `python run.py locations` to see the list.")

    if len(candidates) == 1:
        acct_name, loc = candidates[0]
        return acct_name, loc["name"]

    print("\n  This account manages more than one profile. Pick one and put it "
          "in config.yaml under `location:`, or pass --location.\n")
    for acct_name, loc in candidates:
        print(f"    {loc['name']:<28} {loc.get('title', '')}")
        print(f"      account: {acct_name}")
    raise SystemExit(1)


def _snapshot(client: Client, cfg: dict, args, *, verbose: bool = True,
              fetch_site: bool = True):
    """Read the profile and its website.

    Returns account, location, snapshot, what was skipped, and the site
    content (or None). The website comes from the profile's own websiteUri, so
    connecting a profile is all it takes to ground the writing in the
    business's real words.
    """
    account, location = _resolve(client, cfg, args)
    if verbose:
        print(f"\n  Reading {location}\n")
    snap, skipped, site_data, analysis = audit_mod.fetch_snapshot(
        client, account, location, verbose=verbose, cfg=cfg,
        fetch_site=fetch_site)
    return account, location, snap, skipped, site_data, analysis


# ------------------------------------------------------------------- commands

def cmd_doctor(args) -> int:
    print("\n  gbp-autopilot doctor\n" + "  " + "-" * 40)
    ok = True

    try:
        cfg = config.load(args.config)
        print("  config.yaml ............ found")
    except SystemExit as exc:
        print(f"  config.yaml ............ MISSING\n\n{exc}")
        return 1

    for key in ("business.name", "business.what_we_do"):
        node = cfg
        for part in key.split("."):
            node = (node or {}).get(part) if isinstance(node, dict) else None
        mark = "set" if node else "EMPTY -- replies and posts will be generic"
        print(f"  {key + ' ':.<23} {mark}")
        ok = ok and bool(node)

    print(f"  client_secret.json ..... "
          f"{'found' if config.CLIENT_SECRET_PATH.exists() else 'MISSING'}")
    ok = ok and config.CLIENT_SECRET_PATH.exists()

    age = auth.token_age_days()
    if age is None:
        print("  google login ........... NOT SIGNED IN -- run: python run.py login")
        ok = False
    else:
        warn = ""
        if age > 5:
            warn = ("  <- close to the 7-day Testing-mode expiry. "
                    "Publish your OAuth consent screen.")
        print(f"  google login ........... {age:.1f} days old{warn}")

    backend = (cfg.get("llm", {}) or {}).get("backend", "claude")
    if backend == "claude":
        found = shutil.which("claude")
        print(f"  claude CLI ............. {'found' if found else 'NOT FOUND'}")
        ok = ok and bool(found)
    else:
        has = bool(config.env("ANTHROPIC_API_KEY"))
        print(f"  ANTHROPIC_API_KEY ...... {'set' if has else 'MISSING'}")
        ok = ok and has

    ib = (cfg.get("images", {}) or {}).get("backend", "none")
    host = (cfg.get("images", {}) or {}).get("host", "none")
    print(f"  image backend .......... {ib}")
    print(f"  image hosting .......... {host}")
    if ib != "none" and host == "none":
        print("       note: images will be generated but not hosted, so posts "
              "will go out as text only.")

    if age is not None:
        try:
            client = _client(cfg, interactive=False)
            accounts = client.accounts()
            print(f"  google API ............. ok, {len(accounts)} account(s)")
            for acct in accounts[:3]:
                locs = client.locations(acct["name"], read_mask="name,title")
                print(f"       {acct.get('accountName', acct['name'])}: "
                      f"{len(locs)} location(s)")
        except (AuthError, ApiError) as exc:
            print(f"  google API ............. FAILED\n\n{exc}\n")
            ok = False

    print("  " + "-" * 40)
    print("  Ready.\n" if ok else "  Fix the items above before going live.\n")
    return 0 if ok else 1


def cmd_login(args) -> int:
    auth.credentials(interactive=True)
    print("\n  Signed in. Token saved to data/token.json\n")
    print("  If your OAuth consent screen is still in Testing mode, this login")
    print("  expires in 7 days. Publish the app in Google Cloud Console to stop")
    print("  that happening.\n")
    return 0


def cmd_locations(args) -> int:
    cfg = config.load(args.config)
    client = _client(cfg)
    for acct in client.accounts():
        print(f"\n  {acct.get('accountName', '(no name)')}  [{acct['name']}]")
        locs = client.locations(acct["name"],
                                read_mask="name,title,storefrontAddress")
        if not locs:
            print("    (no locations)")
        for loc in locs:
            city = (loc.get("storefrontAddress", {}) or {}).get("locality", "")
            print(f"    {loc['name']:<28} {loc.get('title','')}"
                  f"{'  -- ' + city if city else ''}")
    print()
    return 0


def cmd_audit(args) -> int:
    cfg = config.load(args.config)
    db.init()
    client = _client(cfg)
    account, location, snap, skipped, site_data, analysis = _snapshot(
        client, cfg, args)

    result = audit_mod.audit(snap, cfg, skipped)
    audit_mod.print_summary(result)

    prev = db.previous_score(location)
    db.save_audit(location, result.title, result.score, result.grade,
                  [{"id": f.rule_id, "passed": f.passed, "severity": f.severity,
                    "title": f.title, "detail": f.detail} for f in result.findings])

    if not args.no_report:
        path = report.write(result, prepared_by=cfg.get("prepared_by", ""),
                            previous_score=prev)
        print(f"  Report: {path}\n")
    return 0


def cmd_fix(args) -> int:
    cfg = config.load(args.config)
    db.init()
    client = _client(cfg)
    account, location, snap, skipped, site_data, analysis = _snapshot(
        client, cfg, args)

    result = audit_mod.audit(snap, cfg, skipped)
    only = args.only.split(",") if args.only else None
    fixes = fix_mod.plan(result, snap, cfg, only=only, site_data=site_data,
                         analysis=analysis)
    fix_mod.show(fixes)
    if fixes:
        fix_mod.apply(fixes, client, location, dry_run=not args.apply)
    return 0


def cmd_reviews(args) -> int:
    cfg = config.load(args.config)
    db.init()
    client = _client(cfg)
    account, location = _resolve(client, cfg, args)
    location_id = split_location_id(location)

    try:
        all_reviews = client.reviews(account, location_id)
    except ApiError as exc:
        print(f"\n  Could not read reviews.\n\n{exc}\n")
        return 1

    print(f"\n  {len(all_reviews)} review(s), "
          f"{len(reviews.unanswered(all_reviews))} without a reply.\n")
    drafts = reviews.plan(all_reviews, cfg, location)
    reviews.show(drafts)
    if drafts:
        reviews.apply(drafts, client, location, dry_run=not args.apply,
                      include_held=args.include_held)
    return 0


def cmd_post(args) -> int:
    cfg = config.load(args.config)
    db.init()
    client = _client(cfg)
    account, location, snap, _sk, site_data, analysis = _snapshot(
        client, cfg, args, verbose=False)

    draft = posts.plan(snap, location, cfg, topic=args.topic,
                       with_image=not args.no_image, site_data=site_data,
                       url=args.url, analysis=analysis)
    posts.show(draft)
    posts.apply(draft, client, account, location, split_location_id(location),
                dry_run=not args.apply, force=args.force,
                language=cfg.get("posts", {}).get("language", "en"))
    return 0


def _our_facts(snap, client=None, account=None, location=None):
    """Our own review and photo counts, from Google rather than the scrape.

    They are authoritative on our side and only approximate on the competitor
    side, so we never compare a scraped number of ours against a scraped
    number of theirs when we have the real one.
    """
    reviews = len(snap.reviews) if "reviews" in snap.available else None
    photos = (len([m for m in snap.media if m.get("mediaFormat") == "PHOTO"])
              if "media" in snap.available else None)
    rating = None
    if reviews:
        stars = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5}
        vals = [stars.get(r.get("starRating", ""), 0) for r in snap.reviews]
        vals = [v for v in vals if v]
        rating = round(sum(vals) / len(vals), 2) if vals else None
    return reviews, rating, photos


def cmd_dashboard(args) -> int:
    """Serve the local web dashboard.

    Every button shells out to this same CLI, so the two can never disagree
    about what a command does.
    """
    cfg = config.load(args.config)
    db.init()
    dash.serve(cfg, host=args.host, port=args.port, token=args.token or "")
    return 0


def cmd_compare(args) -> int:
    """How this profile stacks up against whoever is actually ranking.

    The only part of the tool that needs a paid third party: Google's own API
    will only ever describe profiles you manage, so a competitor comparison is
    impossible without going outside it.
    """
    cfg = config.load(args.config)
    db.init()

    if not dfs.available():
        print("\n  This needs DataForSEO credentials in .env:\n"
              "    DATAFORSEO_LOGIN=...\n    DATAFORSEO_PASSWORD=...\n\n"
              "  Everything else in this tool works without them.\n")
        return 1

    client = _client(cfg)
    account, location, snap, _sk, _site, _kw = _snapshot(
        client, cfg, args, verbose=not args.quiet, fetch_site=False)

    ccfg = cfg.get("competitors", {}) or {}
    keywords = ([k.strip() for k in args.keywords.split(",")] if args.keywords
                else list(ccfg.get("keywords") or []))
    if not keywords:
        print("\n  No keywords. Pass --keywords \"plumber durham, boiler "
              "repair durham\"\n  or set competitors.keywords in config.yaml.\n")
        return 1

    latlng = snap.location.get("latlng") or {}
    result = competitors.compare(
        keywords,
        our_name=snap.title,
        our_phone=snap.get("phoneNumbers.primaryPhone", "") or "",
        our_place_id=snap.get("metadata.placeId", "") or "",
        latitude=latlng.get("latitude"),
        longitude=latlng.get("longitude"),
        location_name=ccfg.get("location_name", ""),
        language_code=ccfg.get("language_code", "en"),
        verbose=not args.quiet,
    )

    reviews, rating, photos = _our_facts(snap)
    competitors.show(result, our_reviews=reviews, our_rating=rating,
                     our_photos=photos)
    return 0


def cmd_citations(args) -> int:
    """Whether the directories showing this business agree on its phone number."""
    cfg = config.load(args.config)
    db.init()

    if not dfs.available():
        print("\n  This needs DataForSEO credentials in .env:\n"
              "    DATAFORSEO_LOGIN=...\n    DATAFORSEO_PASSWORD=...\n")
        return 1

    client = _client(cfg)
    _account, _location, snap, _sk, _site, _kw = _snapshot(
        client, cfg, args, verbose=not args.quiet, fetch_site=False)

    ccfg = cfg.get("competitors", {}) or {}
    # The organic endpoint refuses a task with no location, so fall back to the
    # country on the profile rather than letting the request be rejected and
    # reported as "no listings found".
    where = ccfg.get("location_name") or dfs.location_for(snap.region_code)
    if not where:
        print(f"\n  Could not work out a search location for region code "
              f"'{snap.region_code}'.\n  Set competitors.location_name in "
              f"config.yaml, e.g. \"Saudi Arabia\".\n")
        return 1

    check = citations.find(
        snap.title,
        snap.locality or (cfg.get("business", {}) or {}).get("city", ""),
        snap.get("phoneNumbers.primaryPhone", "") or "",
        location_name=where,
        language_code=ccfg.get("language_code", "en"),
        max_pages=int((cfg.get("citations", {}) or {}).get("max_pages", 10)),
        user_agent=(cfg.get("website", {}) or {}).get("user_agent", ""),
        verbose=not args.quiet,
    )
    citations.show(check)
    return 0


def cmd_keywords(args) -> int:
    """What people typed to find this profile, and whether it says those words.

    This is the Performance tab's search-terms list, pulled through the API and
    cross-referenced against everything on the profile. The terms with NOWHERE
    against them are the work.
    """
    cfg = config.load(args.config)
    db.init()
    client = _client(cfg)
    _account, _location, _snap, _sk, _site, analysis = _snapshot(
        client, cfg, args, verbose=not args.quiet)

    if analysis is None:
        print("\n  No search-term data came back.\n"
              "  Either the Performance API is not approved for this project "
              "yet, or\n  the profile is too new -- Google needs a few months "
              "of activity, and the\n  current month is never included.\n")
        return 1

    keywords_mod = kw_mod
    keywords_mod.show(analysis, limit=args.limit)

    if args.csv:
        import csv
        path = config.REPORT_DIR / f"search-terms-{_snap.title[:30]}.csv"
        config.ensure_dirs()
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["search term", "times shown", "exact count",
                        "brand search", "where it appears on the profile"])
            for c in analysis.coverage:
                w.writerow([c.keyword.term, c.keyword.impressions,
                            "yes" if c.keyword.exact else "no (threshold)",
                            "yes" if c.is_brand else "no",
                            ", ".join(c.places) or "NOWHERE"])
        print(f"  Full list: {path}\n")
    return 0


def cmd_site(args) -> int:
    """Show exactly what was read from the business's website.

    Worth running once when you connect a profile: it is the difference between
    trusting that the writer has good source material and knowing it does.
    """
    cfg = config.load(args.config)
    website = cfg.get("website", {}).get("url", "")

    if not website and not args.url:
        client = _client(cfg)
        _account, location = _resolve(client, cfg, args)
        loc = client.location(location, read_mask="name,title,websiteUri")
        website = loc.get("websiteUri", "")
        if not website:
            print("\n  This profile has no website linked, and none is set in "
                  "config.yaml\n  under website.url. Nothing to read.\n")
            return 1
        print(f"\n  Website on the profile: {website}")

    site_data = site_mod.load(cfg, args.url or website, force=args.refresh,
                              verbose=True)
    site_mod.show(site_data)
    return 0 if site_data.ok else 1


def cmd_watch(args) -> int:
    cfg = config.load(args.config)
    db.init()
    client = _client(cfg)
    account, location, snap, _sk, site_data, analysis = _snapshot(
        client, cfg, args, verbose=False)

    first = db.last_snapshot(location) is None
    changes = watch.run(snap, location)
    watch.show(changes, first_run=first)
    return 0


def cmd_daily(args) -> int:
    """Everything, in the order that makes sense: look, then act."""
    cfg = config.load(args.config)
    db.init()
    client = _client(cfg, interactive=False)
    account, location, snap, skipped, site_data, analysis = _snapshot(
        client, cfg, args)
    location_id = split_location_id(location)

    print("\n== 1. what changed ==")
    first = db.last_snapshot(location) is None
    watch.show(watch.run(snap, location), first_run=first)

    print("== 2. audit ==")
    result = audit_mod.audit(snap, cfg, skipped)
    prev = db.previous_score(location)
    db.save_audit(location, result.title, result.score, result.grade,
                  [{"id": f.rule_id, "passed": f.passed} for f in result.findings])
    audit_mod.print_summary(result)
    path = report.write(result, prepared_by=cfg.get("prepared_by", ""),
                        previous_score=prev)
    print(f"  Report: {path}")

    print("\n== 3. reviews ==")
    try:
        drafts = reviews.plan(client.reviews(account, location_id), cfg, location)
        reviews.show(drafts)
        if drafts:
            reviews.apply(drafts, client, location, dry_run=not args.apply)
    except ApiError as exc:
        print(f"  skipped: {exc}")

    if args.with_post:
        print("\n== 4. post ==")
        try:
            draft = posts.plan(snap, location, cfg, with_image=not args.no_image,
                               site_data=site_data, analysis=analysis)
            posts.show(draft)
            posts.apply(draft, client, account, location, location_id,
                        dry_run=not args.apply)
        except Exception as exc:
            print(f"  skipped: {exc}")

    alerts = db.open_alerts(location)
    if alerts:
        print(f"\n  {len(alerts)} open alert(s). "
              f"Run `python run.py alerts` to see them.")
    return 0


def cmd_alerts(args) -> int:
    db.init()
    rows = db.open_alerts()
    if not rows:
        print("\n  No open alerts.\n")
        return 0
    print()
    for r in rows:
        when = datetime.fromtimestamp(r["created_at"]).strftime("%d %b %H:%M")
        print(f"  {when}  {r['severity'].upper():<9} {r['message']}")
    if args.ack:
        n = db.acknowledge_alerts()
        print(f"\n  {n} alert(s) acknowledged.")
    print()
    return 0


def cmd_history(args) -> int:
    cfg = config.load(args.config)
    db.init()
    client = _client(cfg)
    _account, location = _resolve(client, cfg, args)
    rows = db.audit_history(location, limit=20)
    if not rows:
        print("\n  No audits recorded yet.\n")
        return 0
    print(f"\n  Score history for {location}\n")
    for r in rows:
        when = datetime.fromtimestamp(r["created_at"]).strftime("%d %b %Y")
        bar = "#" * (r["score"] // 5)
        print(f"  {when}  {r['score']:>3}/100  {r['grade']:<12} {bar}")
    print()
    return 0


def cmd_holidays(args) -> int:
    cfg = config.load(args.config)
    hcfg = cfg.get("holidays", {}) or {}
    region = args.region or hcfg.get("region_code", "")
    if not region:
        print("\n  Pass --region GB (or set holidays.region_code in config.yaml)\n")
        return 1
    days = int(args.days or hcfg.get("horizon_days", 60))
    ups = holidays.upcoming(region, days, extra=hcfg.get("extra"))
    print(f"\n  Public holidays in {region.upper()} in the next {days} days:\n")
    for d, name in ups:
        print(f"    {d}  {name}")
    if not ups:
        print("    (none)")
    if holidays.needs_manual_dates(region):
        print(f"\n  {region.upper()} also has holidays this tool will not guess "
              f"(lunar or\n  announced late). Add them under holidays.extra in "
              f"config.yaml.")
    print()
    return 0


# ----------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        prog="run.py", description="Google Business Profile autopilot")
    ap.add_argument("--config", help="path to config.yaml")
    sub = ap.add_subparsers(dest="command", required=True)

    def add(name, fn, help_text, *, loc=True, apply_flag=False):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=fn)
        if loc:
            p.add_argument("--location", help="locations/12345, or its number")
        if apply_flag:
            p.add_argument("--apply", action="store_true",
                           help="actually write to the live profile")
        return p

    add("doctor", cmd_doctor, "check config, login and API access", loc=False)
    add("login", cmd_login, "sign in to Google", loc=False)
    add("locations", cmd_locations, "list profiles this account manages", loc=False)

    p = add("audit", cmd_audit, "score the profile and write a report")
    p.add_argument("--no-report", action="store_true", help="skip the HTML file")

    p = add("fix", cmd_fix, "apply the automatic fixes", apply_flag=True)
    p.add_argument("--only", help="comma-separated: description,holiday_hours,services")

    p = add("reviews", cmd_reviews, "reply to unanswered reviews", apply_flag=True)
    p.add_argument("--include-held", action="store_true",
                   help="also send replies to low-star reviews")

    p = add("post", cmd_post, "write and publish a Google Post", apply_flag=True)
    p.add_argument("--topic", help="force the topic instead of rotating")
    p.add_argument("--url", help="write the post from this service page URL")
    p.add_argument("--no-image", action="store_true", help="text-only post")
    p.add_argument("--force", action="store_true",
                   help="publish even if the post could not be kept inside "
                        "its source page")

    p = sub.add_parser("dashboard", help="serve the local web dashboard")
    p.set_defaults(func=cmd_dashboard)
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--host", default="127.0.0.1",
                   help="leave this alone unless you know why you are changing it")
    p.add_argument("--token", help="required if --host is not localhost")

    p = sub.add_parser("compare",
                       help="how you stack up against the map pack")
    p.set_defaults(func=cmd_compare)
    p.add_argument("--location", help="locations/12345, or its number")
    p.add_argument("--keywords",
                   help="comma-separated, max 5, e.g. \"plumber durham, "
                        "boiler repair durham\"")
    p.add_argument("--quiet", action="store_true", help="skip the fetch log")

    p = sub.add_parser("citations",
                       help="do directories show the same phone number")
    p.set_defaults(func=cmd_citations)
    p.add_argument("--location", help="locations/12345, or its number")
    p.add_argument("--quiet", action="store_true", help="skip the fetch log")

    p = sub.add_parser("keywords",
                       help="what people typed to find this profile")
    p.set_defaults(func=cmd_keywords)
    p.add_argument("--location", help="locations/12345, or its number")
    p.add_argument("--limit", type=int, default=25,
                   help="how many terms to print (default 25)")
    p.add_argument("--csv", action="store_true",
                   help="also write the full list to reports/")
    p.add_argument("--quiet", action="store_true", help="skip the fetch log")

    p = sub.add_parser("site", help="show what was read from the website")
    p.set_defaults(func=cmd_site)
    p.add_argument("--location", help="locations/12345, or its number")
    p.add_argument("--url", help="read this site instead of the profile's")
    p.add_argument("--refresh", action="store_true",
                   help="re-fetch instead of using the cache")

    add("watch", cmd_watch, "report what changed since the last check")

    p = add("daily", cmd_daily, "watch + audit + reviews (+ post)", apply_flag=True)
    p.add_argument("--with-post", action="store_true", help="also publish a post")
    p.add_argument("--no-image", action="store_true", help="text-only post")

    p = sub.add_parser("alerts", help="open alerts from the watcher")
    p.set_defaults(func=cmd_alerts)
    p.add_argument("--ack", action="store_true", help="mark them all as seen")

    add("history", cmd_history, "audit score over time")

    p = sub.add_parser("holidays", help="what holidays are coming up")
    p.set_defaults(func=cmd_holidays)
    p.add_argument("--region", help="two-letter country code, e.g. GB")
    p.add_argument("--days", type=int, help="how far ahead to look")

    args = ap.parse_args()
    try:
        return args.func(args)
    except (AuthError, ApiError, llm.LLMError) as exc:
        print(f"\n  {exc}\n")
        return 1
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
        return 130
    except Exception:
        print("\n  Unexpected error:\n")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
