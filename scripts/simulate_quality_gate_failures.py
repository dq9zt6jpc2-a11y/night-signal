#!/usr/bin/env python3
"""Prove representative broken public issues fail the quality boundary."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def latest_issue_date() -> str:
    value = (ROOT / ".night-signal-issue-date").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise AssertionError("current issue marker is invalid")
    return value


def fixture() -> Path:
    temp = Path(tempfile.mkdtemp(prefix="night-signal-quality-"))
    shutil.copytree(ROOT / "scripts", temp / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "config", temp / "config")
    shutil.copytree(ROOT / "details", temp / "details")
    shutil.copytree(ROOT / "site", temp / "site")
    shutil.copytree(ROOT / "state", temp / "state")
    shutil.copyfile(ROOT / ".night-signal-issue-date", temp / ".night-signal-issue-date")
    for path in ROOT.glob("night-brief-web-sample-*.html"):
        shutil.copyfile(path, temp / path.name)
    return temp


def run_gate(temp: Path, issue_date: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/quality_gate.py", issue_date],
        cwd=temp,
        text=True,
        capture_output=True,
    )


def expect_pass(temp: Path, issue_date: str) -> None:
    result = run_gate(temp, issue_date)
    if result.returncode != 0:
        raise AssertionError(f"baseline failed\n{result.stdout}\n{result.stderr}")


def expect_fail(name: str, mutate) -> None:
    issue_date = latest_issue_date()
    temp = fixture()
    mutate(temp, issue_date)
    result = run_gate(temp, issue_date)
    if result.returncode == 0:
        raise AssertionError(f"{name}: broken issue passed")
    print(f"PASS expected quality failure: {name}")


def write(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")


def remove_current_detail(temp: Path, issue_date: str) -> None:
    html = (temp / "site" / issue_date / "index.html").read_text(encoding="utf-8")
    match = re.search(r'href="details/([^"#?]+\.html)"', html)
    if not match:
        raise AssertionError("current issue has no detail link")
    (temp / "site" / issue_date / "details" / match.group(1)).unlink()


def inject_internal_heading(temp: Path, issue_date: str) -> None:
    for path in (
        temp / f"night-brief-web-sample-{issue_date}.html",
        temp / "site" / "index.html",
        temp / "site" / issue_date / "index.html",
    ):
        html = path.read_text(encoding="utf-8")
        write(path, re.sub(r"<h3>.*?</h3>", "<h3>一次で固定した確認候補</h3>", html, count=1))


def mismatch_dated_page(temp: Path, issue_date: str) -> None:
    path = temp / "site" / issue_date / "index.html"
    write(path, path.read_text(encoding="utf-8").replace(issue_date, "1999-01-01"))


def remove_category(temp: Path, issue_date: str) -> None:
    for path in (
        temp / f"night-brief-web-sample-{issue_date}.html",
        temp / "site" / "index.html",
        temp / "site" / issue_date / "index.html",
    ):
        html = path.read_text(encoding="utf-8")
        write(
            path,
            re.sub(
                r'\n\s*<section class="section" id="openai">.*?(?=\n\s*<section class="section")',
                "",
                html,
                count=1,
                flags=re.S,
            ),
        )


def main() -> int:
    issue_date = latest_issue_date()
    expect_pass(fixture(), issue_date)
    print("PASS quality baseline")
    expect_fail("missing detail page", remove_current_detail)
    expect_fail("internal process heading", inject_internal_heading)
    expect_fail("dated page date mismatch", mismatch_dated_page)
    expect_fail("missing category section", remove_category)
    print("QUALITY FAILURE SIMULATIONS PASSED: 4 representative failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
