#!/usr/bin/env python3
"""Report whether independent editing can fit inside today's publication window."""

import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from publication_timing import CONFIG_PATH, load_policy


def assess(report, now, policy, owner_slots, trial_minutes):
    zone = ZoneInfo(policy.timezone)
    now = now.astimezone(zone)
    issue = date.fromisoformat(report["issue_date"])
    deadline = datetime.combine(issue, policy.publication_deadline, zone)
    owner_grace = timedelta(minutes=policy.workflow_overhead_budget_minutes)
    if report.get("stage") == "review_missing_owner_heartbeat_missing":
        # Once the first owner has missed its heartbeat, let the independent
        # editor use the existing early watchdog and preserve time for a retry.
        handoff_slot = min(owner_slots)
    else:
        handoff_slot = max(owner_slots)
    ready_after = datetime.combine(issue, handoff_slot, zone) + owner_grace
    # If neither owner recorded even yesterday, waiting for a second clock
    # trigger after the Evidence collector finishes can lose the whole window.
    last_dates = report.get("last_owner_issue_dates", {})
    yesterday = (issue - timedelta(days=1)).isoformat()
    if (report.get("stage") == "review_missing_owner_heartbeat_missing"
            and all(last_dates.get(role) and last_dates[role] < yesterday
                    for role in ("primary", "recovery"))):
        ready_after = datetime.combine(issue, policy.final_collection_not_before, zone)
    # Evidence is already sealed. Reserve time for Pages, orchestration, and safety.
    downstream = policy.pages_timeout_minutes + policy.workflow_overhead_budget_minutes + policy.deadline_safety_margin_minutes
    latest_single = deadline - timedelta(minutes=downstream + trial_minutes)
    latest_with_retry = latest_single - timedelta(minutes=trial_minutes)

    if issue != now.date():
        reason = "different_issue_day"
    elif report.get("published") or report.get("review_ready") or report.get("correction_ready"):
        reason = "existing_publication_or_review"
    elif report.get("evidence_ready") is not True:
        reason = "final_evidence_missing"
    elif report.get("needs_editor_action") is not True:
        reason = "no_editor_action_requested"
    elif now < ready_after:
        reason = "waiting_for_web_recovery_window"
    elif now > latest_single:
        reason = "insufficient_deadline_budget"
    else:
        reason = "eligible_for_independent_editor"
    return {
        "issue_date": issue.isoformat(),
        "checked_at": now.isoformat(),
        "reason": reason,
        "earliest_handoff": ready_after.isoformat(),
        "latest_single_trial": latest_single.isoformat(),
        "latest_trial_with_retry": latest_with_retry.isoformat(),
        "retry_fits": reason == "eligible_for_independent_editor" and now <= latest_with_retry,
        "dispatched": False,
    }


if __name__ == "__main__":
    report = json.loads(Path(sys.argv[1]).read_text())
    config = json.loads(CONFIG_PATH.read_text())
    slots = [time.fromisoformat(slot) for slot in config["editor_owner_heartbeats_jst"]]
    result = assess(report, datetime.now(ZoneInfo(config["timezone"])), load_policy(), slots,
                    config["independent_editor_trial_budget_minutes"])
    print(json.dumps(result))
