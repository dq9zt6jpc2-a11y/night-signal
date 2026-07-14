#!/usr/bin/env python3
"""Verify the two-workflow, single-owner publication boundary."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import publication_timing as timing


ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
COLLECTION = ROOT / ".github" / "workflows" / "unattended-collection.yml"


def fail(message: str) -> None:
    print(f"PUBLICATION SCHEDULE AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def cron_minutes(text: str) -> list[int]:
    values = []
    for minute, hour in re.findall(r'cron:\s*"(\d{2})\s+(\d{2})\s+\*\s+\*\s+\*"', text):
        values.append((int(hour) * 60 + int(minute) + 9 * 60) % (24 * 60))
    return sorted(values)


def ordered(text: str, *labels: str) -> bool:
    positions = [text.find(label) for label in labels]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def main() -> int:
    pages = PAGES.read_text(encoding="utf-8")
    collection = COLLECTION.read_text(encoding="utf-8")
    policy = timing.load_policy()
    if cron_minutes(pages) or re.search(r"\n\s+push:", pages):
        fail("Pages must be dispatch-only")
    if "--deploy-existing" not in pages:
        fail("Pages may deploy only committed issue state")
    expected_heartbeats = sorted(
        timing.minutes(value) for value in policy.schedule_heartbeats_jst
    )
    if cron_minutes(collection) != expected_heartbeats:
        fail(
            "collection heartbeats do not match the timing policy: "
            f"{cron_minutes(collection)} != {expected_heartbeats}"
        )
    if "night-signal-unattended-collection" not in collection or "cancel-in-progress: false" not in collection:
        fail("collection needs one non-cancelling concurrency owner")
    if (
        f"timeout-minutes: {policy.runtime_budget_minutes}" not in collection
        or f"timeout-minutes: {policy.build_timeout_minutes}" not in collection
        or f"timeout-minutes: {policy.pages_timeout_minutes}" not in collection
    ):
        fail("collection and job runtime must be bounded")
    if collection.count('python3 scripts/night_signal_publish.py "$ISSUE_DATE"') != 2:
        fail("fresh and Evidence-reuse branches must both use the canonical pipeline")
    for direct_owner in (
        "python3 scripts/night_signal_collect.py",
        "python3 scripts/night_signal_editor.py",
    ):
        if direct_owner in collection:
            fail(f"workflow bypasses the canonical pipeline: {direct_owner}")
    if not ordered(
        collection,
        "Guard against a queued duplicate owner",
        "Evaluate publication window",
        "Detect an already verified publication",
        "Enforce publication deadline",
        "Audit current model catalog",
        "Restore Evidence checkpoint",
        "Build audited issue",
        "Save Evidence checkpoint",
        "Commit audited issue",
        "Dispatch Pages publication",
        "Wait for Pages publication",
    ):
        fail("collection, checkpoint, commit, and publication stages are out of order")
    if "steps.current_publication.outputs.published != 'true'" not in collection:
        fail("verified publication must short-circuit the fallback attempt")
    if "force:" in collection or "inputs.force" in collection:
        fail("verified publication must not have a force-recollection bypass")
    if "NIGHT_SIGNAL_ALLOW_EXPLICIT_STALE" in collection or "NIGHT_SIGNAL_ALLOW_EXPLICIT_STALE" in pages:
        fail("production workflows must never publish a stale issue as latest")
    if "scripts/publication_timing.py --decision" not in collection:
        fail("scheduled work must use the actual-time publication window")
    if "steps.timing.outputs.action == 'run'" not in collection:
        fail("model and publication work must be gated by the timing decision")
    if "night_signal_model_audit.py" not in collection:
        fail("daily publication must check current model availability without inference")
    if not ordered(
        collection,
        "reuse_evidence:",
        "default: true",
        "Resolve recovery mode",
        'if [[ "$GITHUB_EVENT_NAME" == "schedule" ]]',
        'echo "reuse=false"',
        "Locate latest Evidence checkpoint",
        "steps.recovery.outputs.reuse == 'true'",
        "REUSE_EVIDENCE: ${{ steps.recovery.outputs.reuse }}",
        'if [[ "$REUSE_EVIDENCE" == "true" ]]',
        'python3 scripts/night_signal_publish.py "$ISSUE_DATE" --reuse-evidence',
    ):
        fail("manual recovery must reuse checkpoints while scheduled collection stays fresh")
    if (
        "scripts/night_signal_run_guard.py" not in collection
        or "needs: owner_guard" not in collection
        or "needs.owner_guard.outputs.proceed == 'true'" not in collection
        or "Report duplicate owner skip" not in collection
    ):
        fail("queued duplicate owner runs must stop before model work")
    if "actions/upload-artifact@v7.0.1" not in collection or "actions/download-artifact@v8.0.1" not in collection:
        fail("a failed first attempt must leave a reusable Evidence")
    for checkpoint_name in ("editor_checkpoint.json", "runtime_checkpoint.json"):
        if checkpoint_name not in collection:
            fail(f"recovery artifact is missing {checkpoint_name}")
    if "models: read" not in collection or "contents: write" not in collection or "actions: write" not in collection:
        fail("workflow permissions do not match collection and publication duties")
    if "git push origin HEAD:main" not in collection or "gh workflow run pages.yml" not in collection:
        fail("audited state must be committed before Pages dispatch")
    if 'gh run watch "$RUN_ID" --exit-status' not in collection:
        fail("collection owner must wait for public deployment")
    print(
        "PUBLICATION SCHEDULE AUDIT PASSED: "
        f"window={policy.final_collection_not_before.strftime('%H:%M')}-"
        f"{policy.publication_deadline.strftime('%H:%M')}, "
        f"runtime={policy.runtime_budget_minutes}m, "
        f"safety={policy.deadline_safety_margin_minutes}m, "
        "scheduled_collection=fresh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
