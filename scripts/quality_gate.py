#!/usr/bin/env python3
"""Fail publication when NIGHT SIGNAL is stale or structurally incomplete."""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"
MAX_CARD_AGE_DAYS = 3
MIN_FRESH_CARDS = 8


def issue_date_from_args() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return datetime.now().strftime("%Y-%m-%d")


def fail(message: str) -> None:
    print(f"QUALITY GATE FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: Path) -> str:
    if not path.exists():
        fail(f"missing file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def section_before_history(html: str) -> str:
    return html.split('<section class="section" id="history">', 1)[0]


def card_blocks(html: str) -> list[str]:
    body = section_before_history(html)
    return re.findall(r"<article class=\"(?:card|priority-card)[^\"]*\">.*?</article>", body, flags=re.S)


def card_dates(card: str) -> list[str]:
    return re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", card)


def card_title(card: str) -> str:
    match = re.search(r"<h3>(.*?)</h3>", card, flags=re.S)
    if not match:
        return "(no title)"
    text = re.sub(r"<.*?>", "", match.group(1))
    return re.sub(r"\s+", " ", text).strip()


def validate(issue_date: str) -> None:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    sample = ROOT / f"night-brief-web-sample-{issue_date}.html"
    dated_index = SITE_ROOT / issue_date / "index.html"
    root_index = SITE_ROOT / "index.html"
    extraction_log = ROOT / "details" / f"extraction-log-{issue_date}.html"

    sample_html = read(sample)
    root_html = read(root_index)
    dated_html = read(dated_index)
    read(extraction_log)

    expected_title = f"NIGHT SIGNAL | {issue_date}"
    if expected_title not in sample_html or expected_title not in root_html or expected_title not in dated_html:
        fail(f"issue title/date mismatch; expected {expected_title}")

    display_date = issue_date.replace("-", ".")
    if display_date not in root_html:
        fail(f"root page does not display {display_date}")

    cards = card_blocks(root_html)
    if not cards:
        fail("no cards found before history")

    stale: list[str] = []
    fresh_count = 0
    undated: list[str] = []
    for card in cards:
        dates = card_dates(card)
        if not dates:
            # Priority cards may omit explicit dates; ignore those.
            if "priority-card" not in card:
                undated.append(card_title(card))
            continue
        newest = max(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
        age = (issue_dt - newest).days
        if age < 0:
            # Future scheduled events are allowed only when clearly marked as a plan.
            if "予定" not in card and "次回" not in card and "発表" not in card:
                stale.append(f"future date without schedule context: {card_title(card)} ({newest})")
            continue
        if age > MAX_CARD_AGE_DAYS:
            stale.append(f"{card_title(card)} ({newest}, {age} days old)")
        if age <= 1:
            fresh_count += 1

    if undated:
        fail("undated cards found: " + "; ".join(undated[:5]))
    if stale:
        fail("stale cards found: " + "; ".join(stale[:8]))
    if fresh_count < MIN_FRESH_CARDS:
        fail(f"too few fresh cards dated {issue_date} or previous day: {fresh_count} < {MIN_FRESH_CARDS}")

    required_links = [
        f"{issue_date}/details/extraction-log-{issue_date}.html",
        f"{issue_date}/details/policy.html",
    ]
    for link in required_links:
        if link not in root_html:
            fail(f"missing required root link: {link}")

    print(f"QUALITY GATE PASSED: {issue_date}, cards={len(cards)}, fresh={fresh_count}")


if __name__ == "__main__":
    validate(issue_date_from_args())
