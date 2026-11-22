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


def read_rejected_requests(path: Path) -> list[dict[str, Any]]:
    # The final JSON can exceed the display log tail. Parse the complete log.
    marker = "review responses failed deterministic validation: "
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                _, separator, payload = line.partition(marker)
                if not separator:
                    continue
                try:
                    value = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and isinstance(value.get("rejected_requests"), list):
                    return [item for item in value["rejected_requests"] if isinstance(item, dict)]
    except OSError:
        pass
    return []


def read_recall_risk_categories(path: Path | None) -> list[str]:
    if path is None:
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return list(
        dict.fromkeys(
            str(category)
            for category in value.get("recall_risk_categories", [])
            if str(category)
        )
    )


def reader_verification(log: Path, issue_date: str) -> dict[str, Any] | None:
    if not log.is_file():
        return None
    for line in reversed(log.read_text(encoding="utf-8").splitlines()):
        if not line.startswith("{"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(entry, dict)
            and entry.get("issue_date") == issue_date
            and isinstance(entry.get("confirmed_at"), str)
            and isinstance(entry.get("verified_files_sha256"), dict)
            and entry["verified_files_sha256"]
        ):
            return entry
    return None


def build_feedback(
    issue_date: str,
    *,
    run_id: str,
    run_url: str,
    workflow_status: str,
    recovery_attempt: int,
    step_outcomes: dict[str, str],
    log_directory: Path,
    receipt_path: Path | None = None,
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
        "recovery_attempt": recovery_attempt,
        "status": "success" if workflow_status == "success" else "failed",
        "failed_stage": failed_stage,
        "first_reader_verification": (
            reader_verification(log_directory / "verify.log", issue_date)
            if step_outcomes.get("verify") == "success" else None
        ),
        "step_outcomes": step_outcomes,
        "validator_log_tail": log_tail,
        "rejected_requests": (
            read_rejected_requests(log_directory / "apply.log")
            if failed_stage == "apply" else []
        ),
        "recall_risk_categories": read_recall_risk_categories(receipt_path),
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
    contents_path = f"repos/{repository}/contents/{path}"
    for attempt in range(2):
        existing = run_gh(["api", f"{contents_path}?ref={branch}"], check=False)
        previous_sha = None
        payload = dict(feedback)
        if existing.returncode == 0:
            envelope = json.loads(existing.stdout)
            previous_sha = envelope["sha"]
            previous = json.loads(base64.b64decode(envelope["content"]))
            if previous.get("first_reader_verification"):
                payload["first_reader_verification"] = previous["first_reader_verification"]
        elif "HTTP 404" not in existing.stderr:
            fail("could not read prior cloud feedback")
        encoded = base64.b64encode(
            (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).decode("ascii")
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
        if previous_sha:
            arguments.extend(["-f", f"sha={previous_sha}"])
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
        rejected = [{"request_id": "test-request", "detail": "x" * (MAX_LOG_CHARS + 1)}]
        with (directory / "apply.log").open("a", encoding="utf-8") as stream:
            stream.write(
                "review responses failed deterministic validation: "
                + json.dumps({"rejected_requests": rejected})
                + "\nexact validator reason\n"
            )
        receipt_path = directory / "plus_review_receipt.json"
        receipt_path.write_text(
            json.dumps({"recall_risk_categories": ["OpenAI", "北米経済"]}),
            encoding="utf-8",
        )
        feedback = build_feedback(
            "2099-01-02",
            run_id="123",
            run_url="https://example.invalid/run/123",
            workflow_status="failure",
            recovery_attempt=1,
            step_outcomes={"apply": "failure", "gates": "skipped"},
            log_directory=directory,
            receipt_path=receipt_path,
        )
        if feedback["failed_stage"] != "apply":
            fail("failed stage was not preserved")
        if feedback["recovery_attempt"] != 1:
            fail("bounded recovery attempt was not preserved")
        if "exact validator reason" not in feedback["validator_log_tail"]:
            fail("validator failure detail was not preserved")
        if feedback["rejected_requests"] != rejected:
            fail("complete rejection details were lost after log truncation")
        if feedback["recall_risk_categories"] != ["OpenAI", "北米経済"]:
            fail("recall-risk categories were not preserved")
    print("NIGHT SIGNAL CLOUD FEEDBACK SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default="")
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument("--run-url", default="")
    parser.add_argument("--workflow-status", default="failure")
    parser.add_argument("--recovery-attempt", type=int, choices=(0, 1), default=0)
    parser.add_argument("--log-directory", type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument("--receipt-path", type=Path)
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
        recovery_attempt=args.recovery_attempt,
        step_outcomes=outcomes,
        log_directory=args.log_directory,
        receipt_path=args.receipt_path,
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
