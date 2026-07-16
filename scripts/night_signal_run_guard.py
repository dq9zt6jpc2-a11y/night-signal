#!/usr/bin/env python3
"""Skip a queued owner run that overlapped an older collection run."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


API_ROOT = "https://api.github.com"


def parse_time(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def duplicate_owner_run(
    current_run_id: int,
    runs: list[dict[str, Any]],
) -> int | None:
    current = next(
        (run for run in runs if int(run.get("id", 0)) == current_run_id),
        None,
    )
    if current is None:
        raise ValueError(f"current workflow run {current_run_id} was not returned")
    current_created = parse_time(current.get("created_at"))
    overlaps: list[tuple[datetime, int]] = []
    for run in runs:
        run_id = int(run.get("id", 0))
        if not run_id or run_id == current_run_id:
            continue
        created = parse_time(run.get("created_at"))
        updated = parse_time(run.get("updated_at"))
        if created <= current_created <= updated:
            overlaps.append((created, run_id))
    return max(overlaps, default=(current_created, 0))[1] or None


def workflow_runs(repository: str, workflow: str, token: str) -> list[dict[str, Any]]:
    encoded_workflow = urllib.parse.quote(workflow, safe="")
    url = (
        f"{API_ROOT}/repos/{repository}/actions/workflows/"
        f"{encoded_workflow}/runs?per_page=50"
    )
    errors: list[str] = []
    for attempt in range(2):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "night-signal-owner-guard",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            runs = payload.get("workflow_runs")
            if not isinstance(runs, list):
                raise ValueError("workflow_runs is missing from the GitHub response")
            return [run for run in runs if isinstance(run, dict)]
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            errors.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")
            if attempt == 0:
                time.sleep(2)
    raise RuntimeError("owner guard request failed: " + " / ".join(errors))


def repository_artifacts(
    repository: str,
    artifact_name: str,
    token: str,
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"per_page": 100, "name": artifact_name})
    url = f"{API_ROOT}/repos/{repository}/actions/artifacts?{query}"
    errors: list[str] = []
    for attempt in range(2):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "night-signal-owner-guard",
                "X-GitHub-Api-Version": "2026-03-10",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
            artifacts = payload.get("artifacts")
            if not isinstance(artifacts, list):
                raise ValueError("artifacts is missing from the GitHub response")
            return [item for item in artifacts if isinstance(item, dict)]
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            errors.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")
            if attempt == 0:
                time.sleep(2)
    raise RuntimeError("artifact guard request failed: " + " / ".join(errors))


def reusable_artifact_id(
    artifact_name: str,
    artifacts: list[dict[str, Any]],
) -> int | None:
    candidates: list[dict[str, Any]] = []
    for artifact in artifacts:
        workflow_run = artifact.get("workflow_run")
        if not isinstance(workflow_run, dict):
            continue
        try:
            artifact_id = int(artifact.get("id", 0))
        except (TypeError, ValueError):
            continue
        if (
            artifact.get("name") == artifact_name
            and artifact.get("expired") is not True
            and str(workflow_run.get("head_branch", "")) == "main"
            and artifact_id > 0
        ):
            candidates.append(artifact)
    if not candidates:
        return None
    return int(max(candidates, key=lambda item: str(item.get("created_at", "")))["id"])


def write_outputs(
    path: Path | None,
    *,
    proceed: bool,
    duplicate_of: int | None,
    artifact_ready: bool = False,
    artifact_id: int | None = None,
) -> None:
    lines = [f"proceed={'true' if proceed else 'false'}"]
    lines.append(f"duplicate_of={duplicate_of or ''}")
    lines.append(f"artifact_ready={'true' if artifact_ready else 'false'}")
    lines.append(f"artifact_id={artifact_id or ''}")
    text = "\n".join(lines) + "\n"
    if path is None:
        sys.stdout.write(text)
    else:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)


def self_test() -> None:
    runs = [
        {
            "id": 100,
            "created_at": "2026-07-14T10:00:00Z",
            "updated_at": "2026-07-14T10:40:00Z",
        },
        {
            "id": 101,
            "created_at": "2026-07-14T10:20:00Z",
            "updated_at": "2026-07-14T10:50:00Z",
        },
        {
            "id": 99,
            "created_at": "2026-07-14T08:00:00Z",
            "updated_at": "2026-07-14T08:30:00Z",
        },
    ]
    if duplicate_owner_run(101, runs) != 100:
        raise SystemExit("queued duplicate owner run was not detected")
    if duplicate_owner_run(100, runs) is not None:
        raise SystemExit("the original owner run was incorrectly marked duplicate")
    artifacts = [
        {
            "id": 51,
            "name": "night-signal-state-2026-07-16",
            "expired": False,
            "created_at": "2026-07-16T10:00:00Z",
            "workflow_run": {"head_branch": "main"},
        },
        {
            "id": 50,
            "name": "night-signal-state-2026-07-16",
            "expired": True,
            "created_at": "2026-07-16T09:00:00Z",
            "workflow_run": {"head_branch": "main"},
        },
        {
            "id": "invalid",
            "name": "night-signal-state-2026-07-16",
            "expired": False,
            "created_at": "2026-07-16T11:00:00Z",
            "workflow_run": None,
        },
    ]
    if reusable_artifact_id("night-signal-state-2026-07-16", artifacts) != 51:
        raise SystemExit("reusable final Evidence artifact was not detected")
    print("NIGHT SIGNAL OWNER GUARD PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument(
        "--workflow",
        default="unattended-collection.yml",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=int(os.getenv("GITHUB_RUN_ID", "0") or 0),
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"]) if os.getenv("GITHUB_OUTPUT") else None,
    )
    parser.add_argument("--artifact-name", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""
    if not args.repository or not args.run_id or not token:
        raise SystemExit("repository, run id, and GITHUB_TOKEN are required")
    duplicate_of = duplicate_owner_run(
        args.run_id,
        workflow_runs(args.repository, args.workflow, token),
    )
    artifact_id = (
        reusable_artifact_id(
            args.artifact_name,
            repository_artifacts(args.repository, args.artifact_name, token),
        )
        if args.artifact_name
        else None
    )
    write_outputs(
        args.github_output,
        proceed=duplicate_of is None,
        duplicate_of=duplicate_of,
        artifact_ready=artifact_id is not None,
        artifact_id=artifact_id,
    )
    if duplicate_of:
        print(f"Queued duplicate of owner run {duplicate_of}; model work will be skipped.")
    if artifact_id:
        print(f"Reusable final Evidence artifact {artifact_id} is already available.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
