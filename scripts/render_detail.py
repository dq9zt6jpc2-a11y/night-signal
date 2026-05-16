#!/usr/bin/env python3
"""Render a NIGHT SIGNAL detail page from structured content.

This is the preferred creation path for detail pages. It intentionally exposes
only the reader-facing sections we want to publish:

- 30秒概要
- 本文
- 原文確認

Authoring checklist sections such as "チェック観点" or "次の確認" is not
supported here, so they are not created in the first place.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "details"
MIN_SUMMARY_CHARS = 180
FORBIDDEN_TEXT = [
    "チェック観点",
    "次の確認",
    "次の予定",
    "読むポイント",
    "今回の要点",
    "一次で押さえる点",
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


def reject_forbidden(label: str, text: str) -> None:
    found = [term for term in FORBIDDEN_TEXT if term in text]
    if found:
        fail(f"{label} contains authoring/checklist wording: {', '.join(found)}")


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


def render(data: dict[str, Any]) -> str:
    issue_date = required_str(data, "issue_date")
    section_id = required_str(data, "section_id")
    kicker = required_str(data, "kicker")
    title = required_str(data, "title")
    h1 = required_str(data, "h1")
    summary = required_str(data, "summary")
    paragraphs = [str(value).strip() for value in required_list(data, "body_paragraphs")]
    sources = required_list(data, "sources")

    for label, text in [
        ("title", title),
        ("h1", h1),
        ("summary", summary),
        ("body", "\n".join(paragraphs)),
    ]:
        reject_forbidden(label, text)

    if len(summary.replace(" ", "").replace("\n", "")) < MIN_SUMMARY_CHARS:
        fail(f"summary is too thin: {len(summary)} chars")
    if any(not paragraph for paragraph in paragraphs):
        fail("body_paragraphs must not contain empty paragraphs")

    body = "\n".join(f"      <p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)
    source_links = render_sources(sources)
    escaped_title = html.escape(title)
    escaped_kicker = html.escape(kicker)
    escaped_h1 = html.escape(h1)
    escaped_summary = html.escape(summary)
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

      <h2>30秒概要</h2>
      <div class="summary-lead">{escaped_summary}</div>

      <h2>本文</h2>
{body}

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
