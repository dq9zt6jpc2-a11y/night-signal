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

REQUIRED_SECTIONS = {
    "softbank": "SoftBank",
    "openai": "OpenAI",
    "honda": "Honda",
    "f1": "F1",
    "spacex": "SpaceX",
    "asia": "アジア経済",
    "brex": "宇都宮ブレックス",
    "investment": "投資",
}

MIN_CARDS_PER_SECTION = 2
MIN_DETAIL_TEXT_CHARS = 300

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

REQUIRED_SEARCH_TERM_GROUPS = {
    "OpenAI": [
        ["openai"],
        ["daybreak", "deployment", "codex", "realtime", "sam"],
    ],
    "SoftBank": [
        ["softbank", "ソフトバンク"],
        ["arm", "vision", "openai", "ai"],
    ],
    "Honda": [
        ["honda", "ホンダ"],
        ["ev", "china", "earnings", "loss", "販売", "決算", "赤字"],
    ],
    "F1": [
        ["honda", "aston", "ホンダ"],
        ["aduo", "pu", "power unit", "fia", "ers", "回生"],
    ],
    "SpaceX": [
        ["spacex"],
        ["crs", "starship", "nasa", "dragon"],
    ],
    "アジア経済": [
        ["india", "インド"],
        ["vietnam", "ベトナム", "asean"],
    ],
    "宇都宮ブレックス": [
        ["宇都宮", "brex", "ブレックス"],
        ["b.league", "試合", "日程", "名古屋", "結果"],
    ],
    "投資": [
        ["etf", "株", "market", "fund", "指数"],
        ["fed", "金利", "flows", "ai", "semiconductor", "半導体"],
    ],
}

TITLE_POLICY_LEAK_TERMS = [
    "一次で固定",
    "一次資料",
    "一次更新",
    "数字を固定",
    "完了扱い",
    "補助線",
    "採用は一次",
    "採用前",
    "保留に落と",
    "直検索",
    "カバレッジ",
    "品質ゲート",
]

DETAIL_POLICY_LEAK_TERMS = TITLE_POLICY_LEAK_TERMS + [
    "今夜やること",
    "今夜のチェックリスト",
    "今夜の運用ルール",
    "機械的",
    "監査メモ",
    "復旧版",
    "当日版が未生成",
]

HEADLINE_ABSTRACT_LEAK_TERMS = [
    "個人の文脈",
    "安全の文脈",
    "同じ地図",
    "CPUの現場",
    "投資枠とインフラ",
    "ロスター更新",
    "打ち上げ結果",
    "製品”と“資本",
    "扱い始める",
    "温度感",
    "前に出す",
    "同じ線",
    "現物",
    "足回り",
    "見る日",
    "読む日",
    "意味",
    "更新導線",
]

