#!/usr/bin/env python3
"""Publish one immutable compact review packet on an isolated Git branch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
PACKET_CONTRACT = "codex-plus-editor-v1"
BRANCH_PREFIX = "night-signal-evidence-"
MAX_PACKET_BYTES = 20_000_000
MAX_PART_BYTES = 850_000


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL CLOUD HANDOFF FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def run_git(
    arguments: list[str],
    *,
    check: bool = True,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        input=input_text,
        capture_output=True,
        env={**os.environ, **(env or {})},
    )
    if check and result.returncode != 0:
        fail(
            f"git {' '.join(arguments)}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def branch_name(issue_date: str) -> str:
    if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", issue_date):
        fail("issue date must use YYYY-MM-DD")
    return f"{BRANCH_PREFIX}{issue_date}"


def handoff_path(issue_date: str) -> str:
    branch_name(issue_date)
    return f"cloud-evidence/{issue_date}/manifest.json"


def read_packet(path: Path, issue_date: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        fail(f"cannot read review packet: {exc}")
    if not raw or len(raw) > MAX_PACKET_BYTES:
        fail(f"packet size is outside 1..{MAX_PACKET_BYTES} bytes")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"review packet is invalid JSON: {exc}")
    if not isinstance(value, dict):
        fail("review packet root must be an object")
    if value.get("contract") != PACKET_CONTRACT:
        fail(f"review packet contract must be {PACKET_CONTRACT}")
    if value.get("issue_date") != issue_date:
        fail("review packet issue date does not match")
    evidence_hash = value.get("evidence_sha256")
    if not isinstance(evidence_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", evidence_hash
    ):
        fail("review packet has no valid Evidence SHA-256")
    requests = value.get("requests")
    if not isinstance(requests, list) or not requests:
        fail("review packet must contain at least one request")
    request_ids: set[str] = set()
    candidate_events = 0
    for request in requests:
        if not isinstance(request, dict):
            fail("each packet request must be an object")
        request_id = request.get("request_id")
        payload = request.get("payload")
        if not isinstance(request_id, str) or not request_id:
            fail("each packet request needs a request_id")
        if request_id in request_ids:
            fail("packet contains a duplicate request_id")
        request_ids.add(request_id)
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            fail(f"packet request {request_id} has no events array")
        candidate_events += len(payload["events"])
    metrics = value.get("metrics")
    if not isinstance(metrics, dict):
        fail("review packet metrics are missing")
    if metrics.get("requests") != len(requests):
        fail("review packet request metric does not match its content")
    if metrics.get("candidate_events") != candidate_events:
        fail("review packet event metric does not match its content")
    return value, raw


def compact_json(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def handoff_files(packet: dict[str, Any], raw: bytes) -> dict[str, bytes]:
    issue_date = str(packet["issue_date"])
    prefix = f"cloud-evidence/{issue_date}"
    parts: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for request in packet["requests"]:
        candidate = [*current, request]
        part_value = {
            "contract": PACKET_CONTRACT,
            "issue_date": issue_date,
            "evidence_sha256": packet["evidence_sha256"],
            "requests": candidate,
        }
        if len(compact_json(part_value)) <= MAX_PART_BYTES:
            current = candidate
            continue
        if not current:
            fail("one review request exceeds the cloud handoff part limit")
        parts.append(current)
        current = [request]
    if current:
        parts.append(current)
    files: dict[str, bytes] = {}
    part_entries: list[dict[str, Any]] = []
    for index, requests in enumerate(parts, start=1):
        path = f"{prefix}/requests/{index:03d}.json"
        content = compact_json(
            {
                "contract": PACKET_CONTRACT,
                "issue_date": issue_date,
                "evidence_sha256": packet["evidence_sha256"],
                "requests": requests,
            }
        )
        if len(content) > MAX_PART_BYTES:
            fail("cloud handoff part exceeded its byte limit")
        files[path] = content
        part_entries.append(
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
                "requests": len(requests),
            }
        )
    manifest = {
        "contract": PACKET_CONTRACT,
        "issue_date": issue_date,
        "evidence_sha256": packet["evidence_sha256"],
        "editor_contract_sha256": packet.get("editor_contract_sha256"),
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
        "policy": packet.get("policy"),
        "metrics": packet.get("metrics"),
        "parts": part_entries,
    }
    files[handoff_path(issue_date)] = compact_json(manifest)
    return files


def remote_files(issue_date: str, expected_paths: list[str]) -> dict[str, bytes] | None:
    branch = branch_name(issue_date)
    ref = f"refs/remotes/origin/{branch}"
    exists = run_git(
        ["ls-remote", "--exit-code", "--heads", "origin", f"refs/heads/{branch}"],
        check=False,
    )
    if exists.returncode == 2:
        return None
    if exists.returncode != 0:
        fail(f"could not inspect remote handoff branch: {exists.stderr.strip()}")
    run_git(
        [
            "fetch",
            "--no-tags",
            "origin",
            f"refs/heads/{branch}:{ref}",
        ]
    )
    values: dict[str, bytes] = {}
    for path in expected_paths:
        result = run_git(["show", f"{ref}:{path}"], check=False)
        if result.returncode != 0:
            fail(f"existing handoff branch does not contain {path}")
        values[path] = result.stdout.encode("utf-8")
    return values


def commit_packet(issue_date: str, packet_path: Path) -> dict[str, Any]:
    packet, raw = read_packet(packet_path, issue_date)
    branch = branch_name(issue_date)
    path = handoff_path(issue_date)
    files = handoff_files(packet, raw)
    existing = remote_files(issue_date, sorted(files))
    if existing is not None:
        if existing != files:
            fail("immutable handoff branch already exists with different content")
        return {
            "issue_date": issue_date,
            "branch": branch,
            "path": path,
            "packet_sha256": hashlib.sha256(raw).hexdigest(),
            "parts": len(files) - 1,
            "created": False,
            "remote_verified": True,
        }

    head = run_git(["rev-parse", "HEAD"]).stdout.strip()
    with tempfile.TemporaryDirectory(prefix="night-signal-handoff-") as temporary:
        index = str(Path(temporary) / "index")
        environment = {"GIT_INDEX_FILE": index}
        run_git(["read-tree", "HEAD"], env=environment)
        for destination, content in sorted(files.items()):
            blob = run_git(
                ["hash-object", "-w", "--stdin"],
                input_text=content.decode("utf-8"),
            ).stdout.strip()
            run_git(
                [
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    "100644",
                    blob,
                    destination,
                ],
                env=environment,
            )
        tree = run_git(["write-tree"], env=environment).stdout.strip()
    commit_environment = {
        "GIT_AUTHOR_NAME": "github-actions[bot]",
        "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        "GIT_COMMITTER_NAME": "github-actions[bot]",
        "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
    }
    commit = run_git(
        ["commit-tree", tree, "-p", head],
        input_text=f"Prepare NIGHT SIGNAL review packet for {issue_date}\n",
        env=commit_environment,
    ).stdout.strip()
    pushed = run_git(
        ["push", "origin", f"{commit}:refs/heads/{branch}"],
        check=False,
    )
    if pushed.returncode != 0:
        raced = remote_files(issue_date, sorted(files))
        if raced != files:
            fail(
                "handoff branch push failed and no byte-identical race winner exists: "
                f"{pushed.stderr.strip()}"
            )
        created = False
    else:
        created = True
    confirmed = remote_files(issue_date, sorted(files))
    if confirmed != files:
        fail("handoff push completed without a byte-identical remote manifest")
    return {
        "issue_date": issue_date,
        "branch": branch,
        "path": path,
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
        "parts": len(files) - 1,
        "created": created,
        "remote_verified": True,
    }


def self_test() -> None:
    issue_date = "2099-01-02"
    with tempfile.TemporaryDirectory() as temporary_directory:
        packet_path = Path(temporary_directory) / "editor_packet.json"
        packet = {
            "contract": PACKET_CONTRACT,
            "issue_date": issue_date,
            "evidence_sha256": "a" * 64,
            "requests": [
                {
                    "request_id": "request-1",
                    "payload": {"events": [{"id": "event-1"}]},
                }
            ],
            "metrics": {"requests": 1, "candidate_events": 1},
        }
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        parsed, raw = read_packet(packet_path, issue_date)
        files = handoff_files(parsed, raw)
        manifest = json.loads(files[handoff_path(issue_date)])
        if len(manifest["parts"]) != 1:
            fail("small review packet was not emitted as one part")
        part_path = manifest["parts"][0]["path"]
        if hashlib.sha256(files[part_path]).hexdigest() != manifest["parts"][0]["sha256"]:
            fail("handoff part digest is inconsistent")
        if branch_name(issue_date) != "night-signal-evidence-2099-01-02":
            fail("Evidence handoff branch is not deterministic")
        packet["metrics"]["candidate_events"] = 2
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        try:
            read_packet(packet_path, issue_date)
        except SystemExit:
            pass
        else:
            fail("packet with false event metrics was accepted")
    print("NIGHT SIGNAL CLOUD HANDOFF SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default="")
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.issue_date:
        fail("issue_date is required")
    packet_path = args.packet or STATE_ROOT / args.issue_date / "editor_packet.json"
    if not args.publish:
        packet, raw = read_packet(packet_path, args.issue_date)
        files = handoff_files(packet, raw)
        print(
            json.dumps(
                {
                    "issue_date": args.issue_date,
                    "branch": branch_name(args.issue_date),
                    "path": handoff_path(args.issue_date),
                    "requests": len(packet["requests"]),
                    "packet_bytes": len(raw),
                    "packet_sha256": hashlib.sha256(raw).hexdigest(),
                    "parts": len(files) - 1,
                },
                ensure_ascii=False,
            )
        )
        return 0
    print(json.dumps(commit_packet(args.issue_date, packet_path), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
