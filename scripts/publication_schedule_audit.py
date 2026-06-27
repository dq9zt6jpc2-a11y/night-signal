#!/usr/bin/env python3
"""Fail when NIGHT SIGNAL background publication is no longer single-owner."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"
RUNTIME_WATCHDOG_WORKFLOW = ROOT / ".github" / "workflows" / "runtime-watchdog.yml"
UNATTENDED_WORKFLOW = ROOT / ".github" / "workflows" / "unattended-collection.yml"
UNATTENDED_COLLECTOR = ROOT / "scripts" / "night_signal_unattended_collect.py"


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
    unattended = UNATTENDED_WORKFLOW.read_text(encoding="utf-8")
    collector = UNATTENDED_COLLECTOR.read_text(encoding="utf-8")
    publish_times = cron_minutes(publish)
    unattended_times = cron_minutes(unattended)
    if RUNTIME_WATCHDOG_WORKFLOW.exists():
        fail("runtime-watchdog workflow is obsolete; unattended collection must be the only timed owner")
    if publish_times:
        fail(f"Pages workflow must not run on a schedule; collector owns timed publication: {publish_times}")
    if re.search(r"\n\s+push:", publish):
        fail("Pages workflow must not run on push; unattended collection must dispatch and wait for it")
    if (ROOT / ".github" / "workflows" / "preflight.yml").exists():
        fail("preflight workflow is obsolete; unattended collection owns readiness")
    if "scripts/night_signal_publish.py" not in publish:
        fail("Pages workflow must use the canonical publication owner")
    if '--deploy-existing' not in publish:
        fail("Pages workflow must deploy only committed, freshness-validated state")
    if "OPENAI_API_KEY" in publish:
        fail("Pages workflow must not pretend to own live collection")
    unattended_pre_20 = [
        value
        for value in unattended_times
        if 18 * 60 <= value < 20 * 60
    ]
    if len(unattended_pre_20) < 5 or unattended_pre_20[0] > 18 * 60 + 5:
        fail(
            "unattended collection needs five staged attempts starting by "
            f"18:05 JST: {unattended_times}"
        )
    if max(unattended_pre_20) < 19 * 60 + 50:
        fail(f"unattended collection needs a final pre-20:00 JST attempt: {unattended_times}")
    if "night-signal-unattended-collection" not in unattended:
        fail("unattended workflow must own the single background concurrency group")
    if "cancel-in-progress: false" not in unattended:
        fail("unattended workflow must not cancel an in-flight publication attempt")
    if "timeout-minutes: 105" not in unattended or "timeout-minutes: 70" not in unattended:
        fail("unattended workflow must cap collection and job runtime")
    if "NIGHT_SIGNAL_MODEL_TIMEOUT_SECONDS: 240" in unattended or "NIGHT_SIGNAL_MODEL_RETRIES: 5" in unattended:
        fail("unattended workflow must not override model calls into long retry loops")
    if "NIGHT_SIGNAL_MODEL_CONCURRENCY: 2" not in unattended:
        fail("unattended workflow must parallelize category extraction without broadening calls")
    if "NIGHT_SIGNAL_SKIP_MODEL" in collector:
        fail("a one-shot canary must not disable all category model extraction")
    canary_step = unattended.split("- name: Verify GitHub Models access", 1)[-1].split(
        "- name: Stop after canary", 1
    )[0]
    if "inputs.canary_only == true" not in canary_step:
        fail("the GitHub Models canary must run only for an explicit canary request")
    if "models: read" not in unattended or "night_signal_unattended_collect.py" not in unattended:
        fail("unattended workflow must use GitHub Models without an external API secret")
    if "--event-name workflow_dispatch" in unattended:
        fail("unattended workflow must pass the real GitHub event name when resolving the issue date")
    if '--event-name "$GITHUB_EVENT_NAME"' not in unattended:
        fail("unattended workflow must resolve the issue date from the real GitHub event")
    if "contents: write" not in unattended or "git push origin HEAD:main" not in unattended:
        fail("unattended workflow must be able to commit the audited issue")
    if "actions: write" not in unattended or "gh workflow run pages.yml" not in unattended:
        fail("unattended workflow must explicitly dispatch Pages after bot push")
    if "gh run watch \"$RUN_ID\" --exit-status" not in unattended or "--workflow pages.yml" not in unattended:
        fail("unattended workflow must wait for Pages publication before succeeding")
    if "python3 scripts/night_signal_runtime_audit.py \"$ISSUE_DATE\"" not in unattended:
        fail("unattended workflow must classify readiness before and after collection")
    if "python3 scripts/publication_audit.py \"$ISSUE_DATE\"" not in unattended:
        fail("unattended workflow must run the public/local publication audit after Pages succeeds")
    print(
        "PUBLICATION SCHEDULE AUDIT PASSED: "
        f"pages_jst={publish_times}, unattended_jst={unattended_times}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
