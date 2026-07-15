#!/usr/bin/env python3
"""Verify that adjacent daily runs stay fresh while recovery stays bounded."""

from __future__ import annotations

import json
from datetime import datetime

import night_signal_evidence as evidence_store
import night_signal_publish as publish
import publication_timing as timing


def evidence(checked_at_jst: str) -> dict[str, str]:
    return {
        "checked_at_jst": checked_at_jst,
        "collector_contract_version": evidence_store.collector_contract_version(),
    }


def main() -> int:
    policy = timing.load_policy()
    first_day = evidence("2099-01-01T17:20:00+09:00")
    second_day_pre_final = evidence("2099-01-02T15:30:00+09:00")
    second_day_final = evidence("2099-01-02T17:20:00+09:00")
    checks = {
        "day1_scheduled_recovery_reuses_final_evidence": publish.evidence_reusable(
            first_day,
            "2099-01-01",
            now=datetime.fromisoformat("2099-01-01T18:50:00+09:00"),
            require_final=True,
        ),
        "day2_rejects_day1_evidence": not publish.evidence_reusable(
            first_day,
            "2099-01-02",
            now=datetime.fromisoformat("2099-01-02T17:20:00+09:00"),
            require_final=True,
        ),
        "day2_rejects_pre_final_evidence": not publish.evidence_reusable(
            second_day_pre_final,
            "2099-01-02",
            now=datetime.fromisoformat("2099-01-02T17:20:00+09:00"),
            require_final=True,
        ),
        "day2_accepts_its_own_final_evidence": publish.evidence_reusable(
            second_day_final,
            "2099-01-02",
            now=datetime.fromisoformat("2099-01-02T18:50:00+09:00"),
            require_final=True,
        ),
        "day1_publication_window_runs": timing.scheduled_decision(
            datetime.fromisoformat("2099-01-01T17:00:00+09:00"),
            policy,
        )
        == "run",
        "day2_publication_window_runs": timing.scheduled_decision(
            datetime.fromisoformat("2099-01-02T17:00:00+09:00"),
            policy,
        )
        == "run",
        "late_heartbeat_is_checkpoint_only": (
            timing.scheduled_decision(
                datetime.fromisoformat("2099-01-02T17:17:00+09:00"),
                policy,
            )
            == "run"
            and not timing.scheduled_fresh_collection_allowed(
                datetime.fromisoformat("2099-01-02T17:17:00+09:00"),
                policy,
            )
        ),
        "three_previous_issues_remain_available": publish.ARCHIVED_PREVIOUS_ISSUES
        == 3,
    }
    failed = [name for name, passed in checks.items() if not passed]
    print(
        json.dumps(
            {
                "verdict": "pass" if not failed else "fail",
                "checks": checks,
                "failures": failed,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
