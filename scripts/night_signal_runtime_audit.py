#!/usr/bin/env python3
"""Classify NIGHT SIGNAL runtime failures and choose an honest recovery path."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import night_signal_evidence as evidence_store
import night_signal_core as core

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


def output_text(value: Any) -> str:
    """Extract text from persisted tool outputs without reading prompt context."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(output_text(item) for item in value)
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return str(value["text"])
        return "\n".join(output_text(item) for item in value.values())
    return ""


def parse_event_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(JST)


def automation_trace_state(
    rollout_path: Path,
    *,
    now: datetime | None = None,
    stale_after_minutes: int = 15,
) -> dict[str, Any]:
    """Read executed JSONL events only; prompts and instructions are not evidence."""
    current = (now or datetime.now(JST)).astimezone(JST)
    task_started = False
    task_complete = False
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_executed_at: datetime | None = None
    executed_outputs: list[str] = []
    malformed_lines = 0
    try:
        lines = rollout_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {"available": False, "reason": str(exc)}
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines += 1
            continue
        if not isinstance(record, dict):
            continue
        timestamp = parse_event_time(record.get("timestamp"))
        record_type = record.get("type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if record_type == "event_msg":
            event_type = payload.get("type")
            if event_type == "task_started":
                task_started = True
                started_at = timestamp or started_at
                last_executed_at = timestamp or last_executed_at
            elif event_type == "task_complete":
                task_complete = True
                completed_at = timestamp or completed_at
                last_executed_at = timestamp or last_executed_at
        elif record_type == "response_item" and payload.get("type") in {
            "custom_tool_call_output",
            "function_call_output",
        }:
            text = output_text(payload.get("output")).strip()
            if text:
                executed_outputs.append(text)
            last_executed_at = timestamp or last_executed_at
    stalled = bool(
        task_started
        and not task_complete
        and last_executed_at is not None
        and current - last_executed_at >= timedelta(minutes=stale_after_minutes)
    )
    executed_text = "\n".join(executed_outputs)
    return {
        "available": True,
        "task_started": task_started,
        "task_complete": task_complete,
        "has_agent_completion": task_complete,
        "stalled": stalled,
        "started_at_jst": started_at.isoformat() if started_at else None,
        "completed_at_jst": completed_at.isoformat() if completed_at else None,
        "last_executed_at_jst": (
            last_executed_at.isoformat() if last_executed_at else None
        ),
        "failure_class": classify_failure(executed_text),
        "executed_output_count": len(executed_outputs),
        "malformed_lines": malformed_lines,
    }


def manifest_state(issue_date: str, state_root: Path, now: datetime) -> dict[str, Any]:
    path = state_root / issue_date / "issue.json"
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "fresh_final_issue": False,
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
                "fresh_final_issue": (
                    completed.date().isoformat() == issue_date
                    and completed.timetz().replace(tzinfo=None) >= time(15, 30)
                    and current - completed <= timedelta(hours=4)
                    and completed <= current + timedelta(minutes=5)
                    and manifest.get("collection_mode")
                    in {"web_evidence_plus_review", "github_models_unattended"}
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
        editor_coverage_gaps = core.remaining_editor_coverage_gaps(
            bundle,
            report,
        )
        result.update(
            {
                "usable": not editor_coverage_gaps,
                "source_checks": report["source_checks"],
                "discovery_checks": report["discovery_checks"],
                "unresolved_queries": report["unresolved_queries"],
                "editor_coverage_gaps": editor_coverage_gaps,
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
    fresh_final_issue: bool,
    evidence_usable: bool,
    artifacts: dict[str, bool] | None = None,
) -> str:
    if fresh_final_issue:
        return "fresh_final_issue"
    artifact_state = artifacts if artifacts is not None else {"editor_packet": True}
    if artifact_state.get("issue") and artifact_state.get("plus_review_receipt"):
        return "render_validate_publish"
    if artifact_state.get("editor_review"):
        return "apply_review"
    if evidence_usable and artifact_state.get("editor_packet"):
        return "await_cloud_review"
    if evidence_usable:
        return "prepare_review_packet"
    return "web_evidence_collection"


def latest_automation_run(
    automation_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
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
    trace = automation_trace_state(rollout_path, now=now)
    result["trace"] = trace
    result["failure_class"] = trace.get("failure_class", "unknown")
    result["has_agent_completion"] = trace.get("task_complete") is True
    result["stalled"] = trace.get("stalled") is True
    result["credit_exhausted"] = result["failure_class"] == "codex_credit_exhausted"
    return result


def checkpoint_path(issue_date: str, state_root: Path) -> Path:
    return state_root / issue_date / "runtime_checkpoint.json"


def local_artifact_state(issue_date: str, state_root: Path) -> dict[str, bool]:
    base = state_root / issue_date
    return {
        "evidence": (base / "evidence.json").exists(),
        "editor_packet": (base / "editor_packet.json").exists(),
        "editor_review": (base / "editor_review.json").exists(),
        "plus_review_receipt": (base / "plus_review_receipt.json").exists(),
        "issue": (base / "issue.json").exists(),
        "sample_html": (ROOT / f"night-brief-web-sample-{issue_date}.html").exists(),
        "dated_site_html": (ROOT / "site" / issue_date / "index.html").exists(),
    }


def read_checkpoint(issue_date: str, state_root: Path) -> dict[str, Any]:
    path = checkpoint_path(issue_date, state_root)
    if not path.exists():
        return {"exists": False, "path": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"exists": True, "path": str(path), "error": str(exc)}
    if not isinstance(value, dict) or value.get("issue_date") != issue_date:
        return {
            "exists": True,
            "path": str(path),
            "error": "checkpoint issue date does not match",
        }
    last_event = value.get("last_event")
    return {
        "exists": True,
        "path": str(path),
        "last_event": last_event if isinstance(last_event, dict) else None,
    }


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
    artifacts = local_artifact_state(issue_date, state_root)
    recovery = decide_recovery(
        fresh_final_issue=bool(manifest["fresh_final_issue"]),
        evidence_usable=bool(evidence["usable"]),
        artifacts=artifacts,
    )
    repository = git_state()
    result = {
        "issue_date": issue_date,
        "checked_at_jst": current.astimezone(JST).isoformat(timespec="seconds"),
        "manifest": manifest,
        "evidence": evidence,
        "additional_paid_ai_required": False,
        "artifacts": artifacts,
        "git": repository,
        "recovery_path": recovery,
        "publication_blocked": bool(repository.get("dirty")),
        "blockers": ["dirty_worktree"] if repository.get("dirty") else [],
        "checkpoint": read_checkpoint(issue_date, state_root),
    }
    if automation_id:
        automation = latest_automation_run(automation_id, now=current)
        result["automation"] = automation
        if automation.get("stalled") is True:
            result["recovery_required"] = True
            result["stale_owner_takeover_allowed"] = True
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
        fresh_final_issue=False,
        evidence_usable=False,
    ) != "web_evidence_collection":
        fail("missing Evidence must select the web collector")
    if decide_recovery(
        fresh_final_issue=True,
        evidence_usable=False,
    ) != "fresh_final_issue":
        fail("fresh issue must select deploy-existing recovery")
    if decide_recovery(
        fresh_final_issue=False,
        evidence_usable=True,
    ) != "await_cloud_review":
        fail("usable Evidence must wait for the PC-independent cloud review")
    if decide_recovery(
        fresh_final_issue=False,
        evidence_usable=True,
        artifacts={"editor_review": True},
    ) != "apply_review":
        fail("saved review must resume at deterministic review application")
    if decide_recovery(
        fresh_final_issue=False,
        evidence_usable=True,
        artifacts={"issue": True, "plus_review_receipt": True},
    ) != "render_validate_publish":
        fail("validated issue must resume at rendering and publication")
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "rollout.jsonl"
        records = [
            {
                "timestamp": "2099-01-01T09:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "HTTP 429 rate_limit"}],
                },
            },
            {
                "timestamp": "2099-01-01T09:00:01Z",
                "type": "event_msg",
                "payload": {"type": "task_started"},
            },
            {
                "timestamp": "2099-01-01T09:00:02Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "output": [{"type": "input_text", "text": "git status clean"}],
                },
            },
        ]
        path.write_text(
            "\n".join(json.dumps(value) for value in records) + "\n",
            encoding="utf-8",
        )
        trace = automation_trace_state(
            path,
            now=datetime.fromisoformat("2099-01-01T09:20:03+00:00"),
        )
        if trace["failure_class"] != "unknown":
            fail("prompt text was misclassified as an executed failure")
        if trace["has_agent_completion"] or not trace["stalled"]:
            fail("incomplete automation trace was not marked stalled")
        records.append(
            {
                "timestamp": "2099-01-01T09:20:04Z",
                "type": "event_msg",
                "payload": {"type": "task_complete"},
            }
        )
        path.write_text(
            "\n".join(json.dumps(value) for value in records) + "\n",
            encoding="utf-8",
        )
        completed = automation_trace_state(
            path,
            now=datetime.fromisoformat("2099-01-01T09:20:05+00:00"),
        )
        if not completed["has_agent_completion"] or completed["stalled"]:
            fail("task_complete was not recognized as executed completion proof")
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