HEADLINE_FORBIDDEN_CHARS = ["→", "“", "”"]
GENERIC_HEADLINE_STARTS = ["何が", "なぜ", "どう見る", "読み方", "ポイント"]
DETAIL_ALIGNMENT_KEYWORDS = [
    "ChatGPT",
    "家計",
    "口座",
    "安全",
    "リスク",
    "SoftBank",
    "Arm",
    "データセンター",
    "Honda",
    "EV",
    "HV",
    "ADUO",
    "FIA",
    "CRS-34",
    "Falcon",
    "Dragon",
    "ISS",
    "Starship",
    "Flight 12",
    "ベトナム",
    "IIP",
    "インド",
    "外貨準備",
    "名古屋",
    "ジェレット",
    "米株",
    "ファンド",
    "ETF",
    "ICI",
    "フロー",
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


def card_detail_href(card: str) -> str | None:
    match = re.search(r'href="([^"]*details/([^"#?]+\.html))', card)
    if not match:
        return None
    return match.group(2)


def page_titles(html: str) -> list[str]:
    titles = []
    for match in re.finditer(r"<h3>(.*?)</h3>", section_before_history(html), flags=re.S):
        text = re.sub(r"<.*?>", "", match.group(1))
        titles.append(re.sub(r"\s+", " ", text).strip())
    return titles


def heading_texts(html: str, tags: tuple[str, ...]) -> list[str]:
    tag_pattern = "|".join(tags)
    texts = []
    for match in re.finditer(rf"<({tag_pattern})[^>]*>(.*?)</\1>", html, flags=re.S):
        text = re.sub(r"<.*?>", "", match.group(2))
        texts.append(re.sub(r"\s+", " ", text).strip())
    return texts


def validate_reader_facing_headlines(context: str, headings: list[str]) -> None:
    failures = []
    for heading in headings:
        if any(term in heading for term in HEADLINE_ABSTRACT_LEAK_TERMS):
            failures.append(f"{heading} [abstract phrase]")
            continue
        if any(char in heading for char in HEADLINE_FORBIDDEN_CHARS):
            failures.append(f"{heading} [quote/arrow shorthand]")
            continue
        if any(heading.startswith(prefix) for prefix in GENERIC_HEADLINE_STARTS):
            failures.append(f"{heading} [generic start]")
    if failures:
        fail(f"{context} headings are not reader-facing: " + "; ".join(failures[:8]))


def alignment_keywords(title: str) -> list[str]:
    return [keyword for keyword in DETAIL_ALIGNMENT_KEYWORDS if keyword in title]


def validate_card_detail_alignment(issue_date: str, root_html: str, dated_html: str) -> None:
    cards = card_blocks(root_html) + card_blocks(dated_html)
    by_detail: dict[str, set[str]] = {}
    for card in cards:
        name = card_detail_href(card)
        if not name:
            continue
        by_detail.setdefault(name, set()).add(card_title(card))

    failures = []
    for name, titles in sorted(by_detail.items()):
        if name in {"policy.html", f"extraction-log-{issue_date}.html"}:
            continue
        path = SITE_ROOT / issue_date / "details" / name
        html = read(path)
        primary = " ".join(heading_texts(html, ("title", "h1")))
        body = " ".join(heading_texts(html, ("title", "h1", "h2")))
        summary_match = re.search(r'<div class="summary-lead">(.*?)</div>', html, flags=re.S)
        if summary_match:
            body += " " + re.sub(r"<.*?>", "", summary_match.group(1))
        for title in sorted(titles):
            keywords = alignment_keywords(title)
            if not keywords:
                continue
            primary_hits = [keyword for keyword in keywords if keyword in primary]
            body_hits = [keyword for keyword in keywords if keyword in body]
            required_primary_hits = min(2, len(keywords))
            if len(primary_hits) < required_primary_hits or len(body_hits) < required_primary_hits:
                failures.append(
                    f"{title} -> {name} (primary hits: {primary_hits or '-'}, expected: {keywords})"
                )
    if failures:
        fail("card/detail title mismatch: " + "; ".join(failures[:8]))


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


def validate_detail_quality(issue_date: str, root_html: str, dated_html: str) -> None:
    linked = set(re.findall(rf'href="{issue_date}/details/([^"#?]+\.html)', root_html))
    linked.update(re.findall(r'href="details/([^"#?]+\.html)', dated_html))
    excluded = {"policy.html", f"extraction-log-{issue_date}.html"}
    weak = []
    leaked = []
    missing_source = []
    missing_back = []
    for name in sorted(linked - excluded):
        path = SITE_ROOT / issue_date / "details" / name
        html = read(path)
        plain = re.sub(r"<[^>]+>", "", html)
        plain = re.sub(r"\s+", "", plain)
        if len(plain) < MIN_DETAIL_TEXT_CHARS:
            weak.append(f"{name}: {len(plain)} chars")
        headings = " ".join(re.findall(r"<(?:title|h1|h2)[^>]*>(.*?)</(?:title|h1|h2)>", html, flags=re.S))
        heading_text = re.sub(r"<[^>]+>", "", headings)
        if any(term in heading_text for term in DETAIL_POLICY_LEAK_TERMS):
            leaked.append(name)
        validate_reader_facing_headlines(
            f"detail page {name}",
            heading_texts(html, ("title", "h1")),
        )
        if 'class="source"' not in html or "原文確認" not in html:
            missing_source.append(name)
        if 'class="back"' not in html or "../index.html" not in html:
            missing_back.append(name)
    if weak:
        fail("detail pages too thin: " + "; ".join(weak[:8]))
    if leaked:
        fail("detail headings contain policy/checklist wording: " + ", ".join(leaked[:8]))
    if missing_source:
        fail("detail pages missing source block: " + ", ".join(missing_source[:8]))
    if missing_back:
        fail("detail pages missing back link: " + ", ".join(missing_back[:8]))


def validate_category_sections(root_html: str) -> None:
    body = section_before_history(root_html)
    missing = []
    too_thin = []
    for section_id, label in REQUIRED_SECTIONS.items():
        match = re.search(
            rf'<section class="section" id="{section_id}">(.*?)(?=<section class="section" id=|\Z)',
            body,
            flags=re.S,
        )
        if not match:
            missing.append(label)
            continue
        count = len(re.findall(r'<article class="card[^"]*">', match.group(1)))
        if count < MIN_CARDS_PER_SECTION:
            too_thin.append(f"{label}: {count}")
    if missing:
        fail("missing category sections: " + ", ".join(missing))
    if too_thin:
        fail("category sections below minimum cards: " + ", ".join(too_thin))


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
            if any(not isinstance(item, str) or len(item.strip()) < 4 for item in value):
                fail(f"{category} has weak source evidence: {source_class}")
        for decision_class in REQUIRED_DECISION_CLASSES:
            value = entry.get(decision_class)
            if not isinstance(value, list):
                fail(f"{category} missing decision list: {decision_class}")
        search_terms = entry.get("search_terms")
        if not isinstance(search_terms, list) or not search_terms:
            fail(f"{category} missing search_terms")
        search_blob = " ".join(str(term).lower() for term in search_terms)
        for group in REQUIRED_SEARCH_TERM_GROUPS[category]:
            if not any(term.lower() in search_blob for term in group):
                fail(f"{category} search_terms missing required axis: {'/'.join(group)}")
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

    leaked_titles = [
        title
        for title in page_titles(root_html)
        if any(term in title for term in TITLE_POLICY_LEAK_TERMS)
    ]
    if leaked_titles:
        fail("card titles contain policy/checklist wording: " + "; ".join(leaked_titles[:8]))

    validate_reader_facing_headlines(
        "root page",
        heading_texts(section_before_history(root_html), ("h1", "h3")),
    )

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

    validate_category_sections(root_html)
    validate_detail_quality(issue_date, root_html, dated_html)
    validate_card_detail_alignment(issue_date, root_html, dated_html)

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
