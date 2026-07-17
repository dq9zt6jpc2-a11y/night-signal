#!/usr/bin/env python3
"""Audit the live cloud owner boundary and classify one bounded recovery.

This audit is intentionally read-only.  It distinguishes static repository
readiness, Web-owner liveness, review completion, deterministic publication,
and verified public content.  A caller may use ``recoverable=true`` to dispatch
the existing reviewed-publication workflow once; this module never recollects
Evidence or performs model work.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OWNER_STATUS_BRANCH = "night-signal-owner-status"
OWNER_STATUS_CONTRACT = "night-signal-cloud-owner-status-v1"
OWNER_STATUS_OUTCOMES = {
    "feedback_success",
    "review_submitted",
    "evidence_missing",
    "review_retriggered",
    "correction_submitted",
    "recovery_exhausted",
}
DETERMINISTIC_FAILURE_STAGES = {
    "restore",
    "base_guard",
    "commit",
    "push",
    "pages",
    "pages_retry",
    "pages_watch",
    "verify",
}
EDITOR_CORRECTION_STAGES = {"apply", "gates"}
NETWORK_ERRORS = (
    "could not resolve host",
    "connection reset",
    "connection timed out",
    "error connecting to api.github.com",
    "check your internet connection",
    "temporary failure",
    "503 service unavailable",
)


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL OPERATIONAL AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def valid_issue_date(issue_date: str) -> bool:
    return bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}", issue_date))


def bounded_attempt(value: Any) -> int:
    try:
        return 1 if int(value) >= 1 else 0
    except (TypeError, ValueError):
        return 0


def transient_network_error(value: str) -> bool:
    return any(marker in value.casefold() for marker in NETWORK_ERRORS)


def classify_state(
    *,
    publication_verified: bool,
    evidence_ready: bool,
    review: dict[str, Any] | None,
    feedback: dict[str, Any] | None,
    owner_heartbeats: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    review_handoff = review.get("cloud_handoff", {}) if isinstance(review, dict) else {}
    review_attempt = bounded_attempt(
        review_handoff.get("recovery_attempt")
        if isinstance(review_handoff, dict)
        else 0
    )
    feedback_attempt = bounded_attempt(
        feedback.get("recovery_attempt") if isinstance(feedback, dict) else 0
    )
    recovery_attempt = max(review_attempt, feedback_attempt)
    heartbeat_roles = sorted(owner_heartbeats)
    activation_proven = bool(heartbeat_roles) or bool(
        isinstance(review_handoff, dict)
        and review_handoff.get("execution_surface") == "chatgpt-web-scheduled-task"
    )
    base = {
        "published": publication_verified,
        "evidence_ready": evidence_ready,
        "review_ready": isinstance(review, dict),
        "feedback_ready": isinstance(feedback, dict),
        "activation_proven_today": activation_proven,
        "owner_heartbeat_roles": heartbeat_roles,
        "owner_heartbeat_outcomes": {
            role: str(value.get("outcome", ""))
            for role, value in owner_heartbeats.items()
        },
        "recovery_attempt": recovery_attempt,
        "recoverable": False,
        "needs_editor_action": False,
        "additional_paid_api_requests": 0,
    }
    if publication_verified:
        return {**base, "stage": "published_verified", "reason": ""}
    if not evidence_ready and not isinstance(review, dict):
        return {
            **base,
            "stage": "evidence_missing",
            "reason": "final Evidence handoff is missing; do not start model review",
        }
    if not isinstance(review, dict):
        if heartbeat_roles:
            return {
                **base,
                "stage": "review_missing_after_owner_heartbeat",
                "reason": "Web owner ran but did not produce a review; inspect its recorded outcome",
                "needs_editor_action": True,
            }
        return {
            **base,
            "stage": "review_missing_owner_heartbeat_missing",
            "reason": (
                "no current Web-owner heartbeat or review; the Scheduled task may be "
                "unconfigured, paused, or missing GitHub permission"
            ),
            "needs_editor_action": True,
        }
    if not isinstance(feedback, dict):
        return {
            **base,
            "stage": "review_ready_publication_missing",
            "reason": "review exists but no publication feedback was recorded",
            "recoverable": recovery_attempt == 0,
        }
    failed_stage = str(feedback.get("failed_stage") or "")
    feedback_status = str(feedback.get("status") or "")
    if feedback_status == "success":
        return {
            **base,
            "stage": "publication_verification_mismatch",
            "reason": "workflow reported success but the final public audit does not pass",
            "recoverable": recovery_attempt == 0,
        }
    if failed_stage in EDITOR_CORRECTION_STAGES:
        return {
            **base,
            "stage": "review_correction_required",
            "reason": f"review validator failed at {failed_stage}; correct only rejected events",
            "needs_editor_action": True,
        }
    if failed_stage in DETERMINISTIC_FAILURE_STAGES:
        if recovery_attempt == 0:
            return {
                **base,
                "stage": "deterministic_recovery_required",
                "reason": f"reuse the same review after {failed_stage}",
                "recoverable": True,
            }
        return {
            **base,
            "stage": "deterministic_recovery_exhausted",
            "reason": f"the one bounded recovery already failed at {failed_stage}",
        }
    return {
        **base,
        "stage": "unclassified_publication_failure",
        "reason": f"publication feedback has an unsupported failed stage: {failed_stage or 'unknown'}",
    }


def run_gh(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(2):
        result = subprocess.run(
            ["gh", *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            return result
        error = f"{result.stdout}\n{result.stderr}"
        if attempt == 0 and transient_network_error(error):
            time.sleep(2)
            continue
        break
    assert result is not None
    if check:
        fail(f"gh {' '.join(arguments)}: {result.stderr.strip() or result.stdout.strip()}")
    return result


def remote_json(repository: str, branch: str, path: str) -> dict[str, Any] | None:
    endpoint = f"repos/{repository}/contents/{path}?ref={branch}"
    result = run_gh(["api", endpoint], check=False)
    if result.returncode != 0:
        error = f"{result.stdout}\n{result.stderr}".casefold()
        if "404" in error or "not found" in error or "no commit found" in error:
            return None
        fail(f"cannot inspect {branch}:{path}: {result.stderr.strip() or result.stdout.strip()}")
    try:
        envelope = json.loads(result.stdout)
        raw = base64.b64decode(str(envelope["content"]).replace("\n", ""))
        value = json.loads(raw)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        fail(f"invalid JSON envelope at {branch}:{path}: {exc}")
    if not isinstance(value, dict):
        fail(f"remote JSON root must be an object: {branch}:{path}")
    return value


def valid_owner_heartbeat(
    value: dict[str, Any] | None,
    *,
    issue_date: str,
    role: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if (
        value.get("contract") != OWNER_STATUS_CONTRACT
        or value.get("issue_date") != issue_date
        or value.get("role") != role
        or not isinstance(value.get("checked_at"), str)
        or value.get("outcome") not in OWNER_STATUS_OUTCOMES
    ):
        return None
    try:
        checked_at = datetime.fromisoformat(str(value["checked_at"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    if checked_at.tzinfo is None:
        return None
    return value


def publication_audit(issue_date: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "scripts/publication_audit.py", issue_date],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    output = "\n".join(value for value in (result.stdout.strip(), result.stderr.strip()) if value)
    return result.returncode == 0, output[-4000:]


def write_github_output(path: Path, result: dict[str, Any]) -> None:
    values = {
        "stage": result["stage"],
        "published": str(bool(result["published"])).lower(),
        "recoverable": str(bool(result["recoverable"])).lower(),
        "needs_editor_action": str(bool(result["needs_editor_action"])).lower(),
        "activation_proven_today": str(bool(result["activation_proven_today"])).lower(),
        "recovery_attempt": str(result["recovery_attempt"]),
    }
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def audit(issue_date: str, repository: str) -> dict[str, Any]:
    publication_verified, publication_output = publication_audit(issue_date)
    owner_heartbeats: dict[str, dict[str, Any]] = {}
    for role in ("primary", "recovery"):
        heartbeat = valid_owner_heartbeat(
            remote_json(
                repository,
                OWNER_STATUS_BRANCH,
                f"cloud-owner/{role}.json",
            ),
            issue_date=issue_date,
            role=role,
        )
        if heartbeat is not None:
            owner_heartbeats[role] = heartbeat
    if publication_verified:
        result = classify_state(
            publication_verified=True,
            evidence_ready=False,
            review=None,
            feedback=None,
            owner_heartbeats=owner_heartbeats,
        )
        result.update(
            {
                "issue_date": issue_date,
                "repository": repository,
                "publication_audit_tail": publication_output,
            }
        )
        return result
    evidence = remote_json(
        repository,
        f"night-signal-evidence-{issue_date}",
        f"cloud-evidence/{issue_date}/manifest.json",
    )
    review = remote_json(
        repository,
        f"night-signal-review-{issue_date}",
        f"cloud-review/{issue_date}/editor_review.json",
    )
    feedback = remote_json(
        repository,
        f"night-signal-feedback-{issue_date}",
        f"cloud-feedback/{issue_date}/status.json",
    )
    result = classify_state(
        publication_verified=publication_verified,
        evidence_ready=isinstance(evidence, dict),
        review=review,
        feedback=feedback,
        owner_heartbeats=owner_heartbeats,
    )
    result.update(
        {
            "issue_date": issue_date,
            "repository": repository,
            "publication_audit_tail": publication_output,
        }
    )
    return result


def self_test() -> None:
    if not transient_network_error(
        "error connecting to api.github.com; check your internet connection"
    ):
        fail("GitHub CLI connection failures are not retried once")
    missing = classify_state(
        publication_verified=False,
        evidence_ready=True,
        review=None,
        feedback=None,
        owner_heartbeats={},
    )
    if missing["stage"] != "review_missing_owner_heartbeat_missing":
        fail("missing Web owner was not classified")
    ready = classify_state(
        publication_verified=False,
        evidence_ready=True,
        review={
            "cloud_handoff": {
                "execution_surface": "chatgpt-web-scheduled-task",
                "recovery_attempt": 0,
            }
        },
        feedback=None,
        owner_heartbeats={},
    )
    if ready["stage"] != "review_ready_publication_missing" or not ready["recoverable"]:
        fail("missing review trigger was not recoverable")
    exhausted = classify_state(
        publication_verified=False,
        evidence_ready=True,
        review={"cloud_handoff": {"recovery_attempt": 1}},
        feedback={"status": "failed", "failed_stage": "pages", "recovery_attempt": 1},
        owner_heartbeats={},
    )
    if exhausted["stage"] != "deterministic_recovery_exhausted" or exhausted["recoverable"]:
        fail("bounded recovery exhaustion was not enforced")
    correction = classify_state(
        publication_verified=False,
        evidence_ready=True,
        review={"cloud_handoff": {}},
        feedback={"status": "failed", "failed_stage": "apply"},
        owner_heartbeats={},
    )
    if correction["stage"] != "review_correction_required" or not correction["needs_editor_action"]:
        fail("review correction was mistaken for deterministic recovery")
    published = classify_state(
        publication_verified=True,
        evidence_ready=False,
        review=None,
        feedback=None,
        owner_heartbeats={},
    )
    if published["stage"] != "published_verified":
        fail("verified publication did not short-circuit")
    published_with_activation = classify_state(
        publication_verified=True,
        evidence_ready=False,
        review=None,
        feedback=None,
        owner_heartbeats={
            "primary": {
                "outcome": "review_submitted",
            }
        },
    )
    if not published_with_activation["activation_proven_today"]:
        fail("published state discarded current Web-owner activation proof")
    print("NIGHT SIGNAL OPERATIONAL AUDIT SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default="")
    parser.add_argument(
        "--repository",
        default=os.getenv("GITHUB_REPOSITORY", "dq9zt6jpc2-a11y/night-signal"),
    )
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not valid_issue_date(args.issue_date):
        fail("issue_date must use YYYY-MM-DD")
    result = audit(args.issue_date, args.repository)
    if args.github_output:
        write_github_output(args.github_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not args.report_only and not result["published"]:
        fail(f"{result['stage']}: {result['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
