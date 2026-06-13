#!/usr/bin/env python3
"""Fail when NIGHT SIGNAL no longer has enough pre-20:00 JST publish attempts."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
PREFLIGHT_WORKFLOW = ROOT / ".github" / "workflows" / "preflight.yml"
RUNTIME_WATCHDOG_WORKFLOW = ROOT / ".github" / "workflows" / "runtime-watchdog.yml"


def cron_minutes(text: str) -> list[int]:
    values: list[int] = []
    for minute, hour in re.findall(r'cron:\s*"(\d{2})\s+(\d{2})\s+\*\s+\*\s+\*"', text):
        utc_minutes = int(hour) * 60 + int(minute)
        values.append((utc_minutes + 9 * 60) % (24 * 60))
    return sorted(values)


def fail(message: str) -> None:
    print(f"PUBLICATION SCHEDULE AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    publish = PUBLISH_WORKFLOW.read_text(encoding="utf-8")
    preflight = PREFLIGHT_WORKFLOW.read_text(encoding="utf-8")
    runtime_watchdog = RUNTIME_WATCHDOG_WORKFLOW.read_text(encoding="utf-8")
    publish_times = cron_minutes(publish)
    preflight_times = cron_minutes(preflight)
    watchdog_times = cron_minutes(runtime_watchdog)
    pre_20 = [value for value in publish_times if 18 * 60 <= value <= 20 * 60]
    if len(pre_20) < 4:
        fail(f"need at least four staged publish attempts from 18:00 through 20:00 JST: {publish_times}")
    if pre_20[0] > 18 * 60 + 30:
        fail(f"first publish attempt must be no later than 18:30 JST: {publish_times}")
    if pre_20[-2] > 19 * 60 + 45:
        fail(f"penultimate publish attempt must be no later than 19:45 JST: {publish_times}")
    if not preflight_times or preflight_times[0] > 17 * 60:
        fail(f"first preflight must run by 17:00 JST: {preflight_times}")
    if "scripts/night_signal_publish.py" not in publish or "scripts/night_signal_publish.py" not in preflight:
        fail("both workflows must use the canonical publication owner")
    if '--deploy-existing' not in publish:
        fail("Pages workflow must deploy only committed, freshness-validated state")
    if "OPENAI_API_KEY" in publish:
        fail("Pages workflow must not pretend to own live collection")
    if not watchdog_times or watchdog_times[0] > 19 * 60:
        fail(f"independent runtime watchdog must detect a missing issue before 19:00 JST: {watchdog_times}")
    if "night_signal_runtime_audit.py" not in runtime_watchdog or "--fail-on-blocker" not in runtime_watchdog:
        fail("runtime watchdog must fail independently when no honest collection path exists")
    print(
        "PUBLICATION SCHEDULE AUDIT PASSED: "
        f"publish_jst={publish_times}, preflight_jst={preflight_times}, "
        f"watchdog_jst={watchdog_times}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
