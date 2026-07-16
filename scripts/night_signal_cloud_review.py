#!/usr/bin/env python3
"""Validate a PC-independent ChatGPT Web review handoff before publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
BRANCH_PREFIX = "night-signal-review-"
REVIEW_CONTRACT = "codex-plus-editor-v1"
EXECUTION_SURFACE = "chatgpt-web-scheduled-task"
MAX_REVIEW_BYTES = 4_000_000
JST = ZoneInfo("Asia/Tokyo")


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL CLOUD REVIEW FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_object(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        fail(f"cannot stat review file: {exc}")
    if size <= 0 or size > MAX_REVIEW_BYTES:
        fail(f"review file size is outside 1..{MAX_REVIEW_BYTES} bytes")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read review JSON: {exc}")
    if not isinstance(value, dict):
        fail("review JSON root must be an object")
    return value


def issue_date_from_ref(review_ref: str) -> str:
    if not review_ref.startswith(BRANCH_PREFIX):
        fail(f"review ref must start with {BRANCH_PREFIX}")
    issue_date = review_ref.removeprefix(BRANCH_PREFIX)
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", issue_date):
        fail("review ref must end with one ISO issue date")
    try:
        datetime.strptime(issue_date, "%Y-%m-%d")
    except ValueError:
        fail("review ref contains an invalid issue date")
    return issue_date


def evidence_sha256(evidence_path: Path) -> str:
    try:
        return hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    except OSError as exc:
        fail(f"cannot hash Evidence: {exc}")


def validate_review(
    review: dict[str, Any],
    *,
    issue_date: str,
    expected_evidence_sha256: str,
) -> None:
    if review.get("contract") != REVIEW_CONTRACT:
        fail(f"review contract must be {REVIEW_CONTRACT}")
    if review.get("issue_date") != issue_date:
        fail("review issue date does not match the review branch")
    if review.get("evidence_sha256") != expected_evidence_sha256:
        fail("review Evidence hash does not match the restored final artifact")
    responses = review.get("responses")
    if not isinstance(responses, list) or not responses:
        fail("review must contain at least one response")
    handoff = review.get("cloud_handoff")
    if not isinstance(handoff, dict):
        fail("review has no cloud_handoff provenance")
    if handoff.get("execution_surface") != EXECUTION_SURFACE:
        fail(f"cloud_handoff execution_surface must be {EXECUTION_SURFACE}")
    reviewed_at = handoff.get("reviewed_at")
    if not isinstance(reviewed_at, str):
        fail("cloud_handoff reviewed_at is required")
    try:
        reviewed = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError:
        fail("cloud_handoff reviewed_at must be an ISO timestamp")
    if reviewed.tzinfo is None:
        fail("cloud_handoff reviewed_at must include a timezone")
    reviewed_jst = reviewed.astimezone(JST)
    if reviewed_jst.date().isoformat() != issue_date:
        fail("cloud_handoff reviewed_at must be on the issue date in JST")


def install_review(
    issue_date: str,
    review_path: Path,
    evidence_path: Path,
    state_root: Path,
    *,
    review_ref: str,
) -> Path:
    ref_date = issue_date_from_ref(review_ref)
    if ref_date != issue_date:
        fail("review ref date and requested issue date differ")
    review = read_object(review_path)
    validate_review(
        review,
        issue_date=issue_date,
        expected_evidence_sha256=evidence_sha256(evidence_path),
    )
    destination = state_root / issue_date / "editor_review.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def self_test() -> None:
    issue_date = "2099-01-02"
    review_ref = f"{BRANCH_PREFIX}{issue_date}"
    if issue_date_from_ref(review_ref) != issue_date:
        fail("review ref date parsing failed")
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        evidence_path = root / "evidence.json"
        evidence_path.write_text('{"issue_date":"2099-01-02"}\n', encoding="utf-8")
        review = {
            "contract": REVIEW_CONTRACT,
            "issue_date": issue_date,
            "evidence_sha256": evidence_sha256(evidence_path),
            "cloud_handoff": {
                "execution_surface": EXECUTION_SURFACE,
                "reviewed_at": "2099-01-02T18:00:00+09:00",
            },
            "responses": [{"request_id": "r001", "response": {"events": []}}],
        }
        review_path = root / "review.json"
        review_path.write_text(json.dumps(review), encoding="utf-8")
        installed = install_review(
            issue_date,
            review_path,
            evidence_path,
            root / "state",
            review_ref=review_ref,
        )
        if not installed.exists():
            fail("valid cloud review was not installed")
        wrong_hash = {**review, "evidence_sha256": "0" * 64}
        review_path.write_text(json.dumps(wrong_hash), encoding="utf-8")
        try:
            install_review(
                issue_date,
                review_path,
                evidence_path,
                root / "state",
                review_ref=review_ref,
            )
        except SystemExit:
            pass
        else:
            fail("mismatched Evidence hash was accepted")
    print("NIGHT SIGNAL CLOUD REVIEW SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default="")
    parser.add_argument("--review-path", type=Path)
    parser.add_argument("--review-ref", default="")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.issue_date or not args.review_path or not args.review_ref:
        fail("issue_date, --review-path, and --review-ref are required")
    evidence_path = args.evidence or args.state_root / args.issue_date / "evidence.json"
    destination = install_review(
        args.issue_date,
        args.review_path,
        evidence_path,
        args.state_root,
        review_ref=args.review_ref,
    )
    print(
        json.dumps(
            {
                "issue_date": args.issue_date,
                "review_ref": args.review_ref,
                "installed_review": str(destination),
                "additional_paid_api_requests": 0,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
