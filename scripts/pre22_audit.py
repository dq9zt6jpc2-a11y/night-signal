#!/usr/bin/env python3
"""Pre-publication audit for NIGHT SIGNAL daily generation.

This is intentionally narrower than the research job. It answers one question:
is today's issue actually present, synced, and good enough to publish?
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"


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


def run_generation_if_state_exists(issue_date: str) -> None:
    state_issue = STATE_ROOT / issue_date / "issue.json"
    state_dir = STATE_ROOT / issue_date
    if not state_dir.exists():
        return
    commands = []
    collection_plan = state_dir / "collection_plan.json"
    if not collection_plan.exists():
        commands.append([sys.executable, str(ROOT / "scripts" / "night_signal_state.py"), "--write-collection-plan", issue_date])
    state_inputs_exist = (
        ((state_dir / "observations.jsonl").exists() or (state_dir / "observations.json").exists())
        and ((state_dir / "candidates.jsonl").exists() or (state_dir / "candidates.json").exists())
        and ((state_dir / "decisions.jsonl").exists() or (state_dir / "decisions.json").exists())
        and ((state_dir / "cards.jsonl").exists() or (state_dir / "cards.json").exists())
        and (state_dir / "coverage_manifest.json").exists()
    )
    if not state_issue.exists():
        if not state_inputs_exist:
            return
        commands.append([sys.executable, str(ROOT / "scripts" / "night_signal_state.py"), "--assemble-issue-state", issue_date])
    commands.extend(
        [
            [sys.executable, str(ROOT / "scripts" / "night_signal_state.py"), "--validate-issue", str(state_issue)],
            [sys.executable, str(ROOT / "scripts" / "night_signal_state.py"), "--generate-issue", str(state_issue)],
            [sys.executable, str(ROOT / "scripts" / "sync_site.py"), issue_date],
        ]
    )
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        if result.returncode != 0:
            fail("generation from state failed: " + " ".join(command))


def main() -> int:
    issue_date = issue_date_from_args()
    run_generation_if_state_exists(issue_date)
    require_file(ROOT / f"night-brief-web-sample-{issue_date}.html")
    require_file(ROOT / "details" / f"extraction-log-{issue_date}.html")
    require_file(ROOT / "site" / issue_date / "index.html")
    require_file(ROOT / "site" / "index.html")
    run_quality_gate(issue_date)
    print(f"PRE22 AUDIT PASSED: {issue_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
