#!/usr/bin/env python3
"""Fail when the selected NIGHT SIGNAL issue is not today's JST issue."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
MARKER = ROOT / ".night-signal-issue-date"


def fail(message: str) -> None:
    print(f"CURRENT ISSUE AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_marker() -> str:
    if not MARKER.exists():
        fail("missing .night-signal-issue-date")
    issue_date = MARKER.read_text(encoding="utf-8").strip()
    try:
        datetime.strptime(issue_date, "%Y-%m-%d")
    except ValueError:
        fail(f"invalid .night-signal-issue-date: {issue_date}")
    return issue_date


def require(path: Path) -> None:
    if not path.exists():
        fail(f"missing current issue artifact: {path.relative_to(ROOT)}")


def main() -> int:
    expected = sys.argv[1] if len(sys.argv) > 1 else datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
    issue_date = read_marker()
    if issue_date != expected:
        fail(f"selected issue is {issue_date}, expected JST current issue {expected}")
    require(ROOT / f"night-brief-web-sample-{issue_date}.html")
    require(ROOT / "site" / issue_date / "index.html")
    require(ROOT / "site" / "index.html")
    print(f"CURRENT ISSUE AUDIT PASSED: {issue_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
