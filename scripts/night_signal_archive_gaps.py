#!/usr/bin/env python3
"""Reconstruct outstanding archive dates without relying on a scheduled run."""

import os
from datetime import date, datetime, timedelta

from night_signal_operational_audit import remote_json

from publication_timing import ROOT, load_policy
from sync_site import ARCHIVED_PREVIOUS_ISSUES
from zoneinfo import ZoneInfo

# Begin continuity checks with the incident that introduced this audit.
FIRST_TRACKED_ISSUE = date(2026, 11, 21)


def missing_dates(site, first, today):
    day = first
    while day < today:
        if not (site / day.isoformat() / "index.html").is_file():
            yield day.isoformat()
        day += timedelta(days=1)


def verified_publication(repository, issue):
    if not repository:
        return None
    feedback = remote_json(
        repository, f"night-signal-feedback-{issue}", f"cloud-feedback/{issue}/status.json"
    )
    if not feedback or feedback.get("issue_date") != issue:
        return None
    verification = feedback.get("first_reader_verification")
    if not isinstance(verification, dict) or verification.get("issue_date") != issue:
        return None
    files = verification.get("verified_files_sha256")
    if not isinstance(files, dict) or not files.get("index.html") or not files.get(f"{issue}/index.html"):
        return None
    return verification if isinstance(verification.get("confirmed_at"), str) else None


if __name__ == "__main__":
    today = datetime.now(ZoneInfo(load_policy().timezone)).date()
    site = ROOT / "site"
    retained = sorted(
        path.parent.name
        for path in site.glob("????-??-??/index.html")
        if path.is_file()
    )
    retention_floor = (
        retained[-(ARCHIVED_PREVIOUS_ISSUES + 1)]
        if len(retained) >= ARCHIVED_PREVIOUS_ISSUES + 1 else ""
    )
    gaps = list(missing_dates(site, FIRST_TRACKED_ISSUE, today))
    repository = os.getenv("GITHUB_REPOSITORY", "")
    recorded = {issue: verified_publication(repository, issue) for issue in gaps}
    print("### Missing archive pages inside the retained window")
    for issue in gaps:
        if issue >= retention_floor:
            note = " (prior publication verified)" if recorded[issue] else " (initial publication unverified)"
            print(f"- {issue}{note}")
    if retention_floor:
        print("### Older dates with no retained page")
        for issue in gaps:
            if issue >= retention_floor:
                continue
            if verification := recorded[issue]:
                print(f"- {issue}: publication verified at {verification['confirmed_at']}")
            else:
                print(f"- {issue}: publication history unknown")
