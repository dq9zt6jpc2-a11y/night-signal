#!/usr/bin/env python3
"""Verify that today's NIGHT SIGNAL is not just generated, but published.

This audit is stricter than pre22_audit.py. It is intended to run after
commit/push and fails when local work exists only on this machine.
"""

from __future__ import annotations

import subprocess
import sys
import re
import urllib.request
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = "https://dq9zt6jpc2-a11y.github.io/night-signal/"


def issue_date_from_args() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return datetime.now().strftime("%Y-%m-%d")


def latest_available_issue_date() -> str | None:
    dates = []
    for path in ROOT.glob("night-brief-web-sample-*.html"):
        match = re.fullmatch(r"night-brief-web-sample-(\d{4}-\d{2}-\d{2})\.html", path.name)
        if not match:
            continue
        dates.append(match.group(1))
    return max(dates) if dates else None


def fail(message: str) -> None:
    print(f"PUBLICATION AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        fail(f"{' '.join(args)} failed: {detail}")
    return result


def run_quality_gate(issue_date: str) -> None:
    result = run([sys.executable, str(ROOT / "scripts" / "quality_gate.py"), issue_date], check=False)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        fail(f"quality gate failed for {issue_date}")


def ensure_clean_worktree() -> None:
    status = run(["git", "status", "--porcelain"], check=True).stdout.strip()
    if status:
        fail("working tree has uncommitted changes; commit and push before publication success")


def ensure_pushed_to_origin() -> None:
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], check=True).stdout.strip()
    if branch == "HEAD":
        local_head = run(["git", "rev-parse", "HEAD"], check=True).stdout.strip()
        remote = run(["git", "ls-remote", "origin", "refs/heads/main"], check=True).stdout.strip().split()
        if not remote:
            fail("cannot find remote branch origin/main")
        remote_head = remote[0]
        if remote_head != local_head:
            fail(f"remote origin/main is {remote_head[:12]}, local HEAD is {local_head[:12]}")
        return

    upstream = run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=True).stdout.strip()
    ahead_behind = run(["git", "rev-list", "--left-right", "--count", f"{upstream}...HEAD"], check=True).stdout.split()
    behind = int(ahead_behind[0])
    ahead = int(ahead_behind[1])
    if ahead:
        fail(f"local branch {branch} is ahead of {upstream} by {ahead} commit(s); push did not complete")
    if behind:
        fail(f"local branch {branch} is behind {upstream} by {behind} commit(s); pull/rebase before publishing")

    local_head = run(["git", "rev-parse", "HEAD"], check=True).stdout.strip()
    remote = run(["git", "ls-remote", "origin", f"refs/heads/{branch}"], check=True).stdout.strip().split()
    if not remote:
        fail(f"cannot find remote branch origin/{branch}")
    remote_head = remote[0]
    if remote_head != local_head:
        fail(f"remote origin/{branch} is {remote_head[:12]}, local HEAD is {local_head[:12]}")


def read_public(url: str) -> str:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "night-signal-publication-audit"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - audit must surface network failures plainly.
        fail(f"cannot read public URL {url}: {exc}")


def read_local(path: Path) -> str:
    if not path.exists():
        fail(f"missing local file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def visible_text(html: str) -> str:
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def local_card_titles(issue_date: str) -> list[str]:
    html = read_local(ROOT / "site" / "index.html")
    body = html.split('<section class="section" id="history">', 1)[0]
    titles = []
    for match in re.finditer(r"<h3>(.*?)</h3>", body, flags=re.S):
        title = visible_text(match.group(1))
        if title and title not in titles:
            titles.append(title)
    if not titles:
        fail(f"local site/index.html has no card titles for {issue_date}")
    return titles


def ensure_public_url(issue_date: str) -> None:
    root_html = read_public(PUBLIC_ROOT)
    dated_html = read_public(f"{PUBLIC_ROOT}{issue_date}/index.html")
    expected = f"NIGHT SIGNAL | {issue_date}"
    display = issue_date.replace("-", ".")
    if expected not in root_html or display not in root_html:
        fail(f"public root does not show {issue_date}")
    if expected not in dated_html:
        fail(f"public dated issue does not show {issue_date}")

    missing_titles = [title for title in local_card_titles(issue_date) if title not in root_html]
    if missing_titles:
        fail("public root date is current but content is stale; missing local titles: " + "; ".join(missing_titles))


def main() -> int:
    issue_date = issue_date_from_args()
    latest_issue = latest_available_issue_date()
    if latest_issue and issue_date != latest_issue:
        fail(f"{issue_date} is not the latest local issue; latest is {latest_issue}")
    run_quality_gate(issue_date)
    ensure_clean_worktree()
    ensure_pushed_to_origin()
    ensure_public_url(issue_date)
    print(f"PUBLICATION AUDIT PASSED: {issue_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
