"""The client-facing audit report.

This is the thing you actually send. It has to survive being forwarded, printed
to PDF and read on a phone by someone who does not know what a category is, so:
no external assets, no JavaScript, print stylesheet included, and every finding
carries its own "why this matters" in plain words.

Written with plain string formatting rather than a template engine so the tool
has one less dependency to install.
"""
from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from . import config
from .audit import AuditResult

SEVERITY_COLOR = {
    "critical": "#B3261E",
    "high": "#B45309",
    "medium": "#1D4ED8",
    "low": "#4B5563",
}
SEVERITY_LABEL = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def _e(text) -> str:
    return html.escape(str(text if text is not None else ""))


def _score_color(score: int) -> str:
    if score >= 75:
        return "#15803D"
    if score >= 50:
        return "#B45309"
    return "#B3261E"


CSS = """
*{box-sizing:border-box}
body{margin:0;background:#F3F4F6;color:#111827;
     font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.page{max-width:820px;margin:0 auto;padding:0 20px 72px}
header{padding:44px 0 26px;border-bottom:3px solid #111827}
.eyebrow{font-size:11px;letter-spacing:.16em;text-transform:uppercase;
         color:#6B7280;margin:0 0 10px}
h1{font-size:30px;line-height:1.15;margin:0 0 6px;font-weight:700}
.sub{color:#4B5563;margin:0;font-size:15px}
.scorecard{display:flex;flex-wrap:wrap;gap:22px;align-items:center;
           background:#fff;border:1px solid #E5E7EB;border-radius:6px;
           padding:24px;margin:26px 0}
.dial{width:118px;height:118px;border-radius:50%;display:grid;place-items:center;
      flex:0 0 auto;color:#fff;text-align:center}
.dial b{display:block;font-size:34px;line-height:1;font-weight:700}
.dial span{font-size:11px;letter-spacing:.09em;text-transform:uppercase;opacity:.9}
.scoretext{flex:1 1 260px}
.scoretext h2{margin:0 0 6px;font-size:19px}
.scoretext p{margin:0;color:#4B5563;font-size:15px}
h3{font-size:13px;letter-spacing:.09em;text-transform:uppercase;color:#374151;
   margin:36px 0 12px;padding-bottom:8px;border-bottom:1px solid #D1D5DB}
table.cats{width:100%;border-collapse:collapse;background:#fff;
           border:1px solid #E5E7EB;border-radius:6px;overflow:hidden}
table.cats td{padding:11px 14px;border-bottom:1px solid #F3F4F6;font-size:15px}
table.cats tr:last-child td{border-bottom:0}
td.pct{text-align:right;font-variant-numeric:tabular-nums;width:64px;font-weight:600}
.bar{height:7px;background:#E5E7EB;border-radius:4px;overflow:hidden;width:150px}
.bar i{display:block;height:100%}
.finding{background:#fff;border:1px solid #E5E7EB;border-left-width:4px;
         border-radius:5px;padding:16px 18px;margin:0 0 12px}
.finding .top{display:flex;flex-wrap:wrap;gap:9px;align-items:center;margin-bottom:7px}
.pill{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;
      padding:2px 8px;border-radius:3px;color:#fff;font-weight:600}
.auto{background:#065F46}
.finding h4{margin:0;font-size:17px;font-weight:650;flex:1 1 auto}
.finding .detail{margin:0 0 10px;font-weight:600;font-size:15px}
.finding .why,.finding .fix{margin:0 0 6px;font-size:14.5px;color:#374151}
.finding .why b,.finding .fix b{color:#111827}
.ok{background:#fff;border:1px solid #E5E7EB;border-radius:6px;padding:14px 18px}
.ok ul{margin:0;padding-left:20px;columns:2;column-gap:26px}
.ok li{font-size:14px;color:#374151;margin:0 0 4px;break-inside:avoid}
.note{background:#FEF3C7;border:1px solid #FDE68A;border-radius:6px;
      padding:13px 16px;font-size:14px;color:#78350F;margin:18px 0}
footer{margin-top:44px;padding-top:18px;border-top:1px solid #D1D5DB;
       font-size:12.5px;color:#6B7280}
@media print{
  body{background:#fff}
  .page{max-width:none;padding:0}
  .finding,.scorecard,table.cats,.ok{break-inside:avoid}
  header{padding-top:0}
}
@media (max-width:560px){
  .ok ul{columns:1}
  .bar{width:92px}
}
"""


def _finding_html(f) -> str:
    color = SEVERITY_COLOR[f.severity]
    auto = (f'<span class="pill auto">Automated</span>'
            if f.fixable else "")
    return f"""
    <div class="finding" style="border-left-color:{color}">
      <div class="top">
        <span class="pill" style="background:{color}">{SEVERITY_LABEL[f.severity]}</span>
        <h4>{_e(f.title)}</h4>
        {auto}
      </div>
      <p class="detail">{_e(f.detail)}</p>
      <p class="why"><b>Why it matters.</b> {_e(f.why)}</p>
      <p class="fix"><b>What to do.</b> {_e(f.fix)}</p>
    </div>"""


