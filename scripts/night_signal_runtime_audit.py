#!/usr/bin/env python3
"""Classify NIGHT SIGNAL runtime failures and choose an honest recovery path."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import night_signal_evidence as evidence_store

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
JST = ZoneInfo("Asia/Tokyo")
STAGES = [
    "startup",
    "runtime_checked",
    "plan_written",
    "collection_complete",
    "story_build_complete",
    "render_complete",
    "local_gates_complete",
    "committed",
    "pushed",
    "public_verified",
]


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL RUNTIME AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def classify_failure(text: str) -> str:
    lower = text.lower()
    if (
        ('"has_credits":false' in lower and '"balance":"0"' in lower)
        or "usage limit" in lower
    ):
        return "codex_credit_exhausted"
    if any(term in lower for term in ("context_length_exceeded", "maximum context length", "max_output_tokens")):
        return "model_token_budget_exhausted"
    if "http 429" in lower or "rate_limit" in lower:
        return "rate_limited"
    if any(term in lower for term in ("background responses request timed out", "deadline exceeded", "command timed out")):
        return "execution_timeout"
    if any(term in lower for term in ("github_token is required", "http 401", "bad credentials")):
        return "authentication_unavailable"
    if any(
        term in lower
        for term in (
            "could not resolve host",
            "temporary failure in name resolution",
            "network is unreachable",
            "timed out",
        )
    ):
        if "github.com" in lower or "github.io" in lower or "github pages" in lower:
            return "github_unavailable"
        return "network_unavailable"
    if "working tree has uncommitted changes" in lower or "dirty worktree" in lower:
        return "dirty_worktree"
    if (
        '"last_agent_message":null' in lower
        or '"status":"in_progress"' in lower
        or "background responses request timed out" in lower
    ):
        return "partial_execution"
    return "unknown"


def manifest_state(issue_date: str, state_root: Path, now: datetime) -> dict[str, Any]:
    path = state_root / issue_date / "issue.json"
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "fresh_evening_issue": False,
    }
    if not path.exists():
        return result
    try:
        issue = json.loads(path.read_text(encoding="utf-8"))
        manifest = issue.get("coverage_manifest", {})
        if not isinstance(manifest, dict):
            return {**result, "error": "issue coverage_manifest is missing"}
        completed_value = manifest.get("collection_completed_at_jst")
        if not isinstance(completed_value, str) or not completed_value.strip():
            return {**result, "error": "collection_completed_at_jst is missing"}
        completed = datetime.fromisoformat(completed_value)
        if completed.tzinfo is None:
            return {**result, "error": "collection completion has no timezone"}
        completed = completed.astimezone(JST)
        current = now.astimezone(JST)
        result.update(
            {
                "collection_mode": manifest.get("collection_mode"),
                "collection_completed_at_jst": completed.isoformat(),
                "fresh_evening_issue": (
                    completed.date().isoformat() == issue_date
                    and completed.hour >= 19
                    and current - completed <= timedelta(hours=4)
                    and completed <= current + timedelta(minutes=5)
                    and manifest.get("collection_mode")
                    in {
                        "responses_web_search",
                        "reviewed_live_web",
                        "github_models_unattended",
                    }
                ),
            }
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        result["error"] = str(exc)
    return result


def evidence_state(issue_date: str, state_root: Path) -> dict[str, Any]:
    path = state_root / issue_date / "evidence.json"
    result = {"path": str(path), "exists": path.exists(), "usable": False}
    if not path.exists():
        return result
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        report = evidence_store.validate_bundle(bundle, issue_date)
        result.update(
            {
                "usable": not report["editor_coverage_gaps"],
                "source_checks": report["source_checks"],
                "discovery_checks": report["discovery_checks"],
                "unresolved_queries": report["unresolved_queries"],
                "editor_coverage_gaps": report["editor_coverage_gaps"],
            }
        )
    except (
        AttributeError,
        json.JSONDecodeError,
        OSError,
        evidence_store.EvidenceContractError,
    ) as exc:
        result["error"] = str(exc)
    return result


def git_state() -> dict[str, Any]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    paths = [
        line[3:]
        for line in result.stdout.splitlines()
        if len(line) >= 4
    ]
    return {
        "available": result.returncode == 0,
        "dirty": bool(paths),
        "changed_paths": paths,
        "error": result.stderr.strip() or None,
    }


def decide_recovery(
    *,
    fresh_evening_issue: bool,
    evidence_usable: bool,
    github_models_token: bool = False,
) -> str:
    if fresh_evening_issue:
        return "fresh_evening_issue"
    if evidence_usable:
        return "evidence"
    if github_models_token:
        return "github_models_unattended"
    return "blocked_no_honest_collector"


def latest_automation_run(automation_id: str) -> dict[str, Any]:
    home = Path.home() / ".codex"
    automation_db = home / "sqlite" / "codex-dev.db"
    state_db = home / "state_5.sqlite"
    if not automation_db.exists():
        return {"available": False, "reason": f"missing {automation_db}"}
    with sqlite3.connect(automation_db) as connection:
        row = connection.execute(
            """
            select thread_id, status, created_at, updated_at
            from automation_runs
            where automation_id = ?
            order by created_at desc
            limit 1
            """,
            (automation_id,),
        ).fetchone()
    if not row:
        return {"available": True, "found": False}
    thread_id, status, created_at, updated_at = row
    result: dict[str, Any] = {
        "available": True,
        "found": True,
        "thread_id": thread_id,
        "status": status,
        "created_at_jst": datetime.fromtimestamp(created_at / 1000, JST).isoformat(),
        "updated_at_jst": datetime.fromtimestamp(updated_at / 1000, JST).isoformat(),
    }
    if not state_db.exists():
        return result
    with sqlite3.connect(state_db) as connection:
        thread = connection.execute(
            "select rollout_path from threads where id = ?",
            (thread_id,),
        ).fetchone()
    if not thread:
        return result
    rollout_path = Path(thread[0])
    result["rollout_path"] = str(rollout_path)
    if not rollout_path.exists():
        return result
    text = rollout_path.read_text(encoding="utf-8", errors="replace")
    result["failure_class"] = classify_failure(text)
    result["has_agent_completion"] = '"last_agent_message":null' not in text
    result["credit_exhausted"] = result["failure_class"] == "codex_credit_exhausted"
    return result


def checkpoint_path(issue_date: str, state_root: Path) -> Path:
    return state_root / issue_date / "runtime_checkpoint.json"


def write_checkpoint(
    issue_date: str,
    stage: str,
    status: str,
    detail: str,
    state_root: Path,
) -> dict[str, Any]:
    if stage not in STAGES:
        fail(f"unknown runtime stage: {stage}")
    if status not in {"started", "completed", "failed", "blocked"}:
        fail(f"unknown runtime status: {status}")
    path = checkpoint_path(issue_date, state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    stages: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("issue_date") == issue_date:
                loaded_stages = loaded.get("stages")
                if isinstance(loaded_stages, dict):
                    stages = loaded_stages
        except json.JSONDecodeError:
            pass
    event = {
        "stage": stage,
        "status": status,
        "detail": detail,
        "recorded_at_jst": datetime.now(JST).isoformat(timespec="seconds"),
    }
    stages[stage] = event
    value = {
        "issue_date": issue_date,
        "stages": stages,
        "last_event": event,
    }
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return value


def evaluate(
    issue_date: str,
    state_root: Path,
    *,
    automation_id: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(JST)
    manifest = manifest_state(issue_date, state_root, current)
    evidence = evidence_state(issue_date, state_root)
    github_models_available = bool(
        os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    )
    recovery = decide_recovery(
        fresh_evening_issue=bool(manifest["fresh_evening_issue"]),
        evidence_usable=bool(evidence["usable"]),
        github_models_token=github_models_available,
    )
    result = {
        "issue_date": issue_date,
        "checked_at_jst": current.astimezone(JST).isoformat(timespec="seconds"),
        "manifest": manifest,
        "evidence": evidence,
        "github_models_token_available": github_models_available,
        "git": git_state(),
        "recovery_path": recovery,
        "publication_blocked": recovery == "blocked_no_honest_collector",
        "checkpoint": str(checkpoint_path(issue_date, state_root)),
    }
    if automation_id:
        result["automation"] = latest_automation_run(automation_id)
    return result


def self_test() -> None:
    cases = {
        '{"has_credits":false,"balance":"0"}': "codex_credit_exhausted",
        "HTTP 429 rate_limit": "rate_limited",
        "context_length_exceeded": "model_token_budget_exhausted",
        "GITHUB_TOKEN is required": "authentication_unavailable",
        "command timed out": "execution_timeout",
        "Could not resolve host: example.com": "network_unavailable",
        "Could not resolve host: github.com": "github_unavailable",
        "working tree has uncommitted changes": "dirty_worktree",
        '{"last_agent_message":null}': "partial_execution",
    }
    for text, expected in cases.items():
        actual = classify_failure(text)
        if actual != expected:
            fail(f"classification mismatch: {text!r}: {actual} != {expected}")
    if decide_recovery(
        fresh_evening_issue=False,
        evidence_usable=False,
    ) != "blocked_no_honest_collector":
        fail("no-collector state must block publication")
    if decide_recovery(
        fresh_evening_issue=True,
        evidence_usable=False,
    ) != "fresh_evening_issue":
        fail("fresh issue must select deploy-existing recovery")
    if decide_recovery(
        fresh_evening_issue=False,
        evidence_usable=False,
        github_models_token=True,
    ) != "github_models_unattended":
        fail("GitHub token must select unattended collection fallback")
    print("NIGHT SIGNAL RUNTIME AUDIT PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=datetime.now(JST).date().isoformat())
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--automation-id")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--fail-on-blocker", action="store_true")
    parser.add_argument("--checkpoint-stage", choices=STAGES)
    parser.add_argument(
        "--checkpoint-status",
        choices=["started", "completed", "failed", "blocked"],
        default="completed",
    )
    parser.add_argument("--detail", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.checkpoint_stage:
        value = write_checkpoint(
            args.issue_date,
            args.checkpoint_stage,
            args.checkpoint_status,
            args.detail,
            args.state_root,
        )
        print(json.dumps(value["last_event"], ensure_ascii=False, indent=2))
        return 0
    result = evaluate(
        args.issue_date,
        args.state_root,
        automation_id=args.automation_id,
    )
    if args.write_status:
        path = args.state_root / args.issue_date / "runtime_status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.fail_on_blocker and result["publication_blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
