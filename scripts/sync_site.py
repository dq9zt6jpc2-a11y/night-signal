#!/usr/bin/env python3
"""Sync the working NIGHT SIGNAL files into the published site folder.

The working detail pages link back to the editable sample page. The published
site pages must link back to the dated issue index.

The root site/index.html is the stable URL to bookmark. It always shows the
latest issue; the latest issue plus three prior issues remain readable.
"""

from __future__ import annotations

import shutil
import sys
import re
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "details"
SITE_ROOT = ROOT / "site"
ARCHIVED_PREVIOUS_ISSUES = 3


def detect_issue_date() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]

    # Default to today's issue date. Falling back to the newest existing sample
    # hides failed daily generation by republishing yesterday's page.
    return datetime.now().strftime("%Y-%m-%d")


ISSUE_DATE = detect_issue_date()
SAMPLE = ROOT / f"night-brief-web-sample-{ISSUE_DATE}.html"
SITE_ISSUE = SITE_ROOT / ISSUE_DATE
SITE_DETAILS = SITE_ISSUE / "details"


def rewrite_detail_links(html: str) -> str:
    # Working detail pages link back to the local editable sample HTML.
    # Published detail pages must link back to the dated issue index.html.
    #
    # Detail pages can contain hard-coded sample dates (e.g. when copied from a
    # previous day). Rewrite *any* night-brief-web-sample-YYYY-MM-DD.html link
    # to ../index.html while preserving fragments such as #openai.
    return re.sub(r"\.\./night-brief-web-sample-\d{4}-\d{2}-\d{2}\.html", "../index.html", html)


def rewrite_root_links(html: str) -> str:
    # Dated issue navigation may contain a link back to the stable root URL.
    # It must not survive when that same HTML is promoted to site/index.html.
    html = re.sub(r'\n\s*<a href="\.\./index\.html">最新号</a>', "", html)
    html = re.sub(r'href="\.\./(20\d{2}-\d{2}-\d{2}/details/)', r'href="\1', html)
    html = html.replace('href="../archive.html"', 'href="archive.html"')
    return html.replace('href="details/', f'href="{ISSUE_DATE}/details/')


def ensure_archive_link(html: str, href: str = "../archive.html") -> str:
    """Add archive navigation to legacy retained pages without duplicating it."""
    if re.search(r'href="(?:\.\./)?archive\.html"', html):
        return html
    policy_link = '<a href="details/policy.html">方針</a>'
    return html.replace(
        policy_link,
        f'<a href="{href}">アーカイブ</a>{policy_link}',
        1,
    )


def linked_detail_names(html: str) -> set[str]:
    names = {
        match.group(1)
        for match in re.finditer(r'href="(?:\d{4}-\d{2}-\d{2}/)?details/([^"#?]+\.html)', html)
    }
    names.add("policy.html")
    return names


def dated_samples() -> list[datetime.date]:
    dates = []
    for path in ROOT.glob("night-brief-web-sample-*.html"):
        match = re.fullmatch(r"night-brief-web-sample-(\d{4}-\d{2}-\d{2})\.html", path.name)
        if not match:
            continue
        dates.append(datetime.strptime(match.group(1), "%Y-%m-%d").date())
    return dates


def ensure_issue_is_latest() -> None:
    issue_date = datetime.strptime(ISSUE_DATE, "%Y-%m-%d").date()
    known_dates = dated_samples()
    latest = max(known_dates) if known_dates else issue_date
    if issue_date < latest:
        raise SystemExit(
            f"Refusing to publish {ISSUE_DATE} as site/index.html because newer issue {latest} exists. "
            f"Run scripts/sync_site.py {latest} for the fixed latest URL."
        )


