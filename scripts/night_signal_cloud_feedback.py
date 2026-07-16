#!/usr/bin/env python3
"""Persist compact workflow feedback for the next PC-independent review heartbeat."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BRANCH_PREFIX = "night-signal-feedback-"
FEEDBACK_CONTRACT = "night-signal-cloud-feedback-v1"
MAX_LOG_CHARS = 12_000
NETWORK_ERRORS = (
    "could not resolve host",
    "connection reset",
    "connection timed out",
    "temporary failure",
)


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL CLOUD FEEDBACK FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate_issue_date(issue_date: str) -> None:
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", issue_date):
        fail("issue date must use YYYY-MM-DD")
    try:
        datetime.strptime(issue_date, "%Y-%m-%d")
    except ValueError:
        fail("issue date is invalid")


def read_tail(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-MAX_LOG_CHARS:]


def build_feedback(
    issue_date: str,
    *,
    run_id: str,
    run_url: str,
    workflow_status: str,
    step_outcomes: dict[str, str],
    log_directory: Path,
) -> dict[str, Any]:
    validate_issue_date(issue_date)
    failed_stage = next(
        (stage for stage, outcome in step_outcomes.items() if outcome == "failure"),
        None,
    )
    log_tail = read_tail(log_directory / f"{failed_stage}.log") if failed_stage else ""
    return {
        "contract": FEEDBACK_CONTRACT,
        "issue_date": issue_date,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "workflow_run_id": run_id,
        "workflow_run_url": run_url,
        "status": "success" if workflow_status == "success" else "failed",
        "failed_stage": failed_stage,
        "step_outcomes": step_outcomes,
        "validator_log_tail": log_tail,
        "recovery_contract": (
            "reuse the same Evidence; change only named rejected request/event entries"
        ),
    }


def run_gh(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(2):
        result = subprocess.run(
            ["gh", *arguments],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            return result
        error = f"{result.stdout}\n{result.stderr}".casefold()
        if attempt == 0 and any(marker in error for marker in NETWORK_ERRORS):
            time.sleep(2)
            continue
        break
    assert result is not None
    if check:
        fail(f"gh {' '.join(arguments)}: {result.stderr.strip() or result.stdout.strip()}")
    return result


def publish_feedback(issue_date: str, feedback: dict[str, Any]) -> dict[str, Any]:
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    if not repository:
        repository = run_gh(
            ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]
        ).stdout.strip()
    branch = f"{BRANCH_PREFIX}{issue_date}"
    path = f"cloud-feedback/{issue_date}/status.json"
    ref_path = f"repos/{repository}/git/ref/heads/{branch}"
    branch_result = run_gh(["api", ref_path], check=False)
    if branch_result.returncode != 0:
        main_sha = run_gh(
            ["api", f"repos/{repository}/git/ref/heads/main", "--jq", ".object.sha"]
        ).stdout.strip()
        created = run_gh(
            [
                "api",
                "--method",
                "POST",
                f"repos/{repository}/git/refs",
                "-f",
                f"ref=refs/heads/{branch}",
                "-f",
                f"sha={main_sha}",
            ],
            check=False,
        )
        if created.returncode != 0 and run_gh(["api", ref_path], check=False).returncode != 0:
            fail("could not create or find the cloud feedback branch")
    content = (
        json.dumps(feedback, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    encoded = base64.b64encode(content).decode("ascii")
    contents_path = f"repos/{repository}/contents/{path}"
    for attempt in range(2):
        existing = run_gh(
            ["api", f"{contents_path}?ref={branch}", "--jq", ".sha"],
            check=False,
        )
        arguments = [
            "api",
            "--method",
            "PUT",
            contents_path,
            "-f",
            f"message=Record NIGHT SIGNAL cloud status for {issue_date}",
            "-f",
            f"content={encoded}",
            "-f",
            f"branch={branch}",
        ]
        if existing.returncode == 0 and existing.stdout.strip():
            arguments.extend(["-f", f"sha={existing.stdout.strip()}"])
        updated = run_gh(arguments, check=False)
        if updated.returncode == 0:
            return {"branch": branch, "path": path, "published": True}
        if attempt == 0:
            continue
        fail(f"could not publish cloud feedback: {updated.stderr.strip()}")
    raise AssertionError("unreachable")


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        (directory / "apply.log").write_text("first\nexact validator reason\n", encoding="utf-8")
        feedback = build_feedback(
            "2099-01-02",
            run_id="123",
            run_url="https://example.invalid/run/123",
            workflow_status="failure",
            step_outcomes={"apply": "failure", "gates": "skipped"},
            log_directory=directory,
        )
        if feedback["failed_stage"] != "apply":
            fail("failed stage was not preserved")
        if "exact validator reason" not in feedback["validator_log_tail"]:
            fail("validator failure detail was not preserved")
    print("NIGHT SIGNAL CLOUD FEEDBACK SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default="")
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument("--run-url", default="")
    parser.add_argument("--workflow-status", default="failure")
    parser.add_argument("--log-directory", type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument("--step", action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.issue_date:
        fail("issue_date is required")
    outcomes: dict[str, str] = {}
    for raw in args.step:
        if "=" not in raw:
            fail("--step must use stage=outcome")
        stage, outcome = raw.split("=", 1)
        outcomes[stage] = outcome
    feedback = build_feedback(
        args.issue_date,
        run_id=args.run_id,
        run_url=args.run_url,
        workflow_status=args.workflow_status,
        step_outcomes=outcomes,
        log_directory=args.log_directory,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(feedback, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    result: dict[str, Any] = {"feedback": feedback}
    if args.publish:
        result["publication"] = publish_feedback(args.issue_date, feedback)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
