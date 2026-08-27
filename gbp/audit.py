"""Assemble a Snapshot from the live API, run the rules, and score the result.

The fetch is deliberately forgiving. Reviews, posts and photos live on the
legacy v4 API, which a project can be refused access to, and the Performance
API can be empty for a young profile. Any section we cannot read is marked
unavailable and its rules report "not checked" instead of failing.

That distinction matters commercially: an audit that tells a prospect they have
no photos, when in fact we were never allowed to look, destroys the credibility
of every other line in the report.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import rules
from .api import ApiError, Client, split_location_id
from .rules import CATEGORY_LABELS, Finding, Snapshot

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class AuditResult:
    location: dict[str, Any]
    findings: list[Finding]
    score: int
    grade: str
    by_category: dict[str, dict[str, Any]]
    generated_at: datetime
    skipped: list[str]

    @property
    def title(self) -> str:
        return self.location.get("title", "Unknown business")

    @property
    def failures(self) -> list[Finding]:
        """Everything that failed, worst first. This is the report's spine."""
        return sorted(
            [f for f in self.findings if not f.passed and not f.informational],
            key=lambda f: (SEVERITY_ORDER[f.severity], f.rule_id),
        )

    @property
    def passes(self) -> list[Finding]:
        return [f for f in self.findings if f.passed and not f.informational]

    @property
    def informational(self) -> list[Finding]:
        return [f for f in self.findings if f.informational and f.detail]

    @property
    def fixable(self) -> list[Finding]:
        return [f for f in self.failures if f.fixable]


def _grade(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 60:
        return "Needs work"
    if score >= 40:
        return "Poor"
    return "Critical"


def score_findings(findings: list[Finding]) -> tuple[int, dict[str, dict]]:
    """Weighted score out of 100, plus a per-category breakdown.

    Informational rules carry zero points, so adding one never moves the score.
    A category where every rule was skipped is reported as not checked rather
    than as 100%, which would otherwise flatter a profile we could not read.
    """
    by_cat: dict[str, dict[str, Any]] = {}
    for f in findings:
        c = by_cat.setdefault(f.category, {
            "label": CATEGORY_LABELS.get(f.category, f.category),
            "points": 0, "earned": 0, "findings": [], "checked": 0,
        })
        c["findings"].append(f)
        c["points"] += f.points
        c["earned"] += f.earned
        if not f.informational:
            c["checked"] += 1

    for c in by_cat.values():
        c["percent"] = round(100 * c["earned"] / c["points"]) if c["points"] else None

    total_points = sum(c["points"] for c in by_cat.values())
    total_earned = sum(c["earned"] for c in by_cat.values())
    score = round(100 * total_earned / total_points) if total_points else 0
    return score, by_cat


def fetch_snapshot(client: Client, account: str, location_name: str,
                   *, verbose: bool = True) -> tuple[Snapshot, list[str]]:
    """Pull everything we are allowed to see. Returns the snapshot and a list
    of human-readable reasons for anything we had to skip."""
    location_id = split_location_id(location_name)
    skipped: list[str] = []
    available: set[str] = set()

    def say(msg: str) -> None:
        if verbose:
            print(f"  {msg}")

    location = client.location(location_name)
    available.add("location")
    say(f"profile ....... {location.get('title', '?')}")

    def attempt(label: str, key: str, fn):
        try:
            value = fn()
            available.add(key)
            n = len(value) if isinstance(value, (list, dict)) else 0
            say(f"{label:.<14} {n} item(s)" if isinstance(value, list)
                else f"{label:.<14} ok")
            return value
        except ApiError as exc:
            reason = "no API access" if exc.status == 403 else f"error {exc.status}"
            skipped.append(f"{label.strip()} ({reason})")
            say(f"{label:.<14} skipped -- {reason}")
            return [] if key != "performance" else {}

    reviews = attempt("reviews", "reviews",
                      lambda: client.reviews(account, location_id))
    posts = attempt("posts", "posts",
                    lambda: client.local_posts(account, location_id))
    media = attempt("photos", "media",
                    lambda: client.media(account, location_id))
    questions = attempt("questions", "questions",
                        lambda: client.questions(location_name))
    place_actions = attempt("booking links", "place_actions",
                            lambda: client.place_action_links(location_name))

    try:
        attributes = client.attributes(location_name)
        available.add("attributes")
        say(f"attributes .... {len(attributes.get('attributes', []) or [])} set")
    except ApiError as exc:
        skipped.append(f"attributes (error {exc.status})")
        attributes = {}

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=89)
    try:
        performance = client.performance(location_id, start, end)
        available.add("performance")
        say("performance ... 90 days pulled")
    except ApiError as exc:
        reason = "no API access" if exc.status == 403 else f"error {exc.status}"
        skipped.append(f"performance ({reason})")
        say(f"performance ... skipped -- {reason}")
        performance = {}

    snap = Snapshot(
        location=location, reviews=reviews, posts=posts, media=media,
        questions=questions, performance=performance, attributes=attributes,
        place_actions=place_actions, available=available,
        now=datetime.now(timezone.utc),
    )
    return snap, skipped


def audit(snapshot: Snapshot, cfg: dict | None = None,
          skipped: list[str] | None = None) -> AuditResult:
    findings = rules.run_all(snapshot, (cfg or {}).get("audit", {}) if cfg else {})
    score, by_cat = score_findings(findings)
    return AuditResult(
        location=snapshot.location,
        findings=findings,
        score=score,
        grade=_grade(score),
        by_category=by_cat,
        generated_at=snapshot.now,
        skipped=skipped or [],
    )


def print_summary(result: AuditResult) -> None:
    """Terminal summary. The HTML report is what a client sees; this is what
    you look at while you work."""
    print()
    print("=" * 72)
    print(f"  {result.title}")
    print(f"  Score {result.score}/100 -- {result.grade}")
    print("=" * 72)

    for key, cat in sorted(result.by_category.items(),
                           key=lambda kv: -(kv[1]["points"] or 0)):
        pct = cat["percent"]
        bar = "not checked" if pct is None else f"{pct:>3}%  " + \
            "#" * (pct // 10) + "." * (10 - pct // 10)
        print(f"  {cat['label']:.<32} {bar}")

    fails = result.failures
    if fails:
        print(f"\n  {len(fails)} issue(s), worst first:\n")
        for f in fails:
            mark = "[auto]" if f.fixable else "      "
            print(f"  {mark} {f.severity.upper():<8} {f.title}")
            print(f"           {f.detail}")
    else:
        print("\n  Nothing failed. That is rare -- check the skipped list below.")

    if result.skipped:
        print(f"\n  Not checked: {', '.join(result.skipped)}")

    auto = result.fixable
    if auto:
        # Name the command that actually does each one. Saying "run.py fix"
        # for a review backlog would be a promise the tool does not keep.
        cmds: dict[str, int] = {}
        for f in auto:
            key = f.command or "this tool"
            cmds[key] = cmds.get(key, 0) + 1
        print(f"\n  {len(auto)} of these are automated:")
        for cmd, n in sorted(cmds.items()):
            print(f"      python {cmd:<20} {n} item(s)")
    print()
