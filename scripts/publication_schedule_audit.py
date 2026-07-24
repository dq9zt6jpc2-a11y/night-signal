#!/usr/bin/env python3
"""Verify the zero-additional-charge collection/review/publication boundary."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import publication_timing as timing


ROOT = Path(__file__).resolve().parents[1]
PAGES = ROOT / ".github" / "workflows" / "pages.yml"
COLLECTION = ROOT / ".github" / "workflows" / "unattended-collection.yml"
CLOUD_PUBLICATION = ROOT / ".github" / "workflows" / "cloud-review-publish.yml"
PUBLICATION_WATCHDOG = ROOT / ".github" / "workflows" / "publication-watchdog.yml"
RETIRED_MODEL_WORKFLOW = ROOT / ".github" / "workflows" / "model-catalog-evaluation.yml"
PLUS_EDITOR = ROOT / "scripts" / "night_signal_plus_editor.py"
PUBLISH_DRIVER = ROOT / "scripts" / "night_signal_publish.py"
AI_POLICY = ROOT / "config" / "night_signal_ai.json"
RUNBOOK = ROOT / "docs" / "night_signal_plus_runbook.md"
WEB_OWNER_RUNBOOK = ROOT / "docs" / "night_signal_web_owner.md"
CLOUD_HANDOFF = ROOT / "scripts" / "night_signal_cloud_handoff.py"
CLOUD_REVIEW = ROOT / "scripts" / "night_signal_cloud_review.py"
CLOUD_FEEDBACK = ROOT / "scripts" / "night_signal_cloud_feedback.py"
OPERATIONAL_AUDIT = ROOT / "scripts" / "night_signal_operational_audit.py"
BASIC_DESIGN = ROOT / "docs" / "night-signal-basic-design.md"
REQUIREMENTS = ROOT / "docs" / "night-signal-requirements.md"
OPERATIONS_POLICY = ROOT / "config" / "night_signal_operations.json"


def fail(message: str) -> None:
    print(f"PUBLICATION SCHEDULE AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def cron_minutes(text: str) -> list[int]:
    values = []
    for minute, hour in re.findall(
        r'cron:\s*"(\d{2})\s+(\d{2})\s+\*\s+\*\s+\*"',
        text,
    ):
        values.append((int(hour) * 60 + int(minute) + 9 * 60) % (24 * 60))
    return sorted(values)


def ordered(text: str, *labels: str) -> bool:
    positions = [text.find(label) for label in labels]
    return all(position >= 0 for position in positions) and positions == sorted(positions)


def main() -> int:
    pages = PAGES.read_text(encoding="utf-8")
    collection = COLLECTION.read_text(encoding="utf-8")
    cloud_publication = CLOUD_PUBLICATION.read_text(encoding="utf-8")
    publication_watchdog = PUBLICATION_WATCHDOG.read_text(encoding="utf-8")
    plus_editor = PLUS_EDITOR.read_text(encoding="utf-8")
    publish_driver = PUBLISH_DRIVER.read_text(encoding="utf-8")
    policy = timing.load_policy()

    if cron_minutes(pages) or re.search(r"\n\s+push:", pages):
        fail("Pages must remain dispatch-only")
    if "--deploy-existing" not in pages:
        fail("Pages may deploy only committed audited issue state")
    expected_heartbeats = sorted(
        timing.minutes(value) for value in policy.schedule_heartbeats_jst
    )
    if cron_minutes(collection) != expected_heartbeats:
        fail(
            "Evidence heartbeats do not match timing policy: "
            f"{cron_minutes(collection)} != {expected_heartbeats}"
        )
    if "night-signal-evidence-collection" not in collection:
        fail("Evidence collection needs one non-cancelling owner")
    if "cancel-in-progress: false" not in collection:
        fail("a delayed Evidence run must not cancel an active collector")
    if "contents: write" not in collection:
        fail("Evidence collection cannot publish the isolated cloud handoff")
    if "--near-window-wait-seconds" not in collection:
        fail("near-window scheduled runners are still discarded before 16:45")
    if "timeout-minutes: 105" not in collection:
        fail("Evidence owner timeout does not cover bounded waiting plus collection")
    if "models: read" in collection or "models.github.ai" in collection:
        fail("active collection must not depend on retired GitHub Models")
    if "api.openai.com" in collection or "OPENAI_API_KEY" in collection:
        fail("active collection must not enter a separately billed OpenAI API path")
    for forbidden in (
        "git push origin HEAD:main",
        "gh workflow run pages.yml",
        "night_signal_model_audit.py",
        "night_signal_editor.py",
    ):
        if forbidden in collection:
            fail(f"Evidence-only workflow contains forbidden production work: {forbidden}")
    if not ordered(
        collection,
        "Guard against a queued duplicate collector",
        "Evaluate final collection window",
        "Detect an already verified publication",
        "Detect a reusable final Evidence artifact",
        "Reuse completed Evidence without recollection",
        "Collect complete web Evidence and prepare the Plus review packet",
        "Save the complete Evidence and compact review packet",
        "Publish the immutable PC-independent review handoff",
        "Report zero-cost collection boundary",
    ):
        fail("Evidence collection stages are out of order")
    for required in (
        "scripts/night_signal_collect.py",
        "scripts/night_signal_plus_editor.py",
        "--prepare",
        "editor_packet.json",
        "artifact_ready",
        "retention-days: 3",
        "if-no-files-found: error",
        "scripts/night_signal_cloud_handoff.py",
        "--restore-only",
        "Repository model API requests: 0",
        "Additional paid API requests: 0",
    ):
        if required not in collection:
            fail(f"Evidence workflow is missing {required}")
    if RETIRED_MODEL_WORKFLOW.exists():
        fail("retired GitHub Models evaluation workflow is still active")
    for retired_path in (
        ROOT / "scripts" / "night_signal_models.py",
        ROOT / "scripts" / "night_signal_model_audit.py",
        ROOT / "scripts" / "night_signal_model_eval.py",
        ROOT / "config" / "night_signal_models.json",
    ):
        if retired_path.exists():
            fail(f"retired GitHub Models component still exists: {retired_path.name}")
    for required_path in (
        AI_POLICY,
        RUNBOOK,
        WEB_OWNER_RUNBOOK,
        CLOUD_HANDOFF,
        CLOUD_REVIEW,
        CLOUD_FEEDBACK,
        CLOUD_PUBLICATION,
        PUBLICATION_WATCHDOG,
        OPERATIONAL_AUDIT,
        BASIC_DESIGN,
        REQUIREMENTS,
    ):
        if not required_path.exists():
            fail(f"required PC-independent component is missing: {required_path.name}")
    ai_policy = json.loads(AI_POLICY.read_text(encoding="utf-8"))
    production_editor = ai_policy.get("production_editor", {})
    if ai_policy.get("additional_paid_services_allowed") is not False:
        fail("additional paid AI services must be disabled")
    if production_editor.get("model") != "gpt-5.6-terra":
        fail("production Plus review must use the evaluated quality/efficiency route")
    if production_editor.get("reasoning_effort") != "low":
        fail("routine evidence review must use bounded reasoning")
    if production_editor.get("surface") != "chatgpt-web-scheduled-task":
        fail("production editor surface drifted back to a local owner")
    if production_editor.get("local_pc_required") is not False:
        fail("production editor must not require the local PC")
    if production_editor.get("activation_must_be_proven_by_remote_heartbeat") is not True:
        fail("static architecture must not be mistaken for Web-owner activation")
    runbook = RUNBOOK.read_text(encoding="utf-8")
    for required in (
        "scripts/night_signal_review_artifact.py",
        "change only the named request/event",
        "do not recollect or re-review",
        "topic_value_class` must be one of",
        "17:50 Work-mode Web task",
        "18:25 Work-mode Web task",
        "official OpenAI",
    ):
        if required.casefold() not in runbook.casefold():
            fail(f"Plus runbook is missing recovery contract: {required}")
    web_runbook = WEB_OWNER_RUNBOOK.read_text(encoding="utf-8")
    for required in (
        "never the production owner",
        "ChatGPT Web Scheduled task",
        "Always allow",
        "Run now",
        "night-signal-evidence-ISSUE_DATE",
        "night-signal-review-ISSUE_DATE",
        "night-signal-feedback-ISSUE_DATE",
        "Candidate events are not capped",
        "computer may be shut down",
        "correct every named",
        "night-signal-owner-status",
        "night-signal-cloud-owner-status-v1",
        "both show ISSUE_DATE",
        "Do not read Evidence",
        "spend review tokens",
        "current blob SHA",
        "retry only that same liveness write once",
        "must never pause",
    ):
        if required.casefold() not in web_runbook.casefold():
            fail(f"Web owner runbook is missing: {required}")

    operations = json.loads(OPERATIONS_POLICY.read_text(encoding="utf-8"))
    owner_heartbeats = operations.get("editor_owner_heartbeats_jst")
    if owner_heartbeats != ["17:50", "18:25"]:
        fail("Web-owner heartbeat policy must contain only 17:50 and 18:25 JST")
    owner_activation = operations.get("editor_owner_activation", {})
    if owner_activation != {
        "persistent_github_write_permission": True,
        "remote_heartbeat_required": True,
        "run_now_proof_required_before_production": True,
    }:
        fail("Web-owner activation proof policy is incomplete")
    if operations.get("reliability_report_retention_days") != 30:
        fail("operational reliability history must be retained for 30 days")
    watchdog_heartbeats = operations.get("publication_watchdog_heartbeats_jst")
    if watchdog_heartbeats != ["18:00", "18:35", "18:50", "19:05"]:
        fail("publication watchdog policy drifted from the bounded recovery window")
    expected_watchdog_minutes = sorted(
        timing.minutes(timing.parse_clock(value)) for value in watchdog_heartbeats
    )
    if cron_minutes(publication_watchdog) != expected_watchdog_minutes:
        fail("publication watchdog cron does not match the operations policy")
    for required in (
        "night_signal_operational_audit.py",
        "workflow_run:",
        "Publish reviewed NIGHT SIGNAL",
        "recovery_attempt=1",
        "No Evidence recollection or model review was repeated",
        "retention-days: 30",
        "timeout-minutes: 120",
    ):
        if required not in publication_watchdog:
            fail(f"publication watchdog is missing: {required}")
    if "models.github.ai" in publication_watchdog or "api.openai.com" in publication_watchdog:
        fail("publication watchdog contains a paid model path")

    basic_design = BASIC_DESIGN.read_text(encoding="utf-8")
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    for stale in (
        "Codex automationを唯一の編集・検証・commit・公開owner",
        "local Codex Plus owner",
        "ChatGPT Plusに含まれるCodex automationは編集",
    ):
        if stale in basic_design or stale in requirements:
            fail(f"stale local production-owner contract remains: {stale}")

    for forbidden in ("models: read", "models.github.ai", "api.openai.com", "OPENAI_API_KEY"):
        if forbidden in cloud_publication:
            fail(f"cloud publication entered a paid/retired AI path: {forbidden}")
    if cron_minutes(cloud_publication):
        fail("deterministic cloud publication must be event-driven, not a duplicate timer")
    if "timeout-minutes: 105" not in cloud_publication:
        fail("cloud publication timeout does not cover gates plus one Pages recovery")
    for required in (
        'branches:\n      - "night-signal-review-*"',
        '"cloud-review/**/editor_review.json"',
        '"cloud-review/**/editor_correction.json"',
        "Checkout trusted main",
        "--restore-only",
        "night_signal_cloud_review.py",
        "--correction-path",
        "--apply-review",
        "Require the same trusted main before committing",
        "Bounded deterministic base-race recovery attempt",
        "Push once or queue one same-review rebuild after a race",
        "Dispatch Pages exactly once",
        "Retry the same committed Pages deployment once",
        "publication_audit.py",
        "night_signal_cloud_feedback.py",
        "--recovery-attempt \"$RECOVERY_ATTEMPT\"",
    ):
        if required not in cloud_publication:
            fail(f"cloud publication is missing: {required}")
    if not ordered(
        cloud_publication,
        "Checkout trusted main",
        "Stop when this exact issue is already verified live",
        "Restore final Evidence without collection or model work",
        "Validate cloud provenance and apply every reviewed event",
        "Render and run deterministic publication gates",
        "Require the same trusted main before committing",
        "Commit the complete audited publication atomically",
        "Push once or queue one same-review rebuild after a race",
        "Dispatch Pages exactly once",
        "Verify origin, root URL, and dated URL",
        "Publish compact success or validator feedback for recovery",
    ):
        fail("cloud publication recovery stages are out of order")
    handoff_source = CLOUD_HANDOFF.read_text(encoding="utf-8")
    review_source = CLOUD_REVIEW.read_text(encoding="utf-8")
    feedback_source = CLOUD_FEEDBACK.read_text(encoding="utf-8")
    for source, label in (
        (handoff_source, "cloud handoff"),
        (review_source, "cloud review"),
        (feedback_source, "cloud feedback"),
    ):
        if "models." + "github.ai" in source or "api." + "openai.com" in source:
            fail(f"{label} helper contains a paid/retired model endpoint")
    for required in (
        "MAX_PART_BYTES = 850_000",
        "immutable handoff branch",
        "packet_sha256",
        '"remote_verified": True',
    ):
        if required not in handoff_source:
            fail(f"cloud handoff is missing: {required}")
    for required in (
        'EXECUTION_SURFACE = "chatgpt-web-scheduled-task"',
        "Evidence hash does not match",
        "within_review_window",
        "or before 06:00 JST the next day",
    ):
        if required not in review_source:
            fail(f"cloud review validation is missing: {required}")
    if "models.request(" in plus_editor or "urllib.request" in plus_editor:
        fail("Plus importer must be deterministic and network-free")
    collect_start = publish_driver.find("def collect_and_build(")
    assemble_start = publish_driver.find("def assemble_and_render(")
    collect_body = publish_driver[collect_start:assemble_start]
    if "night_signal_plus_editor.py" not in collect_body:
        fail("canonical publish driver does not hand unresolved Evidence to Plus review")
    if "Editor model access" in collect_body:
        fail("canonical publish driver can still enter the retired model editor")
    print(
        "PUBLICATION STATIC CONFIG AUDIT PASSED: "
        f"window={policy.final_collection_not_before.strftime('%H:%M')}-"
        f"{policy.publication_deadline.strftime('%H:%M')}, "
        "architecture-ready=true, live-activation-proven=false, "
        "activation-proof=remote-heartbeat-required, "
        "collector=github-actions, editor=chatgpt-web, publisher=github-actions, "
        "local-pc-required=false, paid-api-requests=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
