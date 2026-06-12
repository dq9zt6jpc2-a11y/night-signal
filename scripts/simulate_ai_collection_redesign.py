#!/usr/bin/env python3
"""Simulate whether the zero-base AI collection redesign is implemented.

The simulation is deterministic and does not call external APIs. It compares
the current collection plan and source code against the desired redesign:
raw web-search traces, strict search execution, cache/reuse, Batch readiness,
and claim/source linkage. It intentionally does not require a separate
multi-file cognition pipeline because that would risk worsening efficiency.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "scripts" / "night_signal_collect.py"
SYNTHESIZER = ROOT / "scripts" / "night_signal_synthesize.py"
STATE = ROOT / "scripts" / "night_signal_state.py"
README = ROOT / "README-night-signal.md"
POLICY = ROOT / "details" / "policy.html"
WORKFLOWS = list((ROOT / ".github" / "workflows").glob("*.yml"))


def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, "unknown"))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def capability_checks() -> dict[str, bool]:
    collector = read(COLLECTOR)
    synthesizer = read(SYNTHESIZER)
    state_code = read(STATE)
    readme = read(README)
    policy = read(POLICY)
    workflows = "\n".join(read(path) for path in WORKFLOWS)
    combined_docs = "\n".join([readme, policy, workflows])
    return {
        "seed_targets_in_plan": "source_targets_for_slot" in state_code,
        "per_seed_target_closure_required": "source_target_results_for_every_seed_target" in state_code,
        "web_search_sources_requested": "web_search_call.action.sources" in collector,
        "web_search_results_requested": "web_search_call.results" in collector,
        "raw_web_search_sources_persisted": "raw_web_search_sources" in collector or "web_search_sources" in state_code,
        "raw_web_search_results_persisted": "raw_web_search_results" in collector or "image_result" in state_code,
        "web_search_required_for_required_slots": '"tool_choice": "required"' in collector or "'tool_choice': 'required'" in collector,
        "domain_filters_implemented": "allowed_domains" in collector or "blocked_domains" in collector,
        "external_web_access_controlled": "external_web_access" in collector,
        "return_token_budget_controlled": "return_token_budget" in collector,
        "image_search_enabled": "search_content_types" in collector and "image_settings" in collector,
        "prompt_cache_key_sent": '"prompt_cache_key"' in collector or "'prompt_cache_key'" in collector,
        "batch_api_implemented": "/v1/batches" in collector or "batches.create" in collector,
        "claim_source_linkage_present": "claim_source" in state_code or "claim_source" in synthesizer,
        "hypotheses_in_collection_plan": "hypotheses" in state_code,
        "policy_mentions_efficient_cognition_flow": "raw source" in policy or "source_target_results" in policy,
        "readme_mentions_efficient_cognition_flow": "source_target_results" in readme,
        "workflow_avoids_parallel_cognition_pipeline": "memory_snapshot.json" not in workflows and "evidence_graph.json" not in workflows,
        "docs_or_workflows_still_old_flow": "collection_plan.json" in combined_docs and "observations.jsonl" in combined_docs,
    }


def simulate(issue_date: str) -> dict[str, Any]:
    plan = state.collection_plan(issue_date)
    tasks = [task for task in plan["tasks"] if isinstance(task, dict)]
    source_targets = [
        target
        for task in tasks
        for target in task.get("source_targets", [])
        if isinstance(target, dict)
    ]
    normal_tasks = [task for task in tasks if task.get("priority") == "normal"]
    reusable_tasks = [task for task in tasks if str(task.get("reuse_policy", "")).startswith("reuse_")]
    checks = capability_checks()

    target_capabilities = [
        "seed_targets_in_plan",
        "per_seed_target_closure_required",
        "web_search_sources_requested",
        "web_search_results_requested",
        "raw_web_search_sources_persisted",
        "raw_web_search_results_persisted",
        "web_search_required_for_required_slots",
        "domain_filters_implemented",
        "external_web_access_controlled",
        "return_token_budget_controlled",
        "image_search_enabled",
        "prompt_cache_key_sent",
        "batch_api_implemented",
        "claim_source_linkage_present",
        "hypotheses_in_collection_plan",
        "policy_mentions_efficient_cognition_flow",
        "readme_mentions_efficient_cognition_flow",
        "workflow_avoids_parallel_cognition_pipeline",
    ]
    implemented = [name for name in target_capabilities if checks[name]]
    missing = [name for name in target_capabilities if not checks[name]]

    # This is a directional simulation, not a cost estimate. It says how much of
    # the plan could benefit if the redesign were implemented.
    potential = {
        "batchable_normal_task_share": round(len(normal_tasks) / len(tasks), 4) if tasks else 0,
        "reuse_candidate_task_share": round(len(reusable_tasks) / len(tasks), 4) if tasks else 0,
        "seed_target_results_required": len(source_targets),
        "seed_target_channel_counts": count_by(source_targets, "channel"),
        "task_channel_counts": count_by(tasks, "channel"),
        "task_model_route_counts": count_by(tasks, "model_route"),
        "task_priority_counts": count_by(tasks, "priority"),
        "task_reuse_policy_counts": count_by(tasks, "reuse_policy"),
    }

    limit_blockers = []
    if not checks["raw_web_search_sources_persisted"]:
        limit_blockers.append("raw_source_trace_missing")
    if not checks["web_search_required_for_required_slots"]:
        limit_blockers.append("required_live_search_not_enforced")
    if not checks["hypotheses_in_collection_plan"]:
        limit_blockers.append("collection_hypotheses_missing")
    if not checks["claim_source_linkage_present"]:
        limit_blockers.append("claim_source_linkage_missing")
    if not checks["prompt_cache_key_sent"]:
        limit_blockers.append("prompt_cache_key_not_sent")
    if checks["batch_api_implemented"] and not checks["claim_source_linkage_present"]:
        limit_blockers.append("batch_before_evidence_linkage_would_hide_misses")

    limit_assessment = {
        "limit_reached": not limit_blockers,
        "limit_blockers": limit_blockers,
        "not_required_for_current_limit": [
            "deep_research_daily_generation",
            "agents_sdk_orchestration",
            "batch_api_before_claim_source_linkage",
            "image_search_for_non_visual_slots",
            "many_new_daily_cognition_files",
        ],
        "reasoning": (
            "Comprehensive collection cannot be considered at the practical limit until "
            "seed targets, raw traces, hypotheses, claim/source linkage, and cache-aware "
            "execution are all present. Deep Research or Agents SDK would add complexity "
            "before the current deterministic path has exhausted cheaper improvements."
        ),
    }

    verdict = "not_improved_in_implementation"
    if (
        checks["raw_web_search_sources_persisted"]
        and checks["web_search_required_for_required_slots"]
        and checks["prompt_cache_key_sent"]
    ):
        verdict = "partially_improved_in_implementation"
    if limit_assessment["limit_reached"]:
        verdict = "practical_collection_limit_reached_without_heavy_orchestration"
    if not missing:
        verdict = "redesign_implemented"

    weaknesses = []
    if not checks["raw_web_search_results_persisted"]:
        weaknesses.append("Current code persists raw web-search sources, but not raw image/search results.")
    if not checks["batch_api_implemented"]:
        weaknesses.append("Current code marks batch/reuse/prompt-cache metadata, but does not execute Batch.")
    if not checks["claim_source_linkage_present"]:
        weaknesses.append("Current synthesis still jumps from observations to decisions without explicit claim/source linkage.")
    if not checks["domain_filters_implemented"] or not checks["return_token_budget_controlled"]:
        weaknesses.append("Responses web-search controls for domain filters and returned-token budget are not yet exposed.")
    if not checks["image_search_enabled"]:
        weaknesses.append("Image search is still deferred for non-visual daily slots.")

    return {
        "issue_date": issue_date,
        "verdict": verdict,
        "plan": {
            "frontier_tasks": len(tasks),
            "source_targets": len(source_targets),
            "batch_groups": count_by(tasks, "batch_group"),
        },
        "potential_improvement_if_implemented": potential,
        "limit_assessment": limit_assessment,
        "implemented_capabilities": implemented,
        "missing_capabilities": missing,
        "weaknesses": weaknesses,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-weakness", action="store_true")
    args = parser.parse_args()

    result = simulate(args.issue_date)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if args.fail_on_weakness and result["missing_capabilities"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
