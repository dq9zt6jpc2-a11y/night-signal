#!/usr/bin/env python3
"""Render a NIGHT SIGNAL detail page from structured content.

This is the preferred creation path for detail pages. New issues expose only
the reader-facing sections we want to publish: one overview and direct sources.

Current issues use a compact information structure, not a time-boxed overview.
Authoring checklist sections are never published.
"""

from __future__ import annotations

import html
import re
from typing import Any

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
    what_changed = basis.get("what_changed")
    if what_changed is not None and (
        not isinstance(what_changed, str) or not what_changed.strip()
    ):
        fail("summary_basis.what_changed must be omitted or non-empty")
    why_it_matters = basis.get("why_it_matters")
    if why_it_matters is not None and (
        not isinstance(why_it_matters, str) or not why_it_matters.strip()
    ):
        fail("summary_basis.why_it_matters must be omitted or non-empty")
    limits = basis.get("limits_or_unknowns")
    if limits is not None and (not isinstance(limits, str) or not limits.strip()):
        fail("summary_basis.limits_or_unknowns must be omitted or non-empty")
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
    what_changed = basis.get("what_changed")
    if isinstance(what_changed, str) and what_changed.strip():
        reject_forbidden("summary_basis.what_changed", what_changed.strip())
    why_it_matters = basis.get("why_it_matters")
    if isinstance(why_it_matters, str) and why_it_matters.strip():
        reject_forbidden("summary_basis.why_it_matters", why_it_matters.strip())
    limits = basis.get("limits_or_unknowns")
    if isinstance(limits, str) and limits.strip():
        reject_forbidden("summary_basis.limits_or_unknowns", limits.strip())
    for index, fact in enumerate(required_list(basis, "confirmed_facts"), start=1):
        reject_forbidden(f"summary_basis.confirmed_facts[{index}]", str(fact))


def render_sources(sources: list[Any]) -> str:
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
    required_list(basis, "source_dates")
    return f"""      <h2>概要</h2>
      <div class="article-summary">
        <p>{html.escape(summary)}</p>
      </div>"""


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

    source_links = render_sources(sources)
    escaped_title = html.escape(title)
    escaped_kicker = html.escape(kicker)
    escaped_h1 = html.escape(h1)
    basis = required_summary_basis(data)
    reject_basis_forbidden(basis)
    summary_block = render_information_basis(summary, basis)
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
