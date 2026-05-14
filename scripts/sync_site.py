#!/usr/bin/env python3
"""Sync the working NIGHT SIGNAL files into the published site folder.

The working detail pages link back to the editable sample page. The published
site pages must link back to the dated issue index instead, otherwise Safari
opens a broken path from site/2026-05-10/details/.

The root site/index.html is the stable URL to bookmark. It always shows the
latest issue while dated folders keep the recent history.
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
RETENTION_DAYS = 7


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
    return html.replace('href="details/', f'href="{ISSUE_DATE}/details/')


def rewrite_issue_index_links(html: str) -> str:
    marker = '<a href="details/extraction-log-'
    if '<a href="../index.html">最新号</a>' not in html and marker in html:
        html = html.replace(marker, '<a href="../index.html">最新号</a>\n        ' + marker, 1)
    return html


def linked_detail_names(html: str) -> set[str]:
    names = {
        match.group(1)
        for match in re.finditer(r'href="(?:\d{4}-\d{2}-\d{2}/)?details/([^"#?]+\.html)', html)
    }
    names.add("policy.html")
    names.add(f"extraction-log-{ISSUE_DATE}.html")
    return names


def issue_dirs() -> list[Path]:
    dated = []
    for path in SITE_ROOT.iterdir():
        if not path.is_dir():
            continue
        try:
            datetime.strptime(path.name, "%Y-%m-%d")
        except ValueError:
            continue
        dated.append(path)
    return sorted(dated, reverse=True)


def prune_old_issues() -> None:
    current = datetime.strptime(ISSUE_DATE, "%Y-%m-%d").date()
    for path in issue_dirs():
        issue_date = datetime.strptime(path.name, "%Y-%m-%d").date()
        if (current - issue_date).days > RETENTION_DAYS:
            shutil.rmtree(path)


def archive_section() -> str:
    cards = []
    for path in issue_dirs():
        cards.append(
            f"""        <article class="card">
          <div class="meta"><span class="pill">履歴</span><span class="pill">{path.name}</span></div>
          <h3>{path.name}</h3>
          <p>直近1週間の履歴。後から読み返すための保存版です。</p>
          <a class="link" href="{path.name}/index.html">この日を開く</a>
        </article>"""
        )
    return f"""
    <section class="section" id="history">
      <div class="section-head"><h2>History</h2><p>直近7日分</p></div>
      <div class="cards">
{chr(10).join(cards)}
      </div>
    </section>
"""


def write_root_latest() -> None:
    html = rewrite_root_links(SAMPLE.read_text(encoding="utf-8"))
    html = html.replace('<a href="details/policy.html">方針</a>', f'<a href="{ISSUE_DATE}/details/policy.html">方針</a><a href="#history">履歴</a>')
    html = html.replace("  </main>\n</body>", f"{archive_section()}  </main>\n</body>")
    (SITE_ROOT / "index.html").write_text(html, encoding="utf-8")


def main() -> int:
    if not SAMPLE.exists():
        raise FileNotFoundError(f"Sample page not found: {SAMPLE}")
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    if SITE_ISSUE.exists():
        shutil.rmtree(SITE_ISSUE)
    SITE_DETAILS.mkdir(parents=True, exist_ok=True)
    sample_html = SAMPLE.read_text(encoding="utf-8")
    (SITE_ISSUE / "index.html").write_text(rewrite_issue_index_links(sample_html), encoding="utf-8")
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
    write_root_latest()
    print(SITE_ISSUE / "index.html")
    print(SITE_ROOT / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
