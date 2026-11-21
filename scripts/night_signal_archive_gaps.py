#!/usr/bin/env python3
"""Reconstruct outstanding archive dates without relying on a scheduled run."""

from datetime import date, datetime, timedelta

from publication_timing import ROOT, load_policy
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
    gaps = list(missing_dates(ROOT / "site", FIRST_TRACKED_ISSUE, today))
    print("### Historical issues missing from the production tree")
    for issue in gaps:
        print(f"- {issue}")
    if not gaps:
        print("No missing archive files.")
