#!/usr/bin/env python3
"""Fail publication when NIGHT SIGNAL is stale or structurally incomplete."""

from __future__ import annotations

import re
import sys
import json
from urllib.parse import unquote
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"
MAX_CARD_AGE_DAYS = 2
MIN_FRESH_CARDS = 12

REQUIRED_CATEGORIES = [
    "OpenAI",
    "SoftBank",
    "Honda",
    "F1",
    "SpaceX",
    "アジア経済",
    "宇都宮ブレックス",
    "投資",
]

REQUIRED_COVERAGE_TERMS = [
    "公式",
    "主要報道",
    "専門媒体",
    "SNS/X",
    "YouTube",
    "データ",
    "予定",
    "反証",
    "保留",
    "除外",
    "未確認",
]

REQUIRED_SOURCE_CLASSES = [
    "official",
    "major_media",
    "specialist_media",
    "sns_x",
    "youtube_video",
    "data_numeric",
    "schedule_calendar",
    "counter_search",
]

REQUIRED_DECISION_CLASSES = [
    "adopted",
    "held",
    "excluded",
    "unresolved",
]


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
    # Only visible metadata dates count. Links such as
    # href="2026-05-13/details/..." are publication paths, not item dates.
    return re.findall(r"<span class=\"pill[^\"]*\">(20\d{2}-\d{2}-\d{2})</span>", card)


def card_title(card: str) -> str:
    match = re.search(r"<h3>(.*?)</h3>", card, flags=re.S)
    if not match:
        return "(no title)"
    text = re.sub(r"<.*?>", "", match.group(1))
    return re.sub(r"\s+", " ", text).strip()


def local_href_targets(html: str, base: Path) -> list[Path]:
    targets = []
    for href in re.findall(r'href="([^"]+)"', html):
        if href.startswith(("#", "http://", "https://", "mailto:", "tel:")):
            continue
        path = unquote(href.split("#", 1)[0].split("?", 1)[0])
        if not path:
            continue
        targets.append((base / path).resolve())
    return targets


def validate_local_links(issue_date: str) -> None:
    html_files = [SITE_ROOT / "index.html", SITE_ROOT / issue_date / "index.html"]
    html_files.extend(sorted((SITE_ROOT / issue_date / "details").glob("*.html")))
    missing = []
    for html_file in html_files:
        html = read(html_file)
        for target in local_href_targets(html, html_file.parent):
            try:
                target.relative_to(ROOT)
            except ValueError:
                continue
            if not target.exists():
                missing.append(f"{html_file.relative_to(ROOT)} -> {target.relative_to(ROOT)}")
    if missing:
        fail("broken local links: " + "; ".join(missing[:12]))


def validate_detail_scope(issue_date: str, root_html: str, dated_html: str) -> None:
    linked = set(re.findall(rf'href="{issue_date}/details/([^"#?]+\.html)', root_html))
    linked.update(re.findall(r'href="details/([^"#?]+\.html)', dated_html))
    linked.add("policy.html")
    linked.add(f"extraction-log-{issue_date}.html")
    actual = {path.name for path in (SITE_ROOT / issue_date / "details").glob("*.html")}
    extra = actual - linked
    missing = linked - actual
    if missing:
        fail("published issue missing linked detail pages: " + ", ".join(sorted(missing)))
    if extra:
        fail("published issue contains unlinked stale detail pages: " + ", ".join(sorted(extra)[:12]))


def validate_extraction_log(extraction_log_html: str) -> None:
    missing_categories = [term for term in REQUIRED_CATEGORIES if term not in extraction_log_html]
    if missing_categories:
        fail("extraction log missing categories: " + ", ".join(missing_categories))

    missing_terms = [term for term in REQUIRED_COVERAGE_TERMS if term not in extraction_log_html]
    if missing_terms:
        fail("extraction log missing coverage terms: " + ", ".join(missing_terms))

    if "採用" not in extraction_log_html:
        fail("extraction log does not record adopted items")

    if "未確認" not in extraction_log_html and "重大リスク" not in extraction_log_html:
        fail("extraction log does not classify unresolved risk")

    manifest_match = re.search(
        r'<script type="application/json" id="coverage-manifest">(.*?)</script>',
        extraction_log_html,
        flags=re.S,
    )
    if not manifest_match:
        fail("extraction log missing coverage-manifest JSON")
    try:
        manifest = json.loads(manifest_match.group(1))
    except json.JSONDecodeError as exc:
        fail(f"coverage-manifest JSON is invalid: {exc}")

    categories = manifest.get("categories")
    if not isinstance(categories, dict):
        fail("coverage-manifest missing categories object")

    for category in REQUIRED_CATEGORIES:
        entry = categories.get(category)
        if not isinstance(entry, dict):
            fail(f"coverage-manifest missing category entry: {category}")
        for source_class in REQUIRED_SOURCE_CLASSES:
            value = entry.get(source_class)
            if not isinstance(value, list) or not value:
                fail(f"{category} missing source evidence: {source_class}")
        for decision_class in REQUIRED_DECISION_CLASSES:
            value = entry.get(decision_class)
            if not isinstance(value, list):
                fail(f"{category} missing decision list: {decision_class}")
        if not entry.get("search_terms"):
            fail(f"{category} missing search_terms")
        if not entry.get("freshness_check"):
            fail(f"{category} missing freshness_check")
        if entry.get("critical_unresolved"):
            fail(f"{category} has critical unresolved risks: {entry['critical_unresolved']}")


def validate(issue_date: str) -> None:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    sample = ROOT / f"night-brief-web-sample-{issue_date}.html"
    dated_index = SITE_ROOT / issue_date / "index.html"
    root_index = SITE_ROOT / "index.html"
    extraction_log = ROOT / "details" / f"extraction-log-{issue_date}.html"

    sample_html = read(sample)
    root_html = read(root_index)
    dated_html = read(dated_index)
    extraction_log_html = read(extraction_log)
    validate_extraction_log(extraction_log_html)

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

    validate_detail_scope(issue_date, root_html, dated_html)
    validate_local_links(issue_date)

    print(f"QUALITY GATE PASSED: {issue_date}, cards={len(cards)}, fresh={fresh_count}")


if __name__ == "__main__":
    validate(issue_date_from_args())
