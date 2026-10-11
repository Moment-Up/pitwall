"""The weekly digest as one printable HTML page (``GET /api/drivers/{id}/digest.html``).

A single document: inline CSS, light colours, A4 with 16 mm margins, system fonts, no JavaScript and no external
requests. Every string goes through ``html.escape`` (driver, track and car names are user or game input). A beginner
gets the simple wording.
"""

from __future__ import annotations

import html
from datetime import date
from typing import Any

from pitwall.motivation.digest import goal_line, improvement_line, possessive, session_line, streak_lines, totals_line
from pitwall.motivation.model import short_date, week_range_text

_CSS = """
@page { size: A4; margin: 16mm; }
* { box-sizing: border-box; }
body { margin: 0; padding: 16px; background: #ffffff; color: #1b1f24;
  font: 12pt/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
h1 { font-size: 20pt; margin: 0 0 4px; }
h2 { font-size: 13pt; margin: 18px 0 6px; padding-bottom: 3px; border-bottom: 1px solid #d5dae1; }
.headline { font-size: 14pt; font-weight: 600; margin: 8px 0 2px; }
.totals { color: #4a5360; margin: 0 0 8px; }
ul { margin: 0; padding-left: 18px; }
li { margin: 3px 0; break-inside: avoid; }
.empty { color: #6b7480; }
footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid #d5dae1; color: #6b7480; font-size: 10pt; }
@media print { body { padding: 0; } }
"""


def _ul(items: list[str]) -> str:
    if not items:
        return '<ul><li class="empty">None this week.</li></ul>'
    return "<ul>" + "".join(f"<li>{html.escape(i)}</li>" for i in items) + "</ul>"


def digest_html(d: dict[str, Any]) -> str:
    e = html.escape
    name = str(d["driver"]["name"])
    simple = bool(d["simple"])
    start = date.fromisoformat(d["week_start"])
    end = date.fromisoformat(d["week_end"])
    title = f"{possessive(name)} week: {week_range_text(start, end)}"
    goals = [goal_line(g, simple) for g in d["goals"]["achieved"]]
    goals += [goal_line(a["goal"], simple, a["from_fraction"], a["to_fraction"]) for a in d["goals"]["active"]]
    badges = [f"{b['title_simple'] if simple else b['title']} ({short_date(b['earned_unix'])})" for b in d["badges"]]
    included = (
        "Synthetic sessions are included and marked; replayed sessions are not."
        if d.get("include_synthetic")
        else "Synthetic and replayed sessions are not included."
    )
    parts = [
        "<!doctype html>",
        '<html lang="en-GB"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{e(title)}</title><style>{_CSS}</style></head><body>",
        f"<h1>{e(title)}</h1>",
        f'<p class="headline">{e(d["headline_simple"] if simple else d["headline"])}</p>',
        f'<p class="totals">{e(totals_line(d))}</p>',
        "<h2>Sessions</h2>",
        _ul([session_line(r) for r in d["sessions"]]),
        "<h2>Best improvements</h2>",
        _ul([improvement_line(i) for i in d["improvements"]]),
        "<h2>Goals</h2>",
        _ul(goals) if goals else '<ul><li class="empty">No goals set.</li></ul>',
        "<h2>Badges this week</h2>",
        _ul(badges),
        "<h2>Streaks</h2>",
        _ul(streak_lines(d["streaks"])),
        f"<footer>Made by Pitwall on this computer from {e(possessive(name))} own driving. {e(included)}</footer>",
        "</body></html>",
    ]
    return "\n".join(parts)