def build(result: AuditResult, *, prepared_by: str = "",
          previous_score: int | None = None) -> str:
    loc = result.location
    addr = loc.get("storefrontAddress", {}) or {}
    where = ", ".join(x for x in [addr.get("locality"), addr.get("regionCode")] if x)
    color = _score_color(result.score)

    trend = ""
    if previous_score is not None:
        delta = result.score - previous_score
        if delta:
            word = "up" if delta > 0 else "down"
            trend = (f" That is {word} {abs(delta)} point"
                     f"{'s' if abs(delta) != 1 else ''} since the last check.")

    fails = result.failures
    criticals = [f for f in fails if f.severity == "critical"]
    lead = (
        f"{len(fails)} issue{'s' if len(fails) != 1 else ''} found"
        + (f", {len(criticals)} of them critical." if criticals else ".")
        if fails else "Nothing failed on this profile."
    )

    cat_rows = []
    for _key, c in sorted(result.by_category.items(),
                          key=lambda kv: -(kv[1]["points"] or 0)):
        pct = c["percent"]
        if pct is None:
            bar, val = '<span style="color:#9CA3AF">not checked</span>', "&mdash;"
        else:
            bar = (f'<div class="bar"><i style="width:{pct}%;'
                   f'background:{_score_color(pct)}"></i></div>')
            val = f"{pct}%"
        cat_rows.append(
            f"<tr><td>{_e(c['label'])}</td><td>{bar}</td>"
            f'<td class="pct">{val}</td></tr>')

    findings_html = "".join(_finding_html(f) for f in fails) or (
        '<div class="ok"><p style="margin:0">Every check that could be run '
        'passed.</p></div>')

    passed = result.passes
    passed_html = ""
    if passed:
        items = "".join(f"<li>{_e(f.title)}</li>" for f in passed)
        passed_html = (f'<h3>Already correct ({len(passed)})</h3>'
                       f'<div class="ok"><ul>{items}</ul></div>')

    info_html = ""
    if result.informational:
        rows = "".join(
            f"<tr><td>{_e(f.title)}</td><td colspan='2'>{_e(f.detail)}</td></tr>"
            for f in result.informational)
        info_html = f"<h3>For reference</h3><table class='cats'>{rows}</table>"

    skipped_html = ""
    if result.skipped:
        skipped_html = (
            f'<div class="note"><b>Not checked:</b> {_e(", ".join(result.skipped))}. '
            f'These sections could not be read, so they are excluded from the '
            f'score rather than counted as failures.</div>')

    auto = result.fixable
    auto_html = ""
    if auto:
        # Group by the command that actually does it, so the report never
        # implies one button fixes everything.
        groups: dict[str, list[str]] = {}
        for f in auto:
            groups.setdefault(f.command or "this tool", []).append(f.title)
        parts = "".join(
            f"<li><b>{_e(cmd)}</b> &mdash; {_e(', '.join(titles))}</li>"
            for cmd, titles in sorted(groups.items()))
        auto_html = (
            f'<div class="note"><b>{len(auto)} of these are handled '
            f'automatically</b> by this tool:<ul style="margin:8px 0 0;'
            f'padding-left:20px">{parts}</ul></div>')

    by = f" &middot; Prepared by {_e(prepared_by)}" if prepared_by else ""
    when = result.generated_at.strftime("%d %B %Y")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Google Business Profile audit &ndash; {_e(result.title)}</title>
<style>{CSS}</style></head><body><div class="page">

<header>
  <p class="eyebrow">Google Business Profile audit</p>
  <h1>{_e(result.title)}</h1>
  <p class="sub">{_e(where)} &middot; {when}{by}</p>
</header>

<div class="scorecard">
  <div class="dial" style="background:{color}">
    <div><b>{result.score}</b><span>out of 100</span></div>
  </div>
  <div class="scoretext">
    <h2>{_e(result.grade)}</h2>
    <p>{_e(lead)}{_e(trend)}</p>
  </div>
</div>

{skipped_html}
{auto_html}

<h3>Where the profile stands</h3>
<table class="cats">{''.join(cat_rows)}</table>

<h3>What to fix, worst first</h3>
{findings_html}

{passed_html}
{info_html}

<footer>
  Audited against Google's own Business Profile guidelines and current local
  search ranking factors. Scores are weighted by impact: a critical issue costs
  more than a cosmetic one. Sections that could not be read are excluded rather
  than counted as failures.
</footer>

</div></body></html>"""


def write(result: AuditResult, *, prepared_by: str = "",
          previous_score: int | None = None,
          path: Path | None = None) -> Path:
    config.ensure_dirs()
    if path is None:
        slug = "".join(ch if ch.isalnum() else "-"
                       for ch in result.title.lower()).strip("-")[:50]
        stamp = result.generated_at.strftime("%Y-%m-%d")
        path = config.REPORT_DIR / f"{stamp}-{slug or 'audit'}.html"
    path.write_text(build(result, prepared_by=prepared_by,
                          previous_score=previous_score), encoding="utf-8")
    return path
