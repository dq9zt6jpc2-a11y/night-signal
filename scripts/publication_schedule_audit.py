#!/usr/bin/env python3
"""Verify the two-workflow, single-owner publication boundary."""

from __future__ import annotations

import re
import sys
from pathlib import Path


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
    if cron_minutes(pages) or re.search(r"\n\s+push:", pages):
        fail("Pages must be dispatch-only")
    if "--deploy-existing" not in pages:
        fail("Pages may deploy only committed issue state")
    if cron_minutes(collection) != [19 * 60 + 5, 19 * 60 + 35]:
        fail(f"collection attempts must be 19:05 and 19:35 JST: {cron_minutes(collection)}")
    if "night-signal-unattended-collection" not in collection or "cancel-in-progress: false" not in collection:
        fail("collection needs one non-cancelling concurrency owner")
    if "timeout-minutes: 105" not in collection or "timeout-minutes: 70" not in collection:
        fail("collection and job runtime must be bounded")
    if collection.count('python3 scripts/night_signal_publish.py "$ISSUE_DATE"') != 2:
        fail("force and normal branches must both use the canonical pipeline")
    for direct_owner in (
        "python3 scripts/night_signal_unattended_collect.py",
        "python3 scripts/night_signal_import_research.py",
    ):
        if direct_owner in collection:
            fail(f"workflow bypasses the canonical pipeline: {direct_owner}")
    if not ordered(
        collection,
        "Detect an already verified publication",
        "Restore reviewed state checkpoint",
        "Build audited issue",
        "Save reviewed state checkpoint",
        "Commit audited issue",
        "Dispatch Pages publication",
        "Wait for Pages publication",
    ):
        fail("collection, checkpoint, commit, and publication stages are out of order")
    if "steps.current_publication.outputs.published != 'true'" not in collection:
        fail("verified publication must short-circuit the fallback attempt")
    if "actions/upload-artifact@v7.0.1" not in collection or "actions/download-artifact@v8.0.1" not in collection:
        fail("a failed first attempt must leave a reusable reviewed bundle")
    if "models: read" not in collection or "contents: write" not in collection or "actions: write" not in collection:
        fail("workflow permissions do not match collection and publication duties")
    if "git push origin HEAD:main" not in collection or "gh workflow run pages.yml" not in collection:
        fail("audited state must be committed before Pages dispatch")
    if 'gh run watch "$RUN_ID" --exit-status' not in collection:
        fail("collection owner must wait for public deployment")
    print("PUBLICATION SCHEDULE AUDIT PASSED: pages=dispatch-only, collection_jst=[19:05,19:35]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
