#!/usr/bin/env python3
"""Restore or create one final Evidence artifact without duplicate dispatches."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, time as clock
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
WORKFLOW = "unattended-collection.yml"
JST = ZoneInfo("Asia/Tokyo")
NETWORK_ERRORS = (
    "could not resolve host",
    "connection reset",
    "connection timed out",
    "error connecting to api.github.com",
    "temporary failure",
)


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL ARTIFACT FAILED: {message}", file=__import__("sys").stderr)
    raise SystemExit(1)


def run_gh(arguments: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    result: subprocess.CompletedProcess[str] | None = None
    for attempt in range(2):
        result = subprocess.run(
            ["gh", *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            if not capture:
                if result.stdout:
                    print(result.stdout, end="")
                if result.stderr:
                    print(result.stderr, end="", file=__import__("sys").stderr)
            return result
        error = f"{result.stdout}\n{result.stderr}".casefold()
        if attempt == 0 and any(marker in error for marker in NETWORK_ERRORS):
            continue
        break
    assert result is not None
    fail(f"gh {' '.join(arguments)}: {result.stderr.strip() or result.stdout.strip()}")


def list_runs() -> list[dict[str, Any]]:
    result = run_gh(
        [
            "run",
            "list",
            "--workflow",
            WORKFLOW,
            "--branch",
            "main",
            "--limit",
            "12",
            "--json",
            "databaseId,status,conclusion,createdAt,headSha,event",
        ]
    )
    value = json.loads(result.stdout)
    if not isinstance(value, list):
        fail("gh run list did not return an array")
    return [entry for entry in value if isinstance(entry, dict)]


def run_created_on_issue_date(run: dict[str, Any], issue_date: str) -> bool:
    try:
        created = datetime.fromisoformat(str(run["createdAt"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return False
    return created.astimezone(JST).date().isoformat() == issue_date


def current_runs(runs: list[dict[str, Any]], issue_date: str) -> list[dict[str, Any]]:
    return [run for run in runs if run_created_on_issue_date(run, issue_date)]


def active_run_id(runs: list[dict[str, Any]], issue_date: str) -> int | None:
    active = [
        run
        for run in current_runs(runs, issue_date)
        if run.get("status") in {"queued", "in_progress", "pending", "waiting"}
    ]
    if not active:
        return None
    return int(active[0]["databaseId"])


def successful_run_ids(runs: list[dict[str, Any]], issue_date: str) -> list[int]:
    return [
        int(run["databaseId"])
        for run in current_runs(runs, issue_date)
        if run.get("status") == "completed" and run.get("conclusion") == "success"
    ]


def validate_download(directory: Path, issue_date: str) -> tuple[Path, Path, Path | None]:
    evidence_path = directory / "evidence.json"
    packet_path = directory / "editor_packet.json"
    eval_path = directory / "eval_report.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if evidence.get("issue_date") != issue_date or packet.get("issue_date") != issue_date:
        raise ValueError("artifact issue date does not match")
    checked = datetime.fromisoformat(str(evidence.get("checked_at_jst")))
    if checked.tzinfo is None or checked.astimezone(JST).time() < clock(16, 45):
        raise ValueError("artifact is not final Evidence from 16:45 JST or later")
    actual_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    if packet.get("evidence_sha256") != actual_hash:
        raise ValueError("packet and Evidence hashes differ")
    if packet.get("contract") != "codex-plus-editor-v1":
        raise ValueError("artifact uses an unknown Plus review contract")
    return evidence_path, packet_path, eval_path if eval_path.exists() else None


def restore_run(run_id: int, issue_date: str, state_root: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix="night-signal-artifact-") as temporary:
        directory = Path(temporary)
        arguments = [
            "run",
            "download",
            str(run_id),
            "--name",
            f"night-signal-state-{issue_date}",
            "--dir",
            str(directory),
        ]
        result: subprocess.CompletedProcess[str] | None = None
        for attempt in range(2):
            result = subprocess.run(
                ["gh", *arguments],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            if result.returncode == 0:
                break
            error = f"{result.stdout}\n{result.stderr}".casefold()
            if attempt == 0 and any(marker in error for marker in NETWORK_ERRORS):
                continue
            break
        assert result is not None
        if result.returncode != 0:
            return False
        try:
            evidence_path, packet_path, eval_path = validate_download(
                directory,
                issue_date,
            )
        except ValueError:
            return False
        destination = state_root / issue_date
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(evidence_path, destination / "evidence.json")
        shutil.copy2(packet_path, destination / "editor_packet.json")
        if eval_path is not None:
            shutil.copy2(eval_path, destination / "eval_report.json")
    print(
        json.dumps(
            {"issue_date": issue_date, "run_id": run_id, "artifact_restored": True},
            ensure_ascii=False,
        )
    )
    return True


def wait_for_new_run(known_ids: set[int], issue_date: str) -> int:
    for _ in range(24):
        runs = current_runs(list_runs(), issue_date)
        new = [
            int(run["databaseId"])
            for run in runs
            if int(run["databaseId"]) not in known_ids
        ]
        if new:
            return new[0]
        time.sleep(5)
    fail("dispatched Evidence run did not appear within two minutes")


def ensure_artifact(issue_date: str, state_root: Path) -> dict[str, Any]:
    runs = list_runs()
    active = active_run_id(runs, issue_date)
    if active is not None:
        run_gh(["run", "watch", str(active), "--exit-status"], capture=False)
        runs = list_runs()
    for run_id in successful_run_ids(runs, issue_date):
        if restore_run(run_id, issue_date, state_root):
            return {"issue_date": issue_date, "run_id": run_id, "dispatched": False}
    known_ids = {
        int(run["databaseId"])
        for run in runs
        if isinstance(run.get("databaseId"), int)
    }
    run_gh(
        [
            "workflow",
            "run",
            WORKFLOW,
            "--ref",
            "main",
            "-f",
            f"issue_date={issue_date}",
        ],
        capture=False,
    )
    run_id = wait_for_new_run(known_ids, issue_date)
    run_gh(["run", "watch", str(run_id), "--exit-status"], capture=False)
    if not restore_run(run_id, issue_date, state_root):
        fail(f"run {run_id} completed without a valid final Evidence artifact")
    return {"issue_date": issue_date, "run_id": run_id, "dispatched": True}


def self_test() -> None:
    runs = [
        {
            "databaseId": 3,
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2099-01-01T08:00:00Z",
        },
        {
            "databaseId": 2,
            "status": "in_progress",
            "conclusion": "",
            "createdAt": "2099-01-01T07:50:00Z",
        },
        {
            "databaseId": 1,
            "status": "completed",
            "conclusion": "success",
            "createdAt": "2098-12-31T08:00:00Z",
        },
    ]
    if active_run_id(runs, "2099-01-01") != 2:
        fail("active current-date run was not selected")
    if successful_run_ids(runs, "2099-01-01") != [3]:
        fail("successful current-date runs were not selected exactly")
    print("NIGHT SIGNAL ARTIFACT SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=datetime.now(JST).date().isoformat())
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    print(json.dumps(ensure_artifact(args.issue_date, args.state_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
