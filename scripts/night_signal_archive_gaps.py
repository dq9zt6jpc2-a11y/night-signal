#!/usr/bin/env python3
"""Reconstruct outstanding archive dates without relying on a scheduled run."""

from datetime import date, datetime, timedelta

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
    print("### Missing issues inside the retained archive window")
    for issue in gaps:
        if issue >= retention_floor:
            print(f"- {issue}")
    if retention_floor:
        print("### Older dates requiring publication records to establish status")
        for issue in gaps:
            if issue < retention_floor:
                print(f"- {issue}")
