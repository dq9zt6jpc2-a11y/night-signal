#!/usr/bin/env python3
"""Pre-22:00 audit for NIGHT SIGNAL daily generation.

This is intentionally narrower than the research job. It answers one question:
is today's issue actually present, synced, and good enough to publish?
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def issue_date_from_args() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return datetime.now().strftime("%Y-%m-%d")


def fail(message: str) -> None:
    print(f"PRE22 AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_file(path: Path) -> None:
    if not path.exists():
        fail(f"missing required file: {path.relative_to(ROOT)}")


def run_quality_gate(issue_date: str) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "quality_gate.py"), issue_date],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        fail(f"quality gate failed for {issue_date}")


def main() -> int:
    issue_date = issue_date_from_args()
    require_file(ROOT / f"night-brief-web-sample-{issue_date}.html")
    require_file(ROOT / "details" / f"extraction-log-{issue_date}.html")
    require_file(ROOT / "site" / issue_date / "index.html")
    require_file(ROOT / "site" / "index.html")
    run_quality_gate(issue_date)
    print(f"PRE22 AUDIT PASSED: {issue_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
