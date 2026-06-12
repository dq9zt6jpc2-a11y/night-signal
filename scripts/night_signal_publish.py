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
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL PUBLISH FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def jst_today() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()


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


def collect(issue_date: str, *, force_collect: bool) -> None:
    if force_collect or not has_observations(issue_date):
        if has_research_bundle(issue_date):
            run([sys.executable, "scripts/night_signal_import_research.py", issue_date])
            return
        require_openai_key(issue_date)
        run([sys.executable, "scripts/night_signal_collect.py", issue_date, "--replace"])
    validate_observations(issue_date)


def synthesize(issue_date: str, *, force_synthesize: bool) -> None:
    if force_synthesize or not has_synthesis(issue_date):
        if has_research_bundle(issue_date):
            run([sys.executable, "scripts/night_signal_import_research.py", issue_date])
            return
        require_openai_key(issue_date)
        run([sys.executable, "scripts/night_signal_synthesize.py", issue_date, "--replace"])


def assemble_and_render(issue_date: str) -> None:
    base = state_dir(issue_date)
    if not (base / "issue.json").exists():
        run([sys.executable, "scripts/night_signal_state.py", "--assemble-issue-state", issue_date])
    run([sys.executable, "scripts/night_signal_state.py", "--validate-issue", str(base / "issue.json")])
    run([sys.executable, "scripts/night_signal_state.py", "--generate-issue", str(base / "issue.json")])


def sync_and_audit(issue_date: str) -> None:
    run([sys.executable, "scripts/night_signal_eval.py", issue_date])
    run([sys.executable, "scripts/guardrail_inventory.py"])
    run([sys.executable, "scripts/sync_site.py", issue_date])
    run([sys.executable, "scripts/current_issue_audit.py", issue_date])
    run([sys.executable, "scripts/coverage_audit.py", issue_date])
    run([sys.executable, "scripts/quality_gate.py", issue_date])
    run([sys.executable, "scripts/pre22_audit.py", issue_date])


def self_tests() -> None:
    run([sys.executable, "scripts/night_signal_state.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_collect.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_synthesize.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_eval.py", "--self-test"])
    run([sys.executable, "scripts/night_signal_import_research.py", "--self-test"])
    run([sys.executable, "scripts/publication_schedule_audit.py"])
    run([sys.executable, "scripts/simulate_ai_collection_redesign.py", jst_today(), "--fail-on-weakness"])


def readiness(issue_date: str, *, check: bool) -> dict[str, Any]:
    result = run(
        [sys.executable, "scripts/night_signal_state.py", "--readiness", "--date", issue_date],
        check=check,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"issue_date": issue_date, "readiness_parse_error": True}


def prepare(issue_date: str, *, force_collect: bool, force_synthesize: bool, skip_live: bool) -> dict[str, Any]:
    self_tests()
    ensure_collection_plan(issue_date)
    issue_exists = (state_dir(issue_date) / "issue.json").exists()
    if force_collect or force_synthesize or not issue_exists:
        if skip_live and not has_observations(issue_date):
            fail(f"{issue_date} has no observations; live collection cannot be skipped")
        collect(issue_date, force_collect=force_collect)
        synthesize(issue_date, force_synthesize=force_synthesize)
    assemble_and_render(issue_date)
    sync_and_audit(issue_date)
    status = readiness(issue_date, check=True)
    if status.get("blockers"):
        fail("readiness still has blockers: " + "; ".join(str(item) for item in status["blockers"]))
    return {
        "issue_date": issue_date,
        "sample_html": f"night-brief-web-sample-{issue_date}.html",
        "site_index": "site/index.html",
        "dated_site_index": f"site/{issue_date}/index.html",
        "readiness": status,
    }


def public_audit(issue_date: str) -> dict[str, Any]:
    run([sys.executable, "scripts/publication_audit.py", issue_date, "--public-content-only"])
    return {"issue_date": issue_date, "public_content_verified": True}


def preflight(issue_date: str) -> dict[str, Any]:
    self_tests()
    ensure_collection_plan(issue_date)
    if not (state_dir(issue_date) / "issue.json").exists() and not has_observations(issue_date):
        require_openai_key(issue_date)
    if (state_dir(issue_date) / "issue.json").exists():
        assemble_and_render(issue_date)
        run([sys.executable, "scripts/sync_site.py", issue_date])
        run([sys.executable, "scripts/current_issue_audit.py", issue_date])
        run([sys.executable, "scripts/coverage_audit.py", issue_date])
        run([sys.executable, "scripts/quality_gate.py", issue_date])
    run([sys.executable, "scripts/guardrail_inventory.py"])
    status = readiness(issue_date, check=False)
    return {"issue_date": issue_date, "preflight": True, "readiness": status}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=jst_today())
    parser.add_argument("--force-collect", action="store_true")
    parser.add_argument("--force-synthesize", action="store_true")
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--public-audit", action="store_true")
    args = parser.parse_args()

    if not args.issue_date or len(args.issue_date) != 10:
        fail(f"invalid issue date: {args.issue_date}")
    if args.preflight:
        result = preflight(args.issue_date)
    elif args.public_audit:
        result = public_audit(args.issue_date)
    else:
        result = prepare(
            args.issue_date,
            force_collect=args.force_collect,
            force_synthesize=args.force_synthesize,
            skip_live=args.skip_live,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
