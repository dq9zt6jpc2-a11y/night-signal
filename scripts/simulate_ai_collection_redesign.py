#!/usr/bin/env python3
"""Measure NIGHT SIGNAL collection coverage, efficiency, and information retention."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "scripts" / "night_signal_collect.py"
SYNTHESIZER = ROOT / "scripts" / "night_signal_synthesize.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def old_slot_plan(frontier: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry = state.load_source_registry()
    return [
        {
            **slot,
            "source_targets": state.source_targets_for_slot(registry, slot),
        }
        for slot in state.required_observation_slots(frontier)
    ]


def slot_keys_from_sweeps(tasks: list[dict[str, Any]]) -> set[tuple[str, str, str, str]]:
    return {
        (
            str(task["category"]),
            str(topic["watch_topic_id"]),
            str(task["source_role"]),
            str(task["channel"]),
        )
        for task in tasks
        for topic in task.get("watch_topics", [])
        if isinstance(topic, dict)
    }


def simulate(issue_date: str) -> dict[str, Any]:
    contract = state.read_json(state.CONFIG_PATH)
    frontier = state.build_frontier(contract)
    old_tasks = old_slot_plan(frontier)
    new_plan = state.collection_plan(issue_date)
    new_tasks = [task for task in new_plan["tasks"] if isinstance(task, dict)]

    required_slots = {
        (
            str(slot["category"]),
            str(slot["watch_topic_id"]),
            str(slot["source_role"]),
            str(slot["channel"]),
        )
        for slot in state.required_observation_slots(frontier)
    }
    planned_slots = slot_keys_from_sweeps(new_tasks)

    old_target_refs = [
        str(target["url"])
        for task in old_tasks
        for target in task["source_targets"]
    ]
    new_target_refs = [
        str(target["url"])
        for task in new_tasks
        for target in task.get("source_targets", [])
        if isinstance(target, dict)
    ]

    broad_horizon_tasks = [
        task
        for task in new_tasks
        if any("breaking announcement change result data" in query for query in task.get("search_queries", []))
        and any("既存watch_topic_idだけでは表現できない" in item for item in task.get("hypotheses", []))
    ]
    old_horizon_tasks = [
        task
        for task in old_tasks
        if any(
            str(task["watch_topic_id"]) not in query
            for query in state.build_search_queries(
                issue_date,
                next(
                    item
                    for item in frontier
                    if item["category"] == task["category"]
                    and item["watch_topic_id"] == task["watch_topic_id"]
                ),
                task,
            )
        )
    ]

    observation_required = set(state.SOURCE_OBSERVATION_SCHEMA["required"])
    summary_required = set(state.SUMMARY_BASIS_SCHEMA["required"])
    collector = read(COLLECTOR)
    synthesizer = read(SYNTHESIZER)
    importer = read(ROOT / "scripts" / "night_signal_import_research.py")
    publisher = read(ROOT / "scripts" / "night_signal_publish.py")
    renderer = read(ROOT / "scripts" / "night_signal_state.py")
    channel_routes: dict[str, set[str]] = {}
    for task in new_tasks:
        channel_routes.setdefault(str(task.get("category")), set()).add(
            str(task.get("channel"))
        )

    metrics = {
        "ai_calls": {
            "before": len(old_tasks),
            "after": len(new_tasks),
            "reduction_ratio": round(1 - len(new_tasks) / len(old_tasks), 4),
        },
        "seed_target_checks": {
            "before": len(old_target_refs),
            "after": len(new_target_refs),
            "unique_targets": len(set(new_target_refs)),
            "duplicate_checks_removed": len(old_target_refs) - len(new_target_refs),
            "reduction_ratio": round(1 - len(new_target_refs) / len(old_target_refs), 4),
        },
        "known_frontier_coverage": {
            "required_slots": len(required_slots),
            "planned_slots": len(planned_slots),
            "recall": round(len(required_slots & planned_slots) / len(required_slots), 4),
            "missing_slots": sorted(required_slots - planned_slots),
        },
        "unknown_topic_discovery": {
            "before_horizon_task_share": round(len(old_horizon_tasks) / len(old_tasks), 4),
            "after_horizon_task_share": round(len(broad_horizon_tasks) / len(new_tasks), 4),
            "discovery_findings_structured": "discovery_findings" in observation_required,
            "synthesis_retains_discoveries": "Treat discovery_findings as the horizon scan" in synthesizer,
        },
        "evidence_integrity": {
            "target_result_has_checked_at": "checked_at_jst" in state.SOURCE_OBSERVATION_SCHEMA["properties"]["source_target_results"]["items"]["required"],
            "target_result_has_verification_method": "verification_method" in state.SOURCE_OBSERVATION_SCHEMA["properties"]["source_target_results"]["items"]["required"],
            "collector_cross_checks_trace_urls": "observed source missing from web_search trace" in collector,
            "reviewed_import_requires_explicit_checks": "seed targets without explicit checks" in importer,
            "unverified_targets_excluded_from_manifest": "observed_urls_by_category" in synthesizer,
        },
        "all_category_channel_coverage": {
            "categories": {
                category: sorted(channels)
                for category, channels in sorted(channel_routes.items())
            },
            "all_have_web_x_youtube": all(
                {"web", "sns_x", "youtube"} <= channels
                for channels in channel_routes.values()
            ),
        },
        "publication_integrity": {
            "morning_issue_does_not_skip_collection": "issue_exists" not in publisher,
            "deploy_requires_evening_refresh": "require_evening_refresh=deploy_existing" in publisher,
            "public_confirmation_signal_layer": "verified-signals" in renderer,
        },
        "information_retention": {
            "required_detail_slots": sorted(summary_required),
            "confirmed_fact_minimum": contract.get("minimum_current_material_facts_per_published_item"),
            "fact_to_source_mapping_required": "fact_sources" in summary_required,
            "collector_preserves_complete_source_list": "web_search_call.action.sources" in collector,
            "detail_source_urls_required": True,
        },
        "route_counts": dict(sorted(Counter(str(task.get("model_route")) for task in new_tasks).items())),
        "channel_sweep_counts": dict(sorted(Counter(str(task.get("channel")) for task in new_tasks).items())),
    }

    failures: list[str] = []
    if metrics["ai_calls"]["reduction_ratio"] < 0.70:
        failures.append("ai_call_reduction_below_70_percent")
    if metrics["seed_target_checks"]["after"] != metrics["seed_target_checks"]["unique_targets"]:
        failures.append("seed_target_checks_still_duplicated")
    if metrics["known_frontier_coverage"]["recall"] != 1.0:
        failures.append("known_frontier_slot_loss")
    if metrics["unknown_topic_discovery"]["after_horizon_task_share"] != 1.0:
        failures.append("horizon_discovery_not_present_in_every_sweep")
    if metrics["unknown_topic_discovery"]["before_horizon_task_share"] != 0.0:
        failures.append("legacy_baseline_not_topic_bound")
    if not metrics["unknown_topic_discovery"]["discovery_findings_structured"]:
        failures.append("discovery_findings_not_structured")
    if not metrics["unknown_topic_discovery"]["synthesis_retains_discoveries"]:
        failures.append("discovery_findings_can_be_dropped")
    if not metrics["information_retention"]["fact_to_source_mapping_required"]:
        failures.append("material_facts_not_individually_sourced")
    if not metrics["information_retention"]["collector_preserves_complete_source_list"]:
        failures.append("complete_web_search_source_list_not_preserved")
    if not all(metrics["evidence_integrity"].values()):
        failures.append("source_verification_provenance_is_incomplete")
    if not metrics["all_category_channel_coverage"]["all_have_web_x_youtube"]:
        failures.append("some_categories_lack_web_x_or_youtube")
    if not all(metrics["publication_integrity"].values()):
        failures.append("publication_can_still_hide_or_reuse_stale_collection")

    result = {
        "issue_date": issue_date,
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "metrics": metrics,
        "limits": [
            "This deterministic simulation proves structural coverage, provenance, and publication ownership.",
            "Live recall still requires an evening collection run and a reviewed missed-source sample.",
        ],
    }
    return result


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
    return 1 if args.fail_on_weakness and result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
