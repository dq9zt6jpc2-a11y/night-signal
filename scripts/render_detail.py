#!/usr/bin/env python3
"""Render a NIGHT SIGNAL detail page from structured content.

This is the preferred creation path for detail pages. New issues expose only
the reader-facing sections we want to publish:

- 要点と背景
- 確認した事実
- 未確定点
- 原文確認

Current issues use a compact information structure, not a time-boxed overview.
Authoring checklist sections are never published.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "details"
CONFIG_PATH = ROOT / "config" / "night_signal_coverage.json"
LEGACY_MIN_SUMMARY_CHARS = 180
MAX_SOURCE_LINKS = 3
LEGACY_SUMMARY_HEADING = "30秒概要"
DEFAULT_SUMMARY_HEADING = "要点と背景"
FORBIDDEN_TEXT = [
    "30秒概要",
    "チェック観点",
    "次の確認",
    "次の予定",
    "読むポイント",
    "今回の要点",
    "一次で押さえる点",
    "最新採用",
    "再確認",
    "上書き",
    "落とし込",
    "固定し",
    "混ぜない",
    "今日の再抽出",
    "今日の更新",
    "本日の更新",
    "本日の修正",
    "日付だけ",
    "差し替え",
    "品質ゲート",
    "監査メモ",
    "カードを",
    "版では",
    "導線",
    "点検",
    "拾う",
    "確認して",
    "位置づけ",
    "説明軸",
    "IR文脈",
    "読み筋",
    "読める状態",
    "材料になっている",
    "更新局面",
    "並行管理",
    "競争軸",
    "発表局面",
    "作業指示",
]
FORBIDDEN_PATTERNS = [
    (r"作業(?:指示|説明|メモ|語|上|として|を書)", "authoring work wording"),
]


def fail(message: str) -> None:
    print(f"DETAIL RENDER FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def minimum_summary_chars(issue_date: str) -> int:
    try:
        contract = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return LEGACY_MIN_SUMMARY_CHARS

    effective_value = contract.get("summary_quality_effective_date")
    if not isinstance(effective_value, str):
        return LEGACY_MIN_SUMMARY_CHARS
    try:
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
        effective_dt = datetime.strptime(effective_value, "%Y-%m-%d").date()
    except ValueError:
        return LEGACY_MIN_SUMMARY_CHARS
    if issue_dt < effective_dt:
        return LEGACY_MIN_SUMMARY_CHARS
    return int(contract.get("minimum_detail_summary_chars", LEGACY_MIN_SUMMARY_CHARS))


def effective_on_or_after(issue_date: str, key: str) -> bool:
    try:
        contract = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    effective_value = contract.get(key)
    if not isinstance(effective_value, str):
        return False
    try:
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
        effective_dt = datetime.strptime(effective_value, "%Y-%m-%d").date()
    except ValueError:
        return False
    return issue_dt >= effective_dt


def detail_information_contract_required(issue_date: str) -> bool:
    return effective_on_or_after(issue_date, "detail_information_contract_effective_date")


def summary_heading(issue_date: str) -> str:
    try:
        contract = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return LEGACY_SUMMARY_HEADING

    effective_value = contract.get("detail_summary_heading_effective_date")
    if not isinstance(effective_value, str):
        return LEGACY_SUMMARY_HEADING
    try:
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
        effective_dt = datetime.strptime(effective_value, "%Y-%m-%d").date()
    except ValueError:
        return LEGACY_SUMMARY_HEADING
    if issue_dt < effective_dt:
        return LEGACY_SUMMARY_HEADING
    heading = contract.get("detail_summary_heading", DEFAULT_SUMMARY_HEADING)
    if isinstance(heading, str) and heading.strip():
        return heading.strip()
    return DEFAULT_SUMMARY_HEADING


def article_summary_required(issue_date: str) -> bool:
    try:
        contract = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    effective_value = contract.get("article_summary_effective_date")
    if not isinstance(effective_value, str):
        return False
    try:
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
        effective_dt = datetime.strptime(effective_value, "%Y-%m-%d").date()
    except ValueError:
        return False
    return issue_dt >= effective_dt


def required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"missing required string: {key}")
    return value.strip()


def required_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        fail(f"missing required list: {key}")
    return value


def required_summary_basis(data: dict[str, Any]) -> dict[str, Any]:
    basis = data.get("summary_basis")
    if not isinstance(basis, dict):
        fail("missing required object: summary_basis")
    for key in ("what_changed", "why_it_matters", "limits_or_unknowns"):
        required_str(basis, key)
    facts = required_list(basis, "confirmed_facts")
    if any(not isinstance(fact, str) or not fact.strip() for fact in facts):
        fail("summary_basis.confirmed_facts must contain reader-facing facts")
    source_dates = required_list(basis, "source_dates")
    if any(not isinstance(date, str) or not date.strip() for date in source_dates):
        fail("summary_basis.source_dates must contain source dates")
    return basis


def reject_forbidden(label: str, text: str) -> None:
    found = [term for term in FORBIDDEN_TEXT if term in text]
    if found:
        fail(f"{label} contains authoring/checklist wording: {', '.join(found)}")
    pattern_hits = [name for pattern, name in FORBIDDEN_PATTERNS if re.search(pattern, text)]
    if pattern_hits:
        fail(f"{label} contains authoring/checklist wording: {', '.join(pattern_hits)}")


def reject_basis_forbidden(basis: dict[str, Any]) -> None:
    for key in ("what_changed", "why_it_matters", "limits_or_unknowns"):
        reject_forbidden(f"summary_basis.{key}", required_str(basis, key))
    for index, fact in enumerate(required_list(basis, "confirmed_facts"), start=1):
        reject_forbidden(f"summary_basis.confirmed_facts[{index}]", str(fact))


def render_sources(sources: list[Any], allow_multiple: bool) -> str:
    if not allow_multiple and len(sources) > MAX_SOURCE_LINKS:
        fail(f"sources must be narrowed to {MAX_SOURCE_LINKS} links or fewer")
    links = []
    for item in sources:
        if not isinstance(item, dict):
            fail("sources entries must be objects with label and url")
        label = required_str(item, "label")
        url = required_str(item, "url")
        if not url.startswith(("https://", "http://")):
            fail(f"source url must be absolute http(s): {url}")
        links.append(f'        <a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>')
    return "\n".join(links)


def render_information_basis(summary: str, basis: dict[str, Any]) -> str:
    what_changed = html.escape(required_str(basis, "what_changed"))
    why_it_matters = html.escape(required_str(basis, "why_it_matters"))
    limits = html.escape(required_str(basis, "limits_or_unknowns"))
    facts = [
        f"        <li>{html.escape(str(fact).strip())}</li>"
        for fact in required_list(basis, "confirmed_facts")
        if str(fact).strip()
    ]
    dates = "、".join(html.escape(str(date).strip()) for date in required_list(basis, "source_dates") if str(date).strip())
    return f"""      <h2>要点と背景</h2>
      <div class="article-summary">
        <p>{html.escape(summary)}</p>
        <p>{what_changed}</p>
        <p>{why_it_matters}</p>
        <p class="source-dates">確認日付: {dates}</p>
      </div>

      <h2>確認した事実</h2>
      <ul class="fact-list">
{chr(10).join(facts)}
      </ul>

      <h2>未確定点</h2>
      <p class="limits">{limits}</p>"""


def render(data: dict[str, Any]) -> str:
    issue_date = required_str(data, "issue_date")
    section_id = required_str(data, "section_id")
    kicker = required_str(data, "kicker")
    title = required_str(data, "title")
    h1 = required_str(data, "h1")
    sources = required_list(data, "sources")
    if data.get("body_paragraphs"):
        fail("body_paragraphs are not supported; integrate reader-facing facts into the article summary")
    summary = required_str(data, "summary")

    for label, text in [
        ("title", title),
        ("h1", h1),
        ("summary", summary),
    ]:
        reject_forbidden(label, text)

    use_article_summary = article_summary_required(issue_date)
    source_links = render_sources(sources, allow_multiple=use_article_summary)
    escaped_title = html.escape(title)
    escaped_kicker = html.escape(kicker)
    escaped_h1 = html.escape(h1)
    if detail_information_contract_required(issue_date):
        basis = required_summary_basis(data)
        reject_basis_forbidden(basis)
        summary_block = render_information_basis(summary, basis)
    else:
        min_summary_chars = minimum_summary_chars(issue_date)
        if len(summary.replace(" ", "").replace("\n", "")) < min_summary_chars:
            fail(f"summary is too thin: {len(summary)} chars")
        heading = html.escape(summary_heading(issue_date))
        if use_article_summary:
            summary_block = f"""      <h2>{heading}</h2>
      <div class="article-summary">{html.escape(summary)}</div>"""
        else:
            summary_block = f"""      <h2>{heading}</h2>
      <div class="summary-lead">{html.escape(summary)}</div>"""
    escaped_issue = html.escape(issue_date, quote=True)
    escaped_section = html.escape(section_id, quote=True)

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title} | NIGHT SIGNAL</title>
  <link rel="stylesheet" href="_style.css">
</head>
<body>
  <main>
    <a class="back" href="../night-brief-web-sample-{escaped_issue}.html#{escaped_section}">一覧へ戻る</a>
    <article class="article">
      <div class="kicker">{escaped_kicker}</div>
      <h1>{escaped_h1}</h1>

{summary_block}

      <div class="source">
        原文確認:
{source_links}
      </div>
      <div class="return-row"><a class="back" href="../night-brief-web-sample-{escaped_issue}.html#{escaped_section}">一覧へ戻る</a></div>
    </article>
  </main>
</body>
</html>
"""


def main() -> int:
    if len(sys.argv) != 2:
        fail("usage: render_detail.py path/to/detail.json")
    source = Path(sys.argv[1])
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail("input JSON must be an object")
    slug = required_str(data, "slug")
    if "/" in slug or not slug.endswith(".html"):
        fail("slug must be a detail html filename, e.g. openai-YYYY-MM-DD.html")
    output = DETAILS / slug
    output.write_text(render(data), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
