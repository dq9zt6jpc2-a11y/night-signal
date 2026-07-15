#!/usr/bin/env python3
"""Run the single NIGHT SIGNAL collection-to-publication pipeline."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import night_signal_state as state
import night_signal_runtime_audit as runtime
import night_signal_evidence as evidence_store
import night_signal_core as core
import publication_timing as timing


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
ARCHIVED_PREVIOUS_ISSUES = 3


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL PUBLISH FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def retained_history_dates(
    available_dates: set[str],
    issue_date: str,
) -> set[str]:
    """Return the current issue and its three most recent predecessors."""
    prior_dates = sorted(
        (value for value in available_dates if value < issue_date),
        reverse=True,
    )[:ARCHIVED_PREVIOUS_ISSUES]
    return {issue_date, *prior_dates}


def jst_today() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()


def eligible_latest_issue_dates(now: datetime | None = None) -> set[str]:
    return timing.eligible_latest_issue_dates(now)


def require_jst_current_issue(
    issue_date: str,
    *,
    now: datetime | None = None,
) -> None:
    eligible = eligible_latest_issue_dates(now)
    if issue_date not in eligible:
        fail(
            "refusing to publish an ineligible issue as latest: "
            f"{issue_date} not in {sorted(eligible)}"
        )


def validate_issue_date(issue_date: str) -> str:
    if not issue_date or len(issue_date) != 10:
        fail(f"invalid issue date: {issue_date}")
    try:
        datetime.strptime(issue_date, "%Y-%m-%d")
    except ValueError:
        fail(f"invalid issue date: {issue_date}")
    return issue_date


def resolve_issue_date(
    *,
    event_name: str,
    requested_issue_date: str,
) -> str:
    requested = requested_issue_date.strip()
    if requested:
        if event_name and event_name != "workflow_dispatch":
            fail("manual issue date override is only allowed for workflow_dispatch")
        issue_date = validate_issue_date(requested)
        require_jst_current_issue(issue_date)
        return issue_date
    issue_date = validate_issue_date(jst_today())
    require_jst_current_issue(issue_date)
    return issue_date


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command), file=sys.stderr)
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if check and result.returncode != 0:
        fail("command failed: " + " ".join(command))
    return result


def state_dir(issue_date: str) -> Path:
    return STATE_ROOT / issue_date


def has_evidence(issue_date: str) -> bool:
    return (state_dir(issue_date) / "evidence.json").exists()


def fresh_evidence(
    issue_date: str,
    *,
    allow_expired_final: bool = False,
) -> bool:
    evidence_path = state_dir(issue_date) / "evidence.json"
    if not evidence_path.exists():
        return False
    try:
        bundle = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    try:
        report = evidence_store.validate_bundle(bundle, issue_date)
    except evidence_store.EvidenceContractError:
        return False
    if core.remaining_editor_coverage_gaps(bundle, report):
        return False
    return evidence_reusable(
        bundle,
        issue_date,
        now=datetime.now(ZoneInfo("Asia/Tokyo")),
        allow_expired_final=allow_expired_final,
    )


def evidence_reusable(
    bundle: dict[str, Any],
    issue_date: str,
    *,
    now: datetime,
    allow_expired_final: bool = False,
) -> bool:
    if bundle.get("collector_contract_version") != evidence_store.collector_contract_version():
        return False
    try:
        checked = datetime.fromisoformat(str(bundle["checked_at_jst"]))
    except (KeyError, TypeError, ValueError):
        return False
    if checked.tzinfo is None:
        return False
    checked = checked.astimezone(ZoneInfo("Asia/Tokyo"))
    current = now.astimezone(ZoneInfo("Asia/Tokyo"))
    if checked.date().isoformat() != issue_date or current < checked:
        return False
    if current.date() == checked.date():
        if current - checked <= timedelta(hours=4):
            return True
        final_cutoff = datetime.combine(
            checked.date(),
            timing.load_policy().final_collection_not_before,
            tzinfo=ZoneInfo("Asia/Tokyo"),
        )
        return allow_expired_final and checked >= final_cutoff
    previous_date = current.date() - timedelta(days=1)
    final_cutoff = datetime.combine(
        checked.date(),
        timing.load_policy().final_collection_not_before,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
    return (
        checked.date() == previous_date
        and current.time() < timing.load_policy().final_collection_not_before
        and checked >= final_cutoff
    )


def issue_matches_evidence(issue_date: str) -> bool:
    base = state_dir(issue_date)
    evidence_path = base / "evidence.json"
    issue_path = base / "issue.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        issue = json.loads(issue_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    manifest = issue.get("coverage_manifest")
    if not isinstance(manifest, dict) or manifest.get(
        "editor_contract_sha256"
    ) != state.editor_contract_sha256():
        return False
    try:
        state.validate_issue_state(issue, issue_path, evidence)
    except SystemExit:
        return False
    return True


def collect_and_build(
    issue_date: str,
    *,
    reuse_evidence: bool,
    reprocess_existing: bool = False,
    reedit_published: bool = False,
) -> None:
    evidence_is_reusable = reuse_evidence and fresh_evidence(
        issue_date,
        allow_expired_final=reedit_published,
    )
    if reprocess_existing:
        if not evidence_is_reusable or not issue_matches_evidence(issue_date):
            fail(
                "deterministic reprocessing requires a validated issue and fresh "
                "reusable Evidence"
            )
        run(
            [
                sys.executable,
                "scripts/night_signal_editor.py",
                issue_date,
                "--postprocess-existing",
            ]
        )
        return
    if reedit_published and not evidence_is_reusable:
        fail("published-issue re-edit requires reusable final same-day Evidence")
    if evidence_is_reusable and issue_matches_evidence(issue_date):
        return
    if not (os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")):
        fail("GITHUB_TOKEN is required for Editor model access")
    if not evidence_is_reusable:
        run([sys.executable, "scripts/night_signal_collect.py", issue_date])
    if not has_evidence(issue_date):
        fail(f"collection did not create evidence.json for {issue_date}")
    run([sys.executable, "scripts/night_signal_editor.py", issue_date])


def assemble_and_render(issue_date: str) -> None:
    base = state_dir(issue_date)
    if not (base / "issue.json").exists():
        fail(f"{issue_date} has no issue state")
    run([sys.executable, "scripts/night_signal_state.py", "--generate-issue", str(base / "issue.json")])


def collection_freshness(
    issue_date: str,
    *,
    now: datetime | None = None,
    require_evening_refresh: bool,
    allow_expired_current: bool = False,
) -> dict[str, Any]:
    issue = json.loads((state_dir(issue_date) / "issue.json").read_text(encoding="utf-8"))
    manifest = issue.get("coverage_manifest")
    if not isinstance(manifest, dict):
        fail("issue state missing coverage_manifest")
    return validate_collection_freshness(
        manifest,
        issue_date,
        now=now or datetime.now(ZoneInfo("Asia/Tokyo")),
        require_evening_refresh=require_evening_refresh,
        allow_expired_current=allow_expired_current,
    )


def validate_collection_freshness(
    manifest: dict[str, Any],
    issue_date: str,
    *,
    now: datetime,
    require_evening_refresh: bool,
    allow_expired_current: bool = False,
) -> dict[str, Any]:
    value = manifest.get("collection_completed_at_jst")
    if not isinstance(value, str):
        fail("coverage manifest missing collection_completed_at_jst")
    try:
        completed = datetime.fromisoformat(value)
    except ValueError:
        fail(f"invalid collection_completed_at_jst: {value}")
    current = now.astimezone(ZoneInfo("Asia/Tokyo"))
    if completed.tzinfo is None:
        fail("collection_completed_at_jst must include a timezone")
    completed = completed.astimezone(ZoneInfo("Asia/Tokyo"))
    if completed.date().isoformat() != issue_date:
        fail(f"collection date mismatch: {completed.isoformat()} != {issue_date}")
    if completed > current + timedelta(minutes=5):
        fail(f"collection completion is in the future: {completed.isoformat()}")
    if (
        issue_date == current.date().isoformat()
        and current - completed > timedelta(hours=4)
        and not allow_expired_current
    ):
        fail(f"collection is too old for publication: {completed.isoformat()}")
    final_cutoff = datetime.combine(
        completed.date(),
        timing.load_policy().final_collection_not_before,
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
    if require_evening_refresh and completed < final_cutoff:
        fail(
            "final publication requires a fresh collection completed at or after "
            f"{final_cutoff.isoformat()}; got {completed.isoformat()}"
        )
    mode = manifest.get("collection_mode")
    if mode != "github_models_unattended":
        fail(f"unsupported collection_mode for publication: {mode}")
    return {
        "collection_completed_at_jst": completed.isoformat(),
        "collection_mode": mode,
        "evening_refresh": completed >= final_cutoff,
    }


def self_test() -> None:
    if retained_history_dates(
        {"2098-12-31", "2099-01-01", "2099-01-02", "2099-01-03", "2099-01-04"},
        "2099-01-04",
    ) != {"2099-01-01", "2099-01-02", "2099-01-03", "2099-01-04"}:
        fail("publication history did not retain current plus three prior issues")
    try:
        require_jst_current_issue("1900-01-01")
    except SystemExit:
        pass
    else:
        fail("stale issue date must never be publishable as latest")
    recovery_now = datetime.fromisoformat("2099-01-02T02:00:00+09:00")
    require_jst_current_issue("2099-01-01", now=recovery_now)
    try:
        require_jst_current_issue(
            "2099-01-01",
            now=datetime.fromisoformat("2099-01-02T16:45:00+09:00"),
        )
    except SystemExit:
        pass
    else:
        fail("previous issue recovery overlapped the current collection window")
    current = datetime.fromisoformat("2099-01-01T18:50:00+09:00")
    fresh = {
        "collection_completed_at_jst": "2099-01-01T17:20:00+09:00",
        "collection_mode": "github_models_unattended",
    }
    result = validate_collection_freshness(
        fresh,
        "2099-01-01",
        now=current,
        require_evening_refresh=True,
    )
    if not result["evening_refresh"]:
        fail("fresh evening collection was rejected")
    expired_evening = {
        "collection_completed_at_jst": "2099-01-01T17:20:00+09:00",
        "collection_mode": "github_models_unattended",
    }
    expired_now = datetime.fromisoformat("2099-01-01T22:30:00+09:00")
    try:
        validate_collection_freshness(
            expired_evening,
            "2099-01-01",
            now=expired_now,
            require_evening_refresh=True,
        )
    except SystemExit:
        pass
    else:
        fail("an expired collection passed without a published-issue redeploy gate")
    redeploy_result = validate_collection_freshness(
        expired_evening,
        "2099-01-01",
        now=expired_now,
        require_evening_refresh=True,
        allow_expired_current=True,
    )
    if not redeploy_result["evening_refresh"]:
        fail("a verified published issue could not be redeployed")
    stale = dict(fresh)
    stale["collection_completed_at_jst"] = "2099-01-01T16:44:00+09:00"
    try:
        validate_collection_freshness(
            stale,
            "2099-01-01",
            now=current,
            require_evening_refresh=True,
        )
    except SystemExit:
        pass
    else:
        fail("pre-final collection must not pass final deployment")
    reusable = {
        "checked_at_jst": "2099-01-01T17:20:00+09:00",
        "collector_contract_version": evidence_store.collector_contract_version(),
    }
    if not evidence_reusable(
        reusable,
        "2099-01-01",
        now=datetime.fromisoformat("2099-01-01T18:50:00+09:00"),
    ):
        fail("fresh same-date Evidence was not reusable")
    for rejected_date, rejected_now in (
        ("2098-12-31", "2099-01-01T18:50:00+09:00"),
        ("2099-01-01", "2099-01-01T22:30:00+09:00"),
    ):
        if evidence_reusable(
            reusable,
            rejected_date,
            now=datetime.fromisoformat(rejected_now),
        ):
            fail("stale or cross-date Evidence was reusable")
    if not evidence_reusable(
        reusable,
        "2099-01-01",
        now=datetime.fromisoformat("2099-01-01T22:30:00+09:00"),
        allow_expired_final=True,
    ):
        fail("explicit published re-edit could not reuse final same-day Evidence")
    if evidence_reusable(
        {
            "checked_at_jst": "2099-01-01T15:29:00+09:00",
            "collector_contract_version": evidence_store.collector_contract_version(),
        },
        "2099-01-01",
        now=datetime.fromisoformat("2099-01-01T22:30:00+09:00"),
        allow_expired_final=True,
    ):
        fail("published re-edit reused pre-final Evidence")
    if not evidence_reusable(
        {
            "checked_at_jst": "2099-01-01T15:29:00+09:00",
            "collector_contract_version": evidence_store.collector_contract_version(),
        },
        "2099-01-01",
        now=datetime.fromisoformat("2099-01-01T17:20:00+09:00"),
    ):
        fail("same-day Evidence could not be reused before final publication validation")
    if not evidence_reusable(
        {
            "checked_at_jst": "2099-01-01T22:45:00+09:00",
            "collector_contract_version": evidence_store.collector_contract_version(),
        },
        "2099-01-01",
        now=datetime.fromisoformat("2099-01-02T03:00:00+09:00"),
    ):
        fail("final previous-day Evidence could not be reused for overnight recovery")
    if evidence_reusable(
        {
            "checked_at_jst": "2099-01-01T22:45:00+09:00",
            "collector_contract_version": evidence_store.collector_contract_version(),
        },
        "2099-01-01",
        now=datetime.fromisoformat("2099-01-02T16:45:00+09:00"),
    ):
        fail("previous-day Evidence overlapped the current collection window")
    print("NIGHT SIGNAL PUBLISH SELF-TEST PASSED")


def sync_and_audit(issue_date: str) -> None:
    require_jst_current_issue(issue_date)
    run([sys.executable, "scripts/sync_site.py", issue_date])
    run([sys.executable, "scripts/current_issue_audit.py", issue_date])
    run([sys.executable, "scripts/coverage_audit.py", issue_date])
    run([sys.executable, "scripts/quality_gate.py", issue_date])


def prune_published_history(issue_date: str) -> None:
    """Keep the current issue plus three prior issues for novelty and readers."""
    current_sample = ROOT / f"night-brief-web-sample-{issue_date}.html"
    sample_html = current_sample.read_text(encoding="utf-8")
    linked_details = {
        match.group(1)
        for match in re.finditer(r'href="details/([^"#?]+\.html)', sample_html)
    }
    linked_details.update({"policy.html", "_style.css"})

    available_dates = {
        path.parent.name
        for path in STATE_ROOT.glob("20??-??-??/issue.json")
    }
    available_dates.update(
        match.group(1)
        for path in ROOT.glob("night-brief-web-sample-*.html")
        if (
            match := re.fullmatch(
                r"night-brief-web-sample-(\d{4}-\d{2}-\d{2})\.html",
                path.name,
            )
        )
    )
    retained_dates = retained_history_dates(available_dates, issue_date)
    for path in ROOT.glob("night-brief-web-sample-*.html"):
        match = re.fullmatch(
            r"night-brief-web-sample-(\d{4}-\d{2}-\d{2})\.html",
            path.name,
        )
        if match and match.group(1) not in retained_dates:
            path.unlink()
    for path in STATE_ROOT.iterdir():
        if path.is_dir() and path.name not in retained_dates:
            shutil.rmtree(path)
    details_dir = ROOT / "details"
    for path in details_dir.iterdir():
        if path.is_file() and path.name not in linked_details:
            path.unlink()


def self_tests(profile: str) -> None:
    if profile == "deploy":
        return
    if profile != "full":
        fail(f"unknown verification profile: {profile}")
    run([sys.executable, "scripts/night_signal_models.py"])
    run([sys.executable, "scripts/night_signal_run_guard.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_model_audit.py", "--self-test"])
    run([sys.executable, "scripts/publication_timing.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_runtime_audit.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_state.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_publish.py", "--self-test"])
    run([sys.executable, "scripts/simulate_runtime_failures.py"])
    run([sys.executable, "scripts/night_signal_collect.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_eval.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_editor.py", "--self-test"])
    run([sys.executable, "scripts/publication_schedule_audit.py"])


def readiness(issue_date: str, *, check: bool) -> dict[str, Any]:
    result = run(
        [sys.executable, "scripts/night_signal_state.py", "--readiness", "--date", issue_date],
        check=check,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"issue_date": issue_date, "readiness_parse_error": True}


def prepare(
    issue_date: str,
    *,
    reuse_evidence: bool,
    reprocess_existing: bool,
    reedit_published: bool,
    deploy_existing: bool,
    redeploy_published: bool,
    deploy_edited_final_evidence: bool,
    verification_profile: str,
) -> dict[str, Any]:
    require_jst_current_issue(issue_date)
    current_stage = "startup"
    runtime.write_checkpoint(issue_date, current_stage, "started", "publication driver started", STATE_ROOT)
    try:
        self_tests(verification_profile)
        runtime.write_checkpoint(issue_date, "runtime_checked", "completed", f"{verification_profile} verification passed", STATE_ROOT)
        if deploy_existing:
            if not (state_dir(issue_date) / "issue.json").exists():
                fail(f"{issue_date} has no committed issue state to deploy")
            if redeploy_published:
                run(
                    [
                        sys.executable,
                        "scripts/publication_audit.py",
                        issue_date,
                        "--public-content-only",
                    ]
                )
            if deploy_edited_final_evidence and not issue_matches_evidence(issue_date):
                fail("edited final-Evidence deployment requires a current audited issue")
        else:
            if reedit_published:
                run(
                    [
                        sys.executable,
                        "scripts/publication_audit.py",
                        issue_date,
                        "--public-content-only",
                    ]
                )
            current_stage = "plan_written"
            runtime.write_checkpoint(issue_date, current_stage, "completed", "current collection contract loaded", STATE_ROOT)
            current_stage = "collection_complete"
            collect_and_build(
                issue_date,
                reuse_evidence=reuse_evidence,
                reprocess_existing=reprocess_existing,
                reedit_published=reedit_published,
            )
            runtime.write_checkpoint(issue_date, current_stage, "completed", "Evidence written", STATE_ROOT)
            current_stage = "story_build_complete"
            runtime.write_checkpoint(issue_date, current_stage, "completed", "important updates and manifest written", STATE_ROOT)
        freshness = collection_freshness(
            issue_date,
            require_evening_refresh=deploy_existing or reedit_published,
            allow_expired_current=(
                redeploy_published
                or reedit_published
                or deploy_edited_final_evidence
            ),
        )
        current_stage = "render_complete"
        assemble_and_render(issue_date)
        runtime.write_checkpoint(issue_date, current_stage, "completed", "issue and detail pages rendered", STATE_ROOT)
        current_stage = "local_gates_complete"
        sync_and_audit(issue_date)
        status = readiness(issue_date, check=True)
        if status.get("blockers"):
            fail("readiness still has blockers: " + "; ".join(str(item) for item in status["blockers"]))
        prune_published_history(issue_date)
        runtime.write_checkpoint(issue_date, current_stage, "completed", "all local publication gates passed", STATE_ROOT)
        return {
            "issue_date": issue_date,
            "sample_html": f"night-brief-web-sample-{issue_date}.html",
            "site_index": "site/index.html",
            "dated_site_index": f"site/{issue_date}/index.html",
            "freshness": freshness,
            "readiness": status,
            "runtime_checkpoint": str(runtime.checkpoint_path(issue_date, STATE_ROOT)),
        }
    except SystemExit:
        runtime.write_checkpoint(
            issue_date,
            current_stage,
            "failed",
            "publication driver exited before completing this stage",
            STATE_ROOT,
        )
        raise


def public_audit(issue_date: str) -> dict[str, Any]:
    require_jst_current_issue(issue_date)
    run([sys.executable, "scripts/publication_audit.py", issue_date, "--public-content-only"])
    return {"issue_date": issue_date, "public_content_verified": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=jst_today())
    parser.add_argument("--resolve-issue-date", action="store_true")
    parser.add_argument("--event-name", default="")
    parser.add_argument("--requested-issue-date", default="")
    parser.add_argument("--reuse-evidence", action="store_true")
    parser.add_argument(
        "--reprocess-existing",
        action="store_true",
        help="re-edit reusable Evidence with checkpoints only and make no model request",
    )
    parser.add_argument(
        "--reedit-published",
        action="store_true",
        help=(
            "re-edit an already-public issue with its final same-day Evidence and "
            "current Editor contract; requires --reuse-evidence"
        ),
    )
    parser.add_argument("--deploy-existing", action="store_true")
    parser.add_argument(
        "--redeploy-published",
        action="store_true",
        help=(
            "redeploy an already-public matching issue without recollection; requires "
            "--deploy-existing and a passing public-content audit"
        ),
    )
    parser.add_argument(
        "--deploy-edited-final-evidence",
        action="store_true",
        help=(
            "deploy an audited current-contract issue rebuilt from final same-day "
            "Evidence after the normal age limit"
        ),
    )
    parser.add_argument("--public-audit", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--verification-profile", choices=["deploy", "full"], default="")
    args = parser.parse_args()

    if args.resolve_issue_date:
        print(
            resolve_issue_date(
                event_name=args.event_name,
                requested_issue_date=args.requested_issue_date,
            )
        )
        return 0
    validate_issue_date(args.issue_date)
    if args.self_test:
        self_test()
        return 0
    if args.reuse_evidence and args.deploy_existing:
        fail("--reuse-evidence and --deploy-existing are mutually exclusive")
    if args.reprocess_existing and not args.reuse_evidence:
        fail("--reprocess-existing requires --reuse-evidence")
    if args.reprocess_existing and args.deploy_existing:
        fail("--reprocess-existing and --deploy-existing are mutually exclusive")
    if args.reedit_published and not args.reuse_evidence:
        fail("--reedit-published requires --reuse-evidence")
    if args.reedit_published and (args.reprocess_existing or args.deploy_existing):
        fail("--reedit-published cannot be combined with reprocess or deploy modes")
    if args.redeploy_published and not args.deploy_existing:
        fail("--redeploy-published requires --deploy-existing")
    if args.deploy_edited_final_evidence and not args.deploy_existing:
        fail("--deploy-edited-final-evidence requires --deploy-existing")
    if args.deploy_edited_final_evidence and args.redeploy_published:
        fail("edited final-Evidence deploy and static redeploy are mutually exclusive")
    if args.public_audit:
        result = public_audit(args.issue_date)
    else:
        verification_profile = args.verification_profile or ("deploy" if args.deploy_existing else "full")
        result = prepare(
            args.issue_date,
            reuse_evidence=args.reuse_evidence,
            reprocess_existing=args.reprocess_existing,
            reedit_published=args.reedit_published,
            deploy_existing=args.deploy_existing,
            redeploy_published=args.redeploy_published,
            deploy_edited_final_evidence=args.deploy_edited_final_evidence,
            verification_profile=verification_profile,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