def prune_old_issues() -> None:
    dated_directories: list[tuple[datetime.date, Path]] = []
    for path in SITE_ROOT.iterdir():
        if not path.is_dir():
            continue
        try:
            parsed = datetime.strptime(path.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        dated_directories.append((parsed, path))
    retained = {
        path
        for _, path in sorted(dated_directories, reverse=True)[
            : ARCHIVED_PREVIOUS_ISSUES + 1
        ]
    }
    for _, path in dated_directories:
        if path not in retained:
            shutil.rmtree(path)


def update_retained_archive_links() -> None:
    for issue_index in SITE_ROOT.glob("20??-??-??/index.html"):
        html = issue_index.read_text(encoding="utf-8")
        updated = ensure_archive_link(html)
        if updated != html:
            issue_index.write_text(updated, encoding="utf-8")


def write_archive_index() -> None:
    issues = sorted(
        (
            path.name
            for path in SITE_ROOT.iterdir()
            if path.is_dir()
            and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", path.name)
            and (path / "index.html").exists()
        ),
        reverse=True,
    )
    links = "\n".join(
        f'      <li><a href="{issue_date}/index.html">{issue_date}</a>'
        f'{" <span>最新号</span>" if issue_date == ISSUE_DATE else ""}</li>'
        for issue_date in issues
    )
    previous_count = max(0, len(issues) - 1)
    archive_copy = (
        f"最新号と過去{previous_count}号を確認できます。"
        if previous_count
        else "この号から履歴保存を開始し、今後は過去3号まで確認できます。"
    )
    html = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NIGHT SIGNAL | アーカイブ</title>
  <style>
    body {{ margin:0; background:#eef1f4; color:#0b1118; font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic","Segoe UI",sans-serif; }}
    main {{ max-width:760px; margin:0 auto; padding:48px 22px; }}
    a {{ color:#1f5eff; font-weight:800; text-decoration:none; }}
    h1 {{ margin:0 0 8px; font-size:36px; }} p {{ color:#687386; }}
    ul {{ list-style:none; padding:0; margin:28px 0; display:grid; gap:12px; }}
    li {{ background:#fff; border:1px solid #d8dee7; border-radius:10px; padding:18px; display:flex; justify-content:space-between; }}
    span {{ color:#087b73; font-size:12px; font-weight:900; }}
  </style>
</head>
<body><main>
  <p><a href="index.html">← 最新号へ</a></p>
  <h1>アーカイブ</h1>
  <p>{archive_copy}</p>
  <ul>
{links}
  </ul>
</main></body>
</html>
"""
    (SITE_ROOT / "archive.html").write_text(html, encoding="utf-8")


def write_root_latest(sample_html: str) -> None:
    html = rewrite_root_links(sample_html)
    html = html.replace(
        '<a href="details/policy.html">方針</a>',
        f'<a href="{ISSUE_DATE}/details/policy.html">方針</a>',
    )
    (SITE_ROOT / "index.html").write_text(html, encoding="utf-8")


def main() -> int:
    if not SAMPLE.exists():
        raise FileNotFoundError(f"Sample page not found: {SAMPLE}")
    ensure_issue_is_latest()
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    if SITE_ISSUE.exists():
        shutil.rmtree(SITE_ISSUE)
    SITE_DETAILS.mkdir(parents=True, exist_ok=True)
    sample_html = ensure_archive_link(SAMPLE.read_text(encoding="utf-8"))
    (SITE_ISSUE / "index.html").write_text(sample_html, encoding="utf-8")
    for name in sorted(linked_detail_names(sample_html)):
        source = DETAILS / name
        if not source.exists():
            raise FileNotFoundError(f"Linked detail page not found: {source}")
        target = SITE_DETAILS / name
        target.write_text(rewrite_detail_links(source.read_text(encoding="utf-8")), encoding="utf-8")
    stylesheet = DETAILS / "_style.css"
    if stylesheet.exists():
        shutil.copyfile(stylesheet, SITE_DETAILS / stylesheet.name)
    prune_old_issues()
    update_retained_archive_links()
    write_root_latest(sample_html)
    write_archive_index()
    print(SITE_ISSUE / "index.html")
    print(SITE_ROOT / "index.html")
    print(SITE_ROOT / "archive.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
