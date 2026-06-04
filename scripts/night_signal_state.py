#!/usr/bin/env python3
"""Schema-first operating state for NIGHT SIGNAL.

This is not another publication gate. It is the small core that the nightly
system should optimize around: discovery frontier -> observations -> candidates
-> decisions -> publication plan. OpenAI-backed runs can produce the same JSON
shape with Responses API Structured Outputs; local and CI runs can still inspect
the state deterministically.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "night_signal_coverage.json"
MARKER_PATH = ROOT / ".night-signal-issue-date"

STATE_NAMES = [
    "frontier_built",
    "observations_collected",
    "candidates_normalized",
    "topic_value_decided",
    "issue_rendered",
    "publication_ready",
]

SOURCE_OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "category",
        "watch_topic_id",
        "source_role",
        "channel",
        "url",
        "observed_at_jst",
        "published_date",
        "evidence_summary",
        "claim_atoms",
    ],
    "properties": {
        "category": {"type": "string"},
        "watch_topic_id": {"type": "string"},
        "source_role": {"type": "string", "enum": ["primary_or_official", "independent_media_or_data", "social_or_video_signal"]},
        "channel": {"type": "string", "enum": ["web", "sns_x", "instagram", "youtube", "data", "calendar"]},
        "url": {"type": "string"},
        "observed_at_jst": {"type": "string"},
        "published_date": {"type": ["string", "null"]},
        "evidence_summary": {"type": "string"},
        "claim_atoms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim_type", "claim", "source_state"],
                "properties": {
                    "claim_type": {"type": "string", "enum": ["announcement", "schedule", "numeric", "result", "award", "status"]},
                    "claim": {"type": "string"},
                    "source_state": {
                        "type": "string",
                        "enum": ["confirmed_update", "scheduled", "published_value", "final_result", "confirmed_award", "confirmed_status"],
                    },
                },
            },
        },
    },
}

CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "category",
        "watch_topic_id",
        "title",
        "source_published_date",
        "source_urls",
        "change_class",
        "summary",
        "material_facts",
        "counter_evidence_checked",
    ],
    "properties": {
        "category": {"type": "string"},
        "watch_topic_id": {"type": "string"},
        "title": {"type": "string"},
        "source_published_date": {"type": "string"},
        "source_urls": {"type": "array", "items": {"type": "string"}},
        "change_class": {
            "type": "string",
            "enum": ["new_event", "material_update", "routine_recurring", "duplicate_followup", "background_only"],
        },
        "summary": {"type": "string"},
        "material_facts": {"type": "array", "items": {"type": "string"}},
        "counter_evidence_checked": {"type": "boolean"},
    },
}

TOPIC_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "candidate_title",
        "adoption_decision",
        "topic_value_class",
        "reader_delta",
        "materiality_basis",
        "reject_reason_class",
        "reject_reason",
    ],
    "properties": {
        "candidate_title": {"type": "string"},
        "adoption_decision": {"type": "string", "enum": ["adopt", "reject"]},
        "topic_value_class": {
            "type": "string",
            "enum": [
                "decision_or_policy",
                "market_or_financial_impact",
                "technical_or_product_shift",
                "operational_status_change",
                "event_result_or_outcome",
                "material_schedule_change",
                "risk_or_safety_signal",
                "cultural_or_audience_signal",
            ],
        },
        "reader_delta": {"type": "string"},
        "materiality_basis": {"type": "string"},
        "reject_reason_class": {
            "type": ["string", "null"],
            "enum": ["duplicate_covered", "lower_importance", "no_material_change", "insufficient_evidence", "insufficient_relevance", None],
        },
        "reject_reason": {"type": ["string", "null"]},
    },
}

ISSUE_STATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issue_date", "state", "frontier", "observations", "candidates", "decisions", "blockers"],
    "properties": {
        "issue_date": {"type": "string"},
        "state": {"type": "string", "enum": STATE_NAMES},
        "frontier": {"type": "array", "items": {"type": "object"}},
        "observations": {"type": "array", "items": SOURCE_OBSERVATION_SCHEMA},
        "candidates": {"type": "array", "items": CANDIDATE_SCHEMA},
        "decisions": {"type": "array", "items": TOPIC_DECISION_SCHEMA},
        "blockers": {"type": "array", "items": {"type": "string"}},
    },
}

SCHEMAS = {
    "source_observation": SOURCE_OBSERVATION_SCHEMA,
    "candidate": CANDIDATE_SCHEMA,
    "topic_decision": TOPIC_DECISION_SCHEMA,
    "issue_state": ISSUE_STATE_SCHEMA,
}


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL STATE FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must be a JSON object")
    return value


def jst_today() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def category_required_channels(contract: dict[str, Any], category: dict[str, Any]) -> list[str]:
    channels = category.get("required_watch_topic_channels", contract.get("required_watch_topic_channels", ["web", "sns_x", "youtube"]))
    if not isinstance(channels, list) or any(not isinstance(channel, str) for channel in channels):
        fail(f"{category.get('label', '<unknown>')} has invalid required channels")
    return channels


def build_frontier(contract: dict[str, Any]) -> list[dict[str, Any]]:
    categories = contract.get("categories")
    if not isinstance(categories, list) or not categories:
        fail("coverage contract missing categories")

    frontier: list[dict[str, Any]] = []
    for category in categories:
        if not isinstance(category, dict):
            fail("coverage category must be an object")
        label = category.get("label")
        section_id = category.get("section_id")
        if not isinstance(label, str) or not isinstance(section_id, str):
            fail("coverage category missing label or section_id")
        axes = category.get("axes", [])
        topics = category.get("watch_topics", [])
        if not isinstance(axes, list) or not isinstance(topics, list):
            fail(f"{label} axes/watch_topics must be lists")
        axis_terms = sorted({term for axis in axes if isinstance(axis, dict) for term in axis.get("terms", []) if isinstance(term, str)})
        channels = category_required_channels(contract, category)
        for topic in topics:
            if not isinstance(topic, dict) or not isinstance(topic.get("id"), str):
                fail(f"{label} watch topic is invalid")
            topic_terms = [term for term in topic.get("terms", []) if isinstance(term, str)]
            frontier.append(
                {
                    "category": label,
                    "section_id": section_id,
                    "watch_topic_id": topic["id"],
                    "required_channels": channels,
                    "search_terms": sorted(set(axis_terms + topic_terms)),
                    "source_roles": ["primary_or_official", "independent_media_or_data", "social_or_video_signal"],
                }
            )
    return frontier


def selected_issue_date() -> str | None:
    if not MARKER_PATH.exists():
        return None
    return MARKER_PATH.read_text(encoding="utf-8").strip()


def artifact_status(issue_date: str) -> dict[str, bool]:
    return {
        "marker_is_issue_date": selected_issue_date() == issue_date,
        "sample_html": (ROOT / f"night-brief-web-sample-{issue_date}.html").exists(),
        "root_site_html": (ROOT / "site" / "index.html").exists(),
        "dated_site_html": (ROOT / "site" / issue_date / "index.html").exists(),
        "extraction_log": (ROOT / "details" / f"extraction-log-{issue_date}.html").exists(),
        "site_extraction_log": (ROOT / "site" / issue_date / "details" / f"extraction-log-{issue_date}.html").exists(),
    }


def readiness(issue_date: str) -> dict[str, Any]:
    contract = read_json(CONFIG_PATH)
    artifacts = artifact_status(issue_date)
    blockers = [name for name, ok in artifacts.items() if not ok]
    frontier = build_frontier(contract)
    return {
        "issue_date": issue_date,
        "state": "publication_ready" if not blockers else "frontier_built",
        "frontier_count": len(frontier),
        "artifacts": artifacts,
        "blockers": blockers,
        "design": {
            "generation_owner": "missing" if blockers else "current_issue_artifacts",
            "publication_rule": "publish only selected JST-current issue artifacts",
            "ai_contract": "Responses API Structured Outputs can fill observations/candidates/decisions; renderers consume only schema-valid records.",
        },
    }


def required_observation_slots(frontier: list[dict[str, Any]]) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = []
    for item in frontier:
        category = str(item["category"])
        watch_topic_id = str(item["watch_topic_id"])
        channels = item.get("required_channels", [])
        if not isinstance(channels, list):
            fail(f"{category} {watch_topic_id} required_channels must be a list")
        slots.append(
            efficient_slot(
                category=category,
                watch_topic_id=watch_topic_id,
                source_role="primary_or_official",
                channel="web",
            )
        )
        slots.append(
            efficient_slot(
                category=category,
                watch_topic_id=watch_topic_id,
                source_role="independent_media_or_data",
                channel="web",
            )
        )
        for channel in channels:
            if channel in {"sns_x", "youtube"}:
                slots.append(
                    efficient_slot(
                        category=category,
                        watch_topic_id=watch_topic_id,
                        source_role="social_or_video_signal",
                        channel=channel,
                    )
                )
    return slots


def efficient_slot(category: str, watch_topic_id: str, source_role: str, channel: str) -> dict[str, str]:
    high_velocity_categories = {"OpenAI", "SpaceX", "F1", "YOASOBI / 幾田りら", "宇都宮ブレックス"}
    market_topics = {"market_price_nav", "market_price_reaction", "us_markets_fund_flows_rates"}
    official_topics = {"prices_wages_boj", "official_launch_manifest", "product_release", "race_schedule_results"}

    priority = "normal"
    if category in high_velocity_categories and channel in {"sns_x", "youtube"}:
        priority = "high"
    if watch_topic_id in market_topics or watch_topic_id in official_topics:
        priority = "high"
    if source_role == "independent_media_or_data" and category in {"日本経済", "アジア経済", "北米経済"}:
        priority = "high"

    reuse_policy = "daily_fetch"
    if channel == "youtube" and priority != "high":
        reuse_policy = "reuse_24h_unless_primary_changed"
    if source_role == "independent_media_or_data" and priority == "normal":
        reuse_policy = "reuse_12h_unless_candidate_changed"

    model_route = "cheap_structured_extractor"
    if priority == "high" and source_role == "primary_or_official":
        model_route = "frontier_planner_if_changed"
    if priority == "high" and source_role == "social_or_video_signal":
        model_route = "cheap_extractor_then_frontier_if_ambiguous"

    return {
        "category": category,
        "watch_topic_id": watch_topic_id,
        "source_role": source_role,
        "channel": channel,
        "priority": priority,
        "reuse_policy": reuse_policy,
        "model_route": model_route,
    }


def observation_key(observation: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(observation.get("category", "")),
        str(observation.get("watch_topic_id", "")),
        str(observation.get("source_role", "")),
        str(observation.get("channel", "")),
    )


def coverage_state(observations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    frontier = build_frontier(read_json(CONFIG_PATH))
    slots = required_observation_slots(frontier)
    observations = observations or []
    observed = {observation_key(item) for item in observations if isinstance(item, dict)}
    missing = [
        slot
        for slot in slots
        if (
            slot["category"],
            slot["watch_topic_id"],
            slot["source_role"],
            slot["channel"],
        )
        not in observed
    ]
    priority_counts = count_by(slots, "priority")
    reuse_counts = count_by(slots, "reuse_policy")
    model_route_counts = count_by(slots, "model_route")
    return {
        "frontier_count": len(frontier),
        "required_observation_slots": len(slots),
        "observed_slots": len(slots) - len(missing),
        "priority_counts": priority_counts,
        "reuse_policy_counts": reuse_counts,
        "model_route_counts": model_route_counts,
        "missing_slots": missing,
        "collection_complete": not missing,
    }


def count_by(items: list[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(key, "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def print_coverage_summary(value: dict[str, Any]) -> None:
    categories: dict[str, int] = {}
    for slot in value["missing_slots"]:
        categories[slot["category"]] = categories.get(slot["category"], 0) + 1
    print(
        json.dumps(
            {
                "collection_complete": value["collection_complete"],
                "frontier_count": value["frontier_count"],
                "required_observation_slots": value["required_observation_slots"],
                "observed_slots": value["observed_slots"],
                "missing_slots": len(value["missing_slots"]),
                "missing_slots_by_category": dict(sorted(categories.items())),
                "model_route_counts": value["model_route_counts"],
                "priority_counts": value["priority_counts"],
                "reuse_policy_counts": value["reuse_policy_counts"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def self_test() -> None:
    contract = read_json(CONFIG_PATH)
    frontier = build_frontier(contract)
    categories = contract.get("categories", [])
    topic_count = sum(len(category.get("watch_topics", [])) for category in categories if isinstance(category, dict))
    if len(frontier) != topic_count:
        fail(f"frontier count mismatch: {len(frontier)} != {topic_count}")
    for name, schema in SCHEMAS.items():
        if schema.get("type") != "object" or not schema.get("required"):
            fail(f"{name} schema is not strict enough")
    coverage = coverage_state([])
    if coverage["required_observation_slots"] <= len(frontier):
        fail("observation slots must expand source roles/channels beyond watch topics")
    if coverage["collection_complete"]:
        fail("empty observations must not be collection-complete")
    if coverage["priority_counts"].get("high", 0) <= 0:
        fail("coverage state must identify high-priority slots")
    if coverage["reuse_policy_counts"].get("reuse_24h_unless_primary_changed", 0) <= 0:
        fail("coverage state must identify reusable low-change slots")
    print("NIGHT SIGNAL STATE PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", choices=sorted(SCHEMAS))
    parser.add_argument("--frontier", action="store_true")
    parser.add_argument("--coverage-state", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--readiness", action="store_true")
    parser.add_argument("--date", default=jst_today())
    parser.add_argument("--allow-blocked", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.schema:
        print_json(SCHEMAS[args.schema])
        return 0
    if args.frontier:
        print_json(build_frontier(read_json(CONFIG_PATH)))
        return 0
    if args.coverage_state:
        state = coverage_state([])
        if args.summary:
            print_coverage_summary(state)
        else:
            print_json(state)
        return 0
    if args.readiness:
        state = readiness(args.date)
        print_json(state)
        if state["blockers"] and not args.allow_blocked:
            return 1
        return 0
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
