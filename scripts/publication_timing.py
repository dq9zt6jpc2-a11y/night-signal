#!/usr/bin/env python3
"""Own NIGHT SIGNAL publication timing and deadline decisions."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "night_signal_operations.json"


def parse_clock(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def minutes(value: time) -> int:
    return value.hour * 60 + value.minute


@dataclass(frozen=True)
class TimingPolicy:
    timezone: str
    publication_deadline: time
    build_timeout_minutes: int
    pages_timeout_minutes: int
    workflow_overhead_budget_minutes: int
    deadline_safety_margin_minutes: int
    observed_schedule_delay_minutes: int
    schedule_delay_contingency_minutes: int
    schedule_heartbeats_jst: tuple[time, ...]

    @property
    def runtime_budget_minutes(self) -> int:
        return (
            self.build_timeout_minutes
            + self.pages_timeout_minutes
            + self.workflow_overhead_budget_minutes
        )

    @property
    def final_collection_not_before(self) -> time:
        value = (
            minutes(self.publication_deadline)
            - self.runtime_budget_minutes
            - self.deadline_safety_margin_minutes
        )
        if value < 0:
            raise ValueError("publication timing budget crosses the previous day")
        return time(hour=value // 60, minute=value % 60)

    @property
    def schedule_delay_absorption_minutes(self) -> int:
        return (
            self.observed_schedule_delay_minutes
            + self.schedule_delay_contingency_minutes
        )


def positive_int(value: Any, name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def load_policy(path: Path = CONFIG_PATH) -> TimingPolicy:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("night_signal_operations must be an object")
    heartbeat_values = value.get("schedule_heartbeats_jst")
    if not isinstance(heartbeat_values, list) or not heartbeat_values:
        raise ValueError("schedule_heartbeats_jst must be a non-empty list")
    policy = TimingPolicy(
        timezone=str(value.get("timezone", "")),
        publication_deadline=parse_clock(str(value.get("publication_deadline", ""))),
        build_timeout_minutes=positive_int(
            value.get("build_timeout_minutes"), "build_timeout_minutes"
        ),
        pages_timeout_minutes=positive_int(
            value.get("pages_timeout_minutes"), "pages_timeout_minutes"
        ),
        workflow_overhead_budget_minutes=positive_int(
            value.get("workflow_overhead_budget_minutes"),
            "workflow_overhead_budget_minutes",
        ),
        deadline_safety_margin_minutes=positive_int(
            value.get("deadline_safety_margin_minutes"),
            "deadline_safety_margin_minutes",
        ),
        observed_schedule_delay_minutes=positive_int(
            value.get("observed_schedule_delay_minutes"),
            "observed_schedule_delay_minutes",
        ),
        schedule_delay_contingency_minutes=positive_int(
            value.get("schedule_delay_contingency_minutes"),
            "schedule_delay_contingency_minutes",
        ),
        schedule_heartbeats_jst=tuple(
            parse_clock(str(item)) for item in heartbeat_values
        ),
    )
    ZoneInfo(policy.timezone)
    heartbeat_minutes = [minutes(item) for item in policy.schedule_heartbeats_jst]
    if heartbeat_minutes != sorted(set(heartbeat_minutes)):
        raise ValueError("schedule_heartbeats_jst must be unique and ordered")
    window_start = minutes(policy.final_collection_not_before)
    if heartbeat_minutes[0] > window_start - policy.schedule_delay_absorption_minutes + 5:
        raise ValueError("earliest heartbeat does not absorb the configured schedule delay")
    if not any(window_start <= item <= window_start + 5 for item in heartbeat_minutes):
        raise ValueError("schedule needs an on-time heartbeat at the publication window")
    if max(
        later - earlier
        for earlier, later in zip(heartbeat_minutes, heartbeat_minutes[1:])
    ) > 180:
        raise ValueError("schedule heartbeat gap exceeds three hours")
    return policy


def eligible_latest_issue_dates(
    now: datetime | None = None,
    policy: TimingPolicy | None = None,
) -> set[str]:
    active_policy = policy or load_policy()
    current = (now or datetime.now(ZoneInfo(active_policy.timezone))).astimezone(
        ZoneInfo(active_policy.timezone)
    )
    dates = {current.date().isoformat()}
    if current.time() < active_policy.final_collection_not_before:
        dates.add((current.date() - timedelta(days=1)).isoformat())
    return dates


def scheduled_decision(now: datetime, policy: TimingPolicy) -> str:
    current = now.astimezone(ZoneInfo(policy.timezone))
    current_minutes = current.hour * 60 + current.minute
    if current_minutes < minutes(policy.final_collection_not_before):
        return "wait"
    if current_minutes >= minutes(policy.publication_deadline):
        return "missed"
    return "run"


def decision(now: datetime, event_name: str, policy: TimingPolicy) -> str:
    if event_name != "schedule":
        return "run"
    return scheduled_decision(now, policy)


def self_test() -> None:
    policy = load_policy()
    if policy.runtime_budget_minutes != 105:
        raise SystemExit("runtime budget must match the workflow timeout")
    if policy.schedule_delay_contingency_minutes != policy.runtime_budget_minutes:
        raise SystemExit("schedule delay contingency must cover one full runtime budget")
    if policy.final_collection_not_before != time(16, 45):
        raise SystemExit("final collection window must be derived as 16:45 JST")
    zone = ZoneInfo(policy.timezone)
    cases = {
        "2099-01-01T16:44:00+09:00": "wait",
        "2099-01-01T16:45:00+09:00": "run",
        "2099-01-01T18:59:00+09:00": "run",
        "2099-01-01T19:00:00+09:00": "missed",
    }
    for raw, expected in cases.items():
        actual = scheduled_decision(datetime.fromisoformat(raw).astimezone(zone), policy)
        if actual != expected:
            raise SystemExit(f"timing decision mismatch: {raw}: {actual} != {expected}")
    if decision(datetime.now(zone), "workflow_dispatch", policy) != "run":
        raise SystemExit("manual recovery must not be mistaken for a scheduled heartbeat")
    print("PUBLICATION TIMING SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--decision", action="store_true")
    parser.add_argument("--event-name", default="schedule")
    parser.add_argument("--now")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    policy = load_policy()
    if args.decision:
        now = (
            datetime.fromisoformat(args.now)
            if args.now
            else datetime.now(ZoneInfo(policy.timezone))
        )
        print(decision(now, args.event_name, policy))
        return 0
    print(
        json.dumps(
            {
                "timezone": policy.timezone,
                "publication_deadline": policy.publication_deadline.strftime("%H:%M"),
                "runtime_budget_minutes": policy.runtime_budget_minutes,
                "deadline_safety_margin_minutes": policy.deadline_safety_margin_minutes,
                "final_collection_not_before": policy.final_collection_not_before.strftime(
                    "%H:%M"
                ),
                "schedule_delay_absorption_minutes": policy.schedule_delay_absorption_minutes,
                "observed_schedule_delay_minutes": policy.observed_schedule_delay_minutes,
                "schedule_delay_contingency_minutes": policy.schedule_delay_contingency_minutes,
                "schedule_heartbeats_jst": [
                    item.strftime("%H:%M") for item in policy.schedule_heartbeats_jst
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
