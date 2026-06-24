#!/usr/bin/env python3
"""Run the canonical NIGHT SIGNAL daily publication pipeline.

This script is the single operational owner for the 20:00 JST publication path.
It keeps the workflow generic: build the dated collection state, collect live
observations when needed, synthesize issue state, render, sync, and audit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import night_signal_runtime_audit as runtime


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL PUBLISH FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def jst_today() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()


def allow_explicit_stale_issue() -> bool:
    return os.getenv("NIGHT_SIGNAL_ALLOW_EXPLICIT_STALE") == "1"


def require_jst_current_issue(issue_date: str) -> None:
    today = jst_today()
    if issue_date != today and not allow_explicit_stale_issue():
        fail(f"refusing to publish stale issue as latest: {issue_date} != JST today {today}")


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


def exists_any(paths: list[Path]) -> bool:
    return any(path.exists() for path in paths)


def state_dir(issue_date: str) -> Path:
    return STATE_ROOT / issue_date


def write_collection_plan(issue_date: str) -> None:
    run([sys.executable, "scripts/night_signal_state.py", "--write-collection-plan", issue_date])


def ensure_collection_plan(issue_date: str) -> None:
    if not (state_dir(issue_date) / "collection_plan.json").exists():
        write_collection_plan(issue_date)


def has_observations(issue_date: str) -> bool:
    base = state_dir(issue_date)
    return exists_any([base / "observations.jsonl", base / "observations.json"])


def has_synthesis(issue_date: str) -> bool:
    base = state_dir(issue_date)
    return (
        exists_any([base / "candidates.jsonl", base / "candidates.json"])
        and exists_any([base / "decisions.jsonl", base / "decisions.json"])
        and exists_any([base / "cards.jsonl", base / "cards.json"])
        and (base / "coverage_manifest.json").exists()
    )


def require_openai_key(issue_date: str) -> None:
    if os.getenv("OPENAI_API_KEY"):
        return
    fail(f"OPENAI_API_KEY is required to generate {issue_date} from live sources")


def has_research_bundle(issue_date: str) -> bool:
    return (state_dir(issue_date) / "research_bundle.json").exists()


def validate_observations(issue_date: str) -> None:
    base = state_dir(issue_date)
    path = base / "observations.jsonl"
    if not path.exists():
        path = base / "observations.json"
    run([sys.executable, "scripts/night_signal_state.py", "--validate-observations", str(path)])


def collect(issue_date: str, *, import_reviewed_bundle: bool) -> None:
    if import_reviewed_bundle:
        if not has_research_bundle(issue_date):
            fail(f"reviewed research bundle is missing for {issue_date}")
        run([sys.executable, "scripts/night_signal_import_research.py", issue_date])
        return
    require_openai_key(issue_date)
    run([sys.executable, "scripts/night_signal_collect.py", issue_date, "--replace", "--resume", "--quiet"])
    validate_observations(issue_date)


def synthesize(issue_date: str, *, import_reviewed_bundle: bool) -> None:
    if import_reviewed_bundle:
        if not has_synthesis(issue_date):
            fail(f"reviewed research import did not create synthesis artifacts for {issue_date}")
        return
    require_openai_key(issue_date)
    run([sys.executable, "scripts/night_signal_synthesize.py", issue_date, "--replace", "--resume"])


def assemble_and_render(issue_date: str) -> None:
    base = state_dir(issue_date)
    run([sys.executable, "scripts/night_signal_state.py", "--assemble-issue-state", issue_date])
    run([sys.executable, "scripts/night_signal_state.py", "--validate-issue", str(base / "issue.json")])
    run([sys.executable, "scripts/night_signal_state.py", "--generate-issue", str(base / "issue.json")])


def collection_freshness(
    issue_date: str,
    *,
    now: datetime | None = None,
    require_evening_refresh: bool,
) -> dict[str, Any]:
    manifest = json.loads(
        (state_dir(issue_date) / "coverage_manifest.json").read_text(encoding="utf-8")
    )
    return validate_collection_freshness(
        manifest,
        issue_date,
        now=now or datetime.now(ZoneInfo("Asia/Tokyo")),
        require_evening_refresh=require_evening_refresh,
    )


def validate_collection_freshness(
    manifest: dict[str, Any],
    issue_date: str,
    *,
    now: datetime,
    require_evening_refresh: bool,
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
    if issue_date == current.date().isoformat() and current - completed > timedelta(hours=4):
        fail(f"collection is too old for publication: {completed.isoformat()}")
    evening_cutoff = datetime.combine(
        completed.date(),
        time(hour=18),
        tzinfo=ZoneInfo("Asia/Tokyo"),
    )
    if require_evening_refresh and completed < evening_cutoff:
        fail(
            "final publication requires a fresh collection completed at or after "
            f"{evening_cutoff.isoformat()}; got {completed.isoformat()}"
        )
    mode = manifest.get("collection_mode")
    if mode not in {
        "responses_web_search",
        "reviewed_live_web",
        "github_models_unattended",
    }:
        fail(f"unsupported collection_mode for publication: {mode}")
    return {
        "collection_completed_at_jst": completed.isoformat(),
        "collection_mode": mode,
        "evening_refresh": completed >= evening_cutoff,
    }


def self_test() -> None:
    original_allow_stale = os.environ.pop("NIGHT_SIGNAL_ALLOW_EXPLICIT_STALE", None)
    try:
        try:
            require_jst_current_issue("1900-01-01")
        except SystemExit:
            pass
        else:
            fail("stale issue date must not be publishable without explicit override")
        os.environ["NIGHT_SIGNAL_ALLOW_EXPLICIT_STALE"] = "1"
        require_jst_current_issue("1900-01-01")
    finally:
        if original_allow_stale is None:
            os.environ.pop("NIGHT_SIGNAL_ALLOW_EXPLICIT_STALE", None)
        else:
            os.environ["NIGHT_SIGNAL_ALLOW_EXPLICIT_STALE"] = original_allow_stale
    current = datetime.fromisoformat("2099-01-01T19:30:00+09:00")
    fresh = {
        "collection_completed_at_jst": "2099-01-01T18:30:00+09:00",
        "collection_mode": "reviewed_live_web",
    }
    result = validate_collection_freshness(
        fresh,
        "2099-01-01",
        now=current,
        require_evening_refresh=True,
    )
    if not result["evening_refresh"]:
        fail("fresh evening collection was rejected")
    stale = dict(fresh)
    stale["collection_completed_at_jst"] = "2099-01-01T13:00:00+09:00"
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
        fail("morning collection must not pass final deployment")
    print("NIGHT SIGNAL PUBLISH SELF-TEST PASSED")


def sync_and_audit(issue_date: str) -> None:
    require_jst_current_issue(issue_date)
    run([sys.executable, "scripts/night_signal_eval.py", issue_date])
    run([sys.executable, "scripts/guardrail_inventory.py"])
    run([sys.executable, "scripts/sync_site.py", issue_date])
    run([sys.executable, "scripts/current_issue_audit.py"])
    run([sys.executable, "scripts/coverage_audit.py", issue_date])
    run([sys.executable, "scripts/quality_gate.py", issue_date])


def self_tests(profile: str) -> None:
    run([sys.executable, "scripts/night_signal_models.py"])
    run([sys.executable, "scripts/night_signal_runtime_audit.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_state.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_publish.py", "--self-test"])
    if profile == "deploy":
        return
    if profile != "full":
        fail(f"unknown verification profile: {profile}")
    run([sys.executable, "scripts/simulate_runtime_failures.py"])
    run([sys.executable, "scripts/night_signal_collect.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_unattended_collect.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_synthesize.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_eval.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_import_research.py", "--self-test"])
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
    import_reviewed_bundle: bool,
    deploy_existing: bool,
    verification_profile: str,
) -> dict[str, Any]:
    require_jst_current_issue(issue_date)
    current_stage = "startup"
    runtime.write_checkpoint(issue_date, current_stage, "started", "publication driver started", STATE_ROOT)
    try:
        self_tests(verification_profile)
        runtime.write_checkpoint(issue_date, "runtime_checked", "completed", f"{verification_profile} verification passed", STATE_ROOT)
        if deploy_existing:
            ensure_collection_plan(issue_date)
            if not (state_dir(issue_date) / "issue.json").exists():
                fail(f"{issue_date} has no committed issue state to deploy")
        else:
            current_stage = "plan_written"
            write_collection_plan(issue_date)
            runtime.write_checkpoint(issue_date, current_stage, "completed", "current collection plan written", STATE_ROOT)
            current_stage = "collection_complete"
            collect(issue_date, import_reviewed_bundle=import_reviewed_bundle)
            runtime.write_checkpoint(issue_date, current_stage, "completed", "all collection slots closed", STATE_ROOT)
            current_stage = "synthesis_complete"
            synthesize(issue_date, import_reviewed_bundle=import_reviewed_bundle)
            runtime.write_checkpoint(issue_date, current_stage, "completed", "candidates, decisions, cards, and manifest written", STATE_ROOT)
        freshness = collection_freshness(
            issue_date,
            require_evening_refresh=deploy_existing,
        )
        current_stage = "render_complete"
        assemble_and_render(issue_date)
        runtime.write_checkpoint(issue_date, current_stage, "completed", "issue and detail pages rendered", STATE_ROOT)
        current_stage = "local_gates_complete"
        sync_and_audit(issue_date)
        status = readiness(issue_date, check=True)
        if status.get("blockers"):
            fail("readiness still has blockers: " + "; ".join(str(item) for item in status["blockers"]))
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
    parser.add_argument("--import-reviewed-bundle", action="store_true")
    parser.add_argument("--deploy-existing", action="store_true")
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
    if args.import_reviewed_bundle and args.deploy_existing:
        fail("--import-reviewed-bundle and --deploy-existing are mutually exclusive")
    if args.public_audit:
        result = public_audit(args.issue_date)
    else:
        verification_profile = args.verification_profile or ("deploy" if args.deploy_existing else "full")
        result = prepare(
            args.issue_date,
            import_reviewed_bundle=args.import_reviewed_bundle,
            deploy_existing=args.deploy_existing,
            verification_profile=verification_profile,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
