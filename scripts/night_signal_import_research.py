#!/usr/bin/env python3
"""Import a reviewed research bundle into the canonical NIGHT SIGNAL state.

This is the API-independent recovery path. It accepts current research gathered
by Codex or another reviewed process, then expands it into the same observation,
candidate, decision, card, and manifest contracts used by the Responses path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import night_signal_state as state
import night_signal_synthesize as synthesize


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL RESEARCH IMPORT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_bundle(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing research bundle: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid research bundle JSON: {exc}")
    if not isinstance(value, dict):
        fail("research bundle must be an object")
    return value


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def category_config() -> dict[str, dict[str, Any]]:
    contract = state.read_json(state.CONFIG_PATH)
    return {
        str(category["label"]): category
        for category in contract.get("categories", [])
        if isinstance(category, dict)
    }


def validate_bundle(bundle: dict[str, Any], issue_date: str) -> dict[str, list[dict[str, Any]]]:
    if bundle.get("issue_date") != issue_date:
        fail(f"bundle issue_date mismatch: {bundle.get('issue_date')} != {issue_date}")
    checked_at = bundle.get("checked_at_jst")
    if not isinstance(checked_at, str) or not checked_at.startswith(issue_date):
        fail("checked_at_jst must be an ISO timestamp on the issue date")
    categories = bundle.get("categories")
    if not isinstance(categories, dict):
        fail("bundle categories must be an object")
    configured = category_config()
    if set(categories) != set(configured):
        fail(
            "bundle category mismatch: "
            f"missing={sorted(set(configured) - set(categories))}, "
            f"extra={sorted(set(categories) - set(configured))}"
        )
    normalized: dict[str, list[dict[str, Any]]] = {}
    topic_keys = {
        (str(item["category"]), str(item["watch_topic_id"]))
        for item in state.build_frontier(state.read_json(state.CONFIG_PATH))
    }
    seen_titles: set[str] = set()
    for label, entry in categories.items():
        if not isinstance(entry, dict):
            fail(f"{label} bundle entry must be an object")
        items = entry.get("items")
        signals = entry.get("signals")
        no_change_summary = entry.get("no_change_summary")
        if not isinstance(items, list):
            fail(f"{label} items must be a list")
        if not isinstance(signals, list):
            fail(f"{label} signals must be a list")
        if not isinstance(no_change_summary, str) or len(no_change_summary.strip()) < 20:
            fail(f"{label} no_change_summary is too short")
        normalized[label] = []
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                fail(f"{label} items[{index}] must be an object")
            required_strings = [
                "watch_topic_id",
                "title",
                "summary",
                "source_published_date",
                "topic_value_class",
                "priority_class",
                "slug",
                "detail_summary",
                "what_changed",
                "why_it_matters",
                "limits_or_unknowns",
            ]
            for key in required_strings:
                if not isinstance(item.get(key), str) or not item[key].strip():
                    fail(f"{label} items[{index}] missing {key}")
            if (label, str(item["watch_topic_id"])) not in topic_keys:
                fail(f"{label} items[{index}] uses unknown watch topic")
            if item["title"] in seen_titles:
                fail(f"duplicate item title: {item['title']}")
            seen_titles.add(item["title"])
            facts = item.get("confirmed_facts")
            sources = item.get("sources")
            if not isinstance(facts, list) or len(facts) < 3:
                fail(f"{label} items[{index}] needs at least three confirmed facts")
            if not isinstance(sources, list) or not sources or len(sources) > 3:
                fail(f"{label} items[{index}] needs one to three sources")
            for source in sources:
                if (
                    not isinstance(source, dict)
                    or not isinstance(source.get("label"), str)
                    or not isinstance(source.get("url"), str)
                    or not source["url"].startswith(("http://", "https://"))
                ):
                    fail(f"{label} items[{index}] contains invalid source")
            normalized[label].append(item)
        for index, signal in enumerate(signals, start=1):
            if not isinstance(signal, dict):
                fail(f"{label} signals[{index}] must be an object")
            for key in (
                "watch_topic_id",
                "title",
                "summary",
                "source_published_date",
                "source_url",
                "change_class",
                "rejection_reason_class",
                "rejection_reason",
            ):
                if not isinstance(signal.get(key), str) or not signal[key].strip():
                    fail(f"{label} signals[{index}] missing {key}")
            if (label, str(signal["watch_topic_id"])) not in topic_keys:
                fail(f"{label} signals[{index}] uses unknown watch topic")
            if not str(signal["source_url"]).startswith(("http://", "https://")):
                fail(f"{label} signals[{index}] source_url must be absolute")
            if signal["title"] in seen_titles:
                fail(f"duplicate signal title: {signal['title']}")
            seen_titles.add(signal["title"])
        required_topics = {
            topic_id for category, topic_id in topic_keys if category == label
        }
        concrete_topics = {
            str(candidate["watch_topic_id"]) for candidate in [*items, *signals]
        }
        missing_topics = sorted(required_topics - concrete_topics)
        if missing_topics:
            fail(
                f"{label} needs a concrete item or signal for every watch topic: "
                + ", ".join(missing_topics)
            )
    return normalized


def matching_item(
    items: list[dict[str, Any]],
    topic_id: str,
    source_role: str,
    channel: str,
) -> dict[str, Any] | None:
    for item in items:
        if item["watch_topic_id"] != topic_id:
            continue
        if item.get("observation_source_role", "primary_or_official") != source_role:
            continue
        if item.get("observation_channel", "web") != channel:
            continue
        return item
    return None


def source_results(
    task: dict[str, Any],
    items: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    issue_date: str,
) -> list[dict[str, Any]]:
    item_sources = {
        str(source["url"]): item
        for item in items
        for source in item.get("sources", [])
        if isinstance(source, dict)
    }
    results: list[dict[str, Any]] = []
    for target in task.get("source_targets", []):
        if not isinstance(target, dict):
            continue
        url = str(target["url"])
        item = item_sources.get(url)
        results.append(
            {
                "label": str(target["label"]),
                "url": url,
                "channel": str(target["channel"]),
                "slot_state": "observed_live",
                "published_date": item["source_published_date"] if item else None,
                "evidence_summary": (
                    f"{item['title']}の直接資料を確認した。"
                    if item
                    else f"{issue_date}時点の更新有無を確認した。"
                ),
            }
        )
    for signal in signals:
        if signal.get("observation_source_role", "primary_or_official") != task["source_role"]:
            continue
        if signal.get("observation_channel", "web") != task["channel"]:
            continue
        results.append(
            {
                "label": str(signal["title"]),
                "url": str(signal["source_url"]),
                "channel": str(signal.get("observation_channel", "web")),
                "slot_state": "observed_live",
                "published_date": str(signal["source_published_date"]),
                "evidence_summary": str(signal["summary"]),
            }
        )
    return results


def build_observations(
    bundle: dict[str, Any],
    items_by_category: dict[str, list[dict[str, Any]]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    issue_date = str(bundle["issue_date"])
    checked_at = str(bundle["checked_at_jst"])
    observations: list[dict[str, Any]] = []
    used_item_titles: set[str] = set()
    for task in plan.get("tasks", []):
        if not isinstance(task, dict):
            continue
        category = str(task["category"])
        items = items_by_category[category]
        signals = [
            signal
            for signal in bundle["categories"][category]["signals"]
            if isinstance(signal, dict)
        ]
        targets = source_results(task, items, signals, issue_date)
        if not targets:
            fail(f"{task.get('slot_id')} has no source targets")
        for topic in task.get("watch_topics", []):
            topic_id = str(topic["watch_topic_id"])
            item = matching_item(
                items,
                topic_id,
                str(task["source_role"]),
                str(task["channel"]),
            )
            if item and item["title"] not in used_item_titles:
                primary_source = item["sources"][0]
                claim_atoms = [
                    {
                        "claim_type": str(item.get("claim_type", "announcement")),
                        "claim": str(fact),
                        "source_state": str(item.get("source_state", "confirmed_update")),
                    }
                    for fact in item["confirmed_facts"]
                ]
                observation_url = str(primary_source["url"])
                published_date: str | None = str(item["source_published_date"])
                evidence_summary = str(item["summary"])
                used_item_titles.add(str(item["title"]))
            else:
                observation_url = str(targets[0]["url"])
                published_date = None
                claim_atoms = []
                evidence_summary = str(
                    bundle["categories"][category]["no_change_summary"]
                )
            observations.append(
                {
                    "category": category,
                    "watch_topic_id": topic_id,
                    "source_role": str(task["source_role"]),
                    "channel": str(task["channel"]),
                    "slot_state": "observed_live",
                    "url": observation_url,
                    "observed_at_jst": checked_at,
                    "published_date": published_date,
                    "evidence_summary": evidence_summary,
                    "source_target_results": targets,
                    "claim_atoms": claim_atoms,
                    "discovery_findings": [],
                }
            )
    unused = [
        item["title"]
        for items in items_by_category.values()
        for item in items
        if item["title"] not in used_item_titles
    ]
    if unused:
        fail(
            "items could not be assigned to a matching observation route: "
            + ", ".join(unused)
        )
    return observations


def build_findings(
    bundle: dict[str, Any],
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issue_date = str(bundle["issue_date"])
    checked_at = str(bundle["checked_at_jst"])
    reviewable: dict[tuple[str, str, str], dict[str, Any]] = {}
    for category, entry in bundle["categories"].items():
        for item in entry["items"]:
            for source in item["sources"]:
                key = (str(category), str(item["watch_topic_id"]), str(source["url"]))
                reviewable[key] = {
                    "title": str(item["title"]),
                    "url": str(source["url"]),
                    "published_date": str(item["source_published_date"]),
                    "summary": str(item["summary"]),
                    "watch_topic_ids": [str(item["watch_topic_id"])],
                    "finding_state": "fresh_update",
                }
        for signal in entry["signals"]:
            key = (
                str(category),
                str(signal["watch_topic_id"]),
                str(signal["source_url"]),
            )
            reviewable[key] = {
                "title": str(signal["title"]),
                "url": str(signal["source_url"]),
                "published_date": str(signal["source_published_date"]),
                "summary": str(signal["summary"]),
                "watch_topic_ids": [str(signal["watch_topic_id"])],
                "finding_state": "near_miss",
            }

    findings: dict[tuple[str, str, str], dict[str, Any]] = {}
    for observation in observations:
        category = str(observation["category"])
        topic_id = str(observation["watch_topic_id"])
        source_role = str(observation["source_role"])
        channel = str(observation["channel"])
        for result in observation["source_target_results"]:
            url = str(result["url"])
            key = (category, topic_id, url)
            base = reviewable.get(key)
            findings[key] = {
                **(
                    base
                    or {
                        "title": f"{result['label']}の公表内容",
                        "url": url,
                        "published_date": result.get("published_date"),
                        "summary": str(result["evidence_summary"]),
                        "watch_topic_ids": [topic_id],
                        "finding_state": "background",
                    }
                ),
                "issue_date": issue_date,
                "slot_id": (
                    f"reviewed-import-{category}-{source_role}-{channel}"
                ),
                "category": category,
                "source_role": source_role,
                "channel": channel,
                "observed_at_jst": checked_at,
            }
    for key, base in reviewable.items():
        if key in findings:
            continue
        category, topic_id, _ = key
        findings[key] = {
            **base,
            "issue_date": issue_date,
            "slot_id": f"reviewed-import-{category}-additional",
            "category": category,
            "source_role": "independent_media_or_data",
            "channel": "web",
            "observed_at_jst": checked_at,
        }
    return list(findings.values())


def no_change_candidate(
    category: str,
    topic_id: str,
    issue_date: str,
    url: str,
) -> dict[str, Any]:
    readable_topic = topic_id.replace("_", " ")
    return {
        "category": category,
        "watch_topic_id": topic_id,
        "title": f"{category}、{readable_topic}に大きな更新なし",
        "source_published_date": issue_date,
        "source_urls": [url],
        "change_class": "background_only",
        "summary": f"{category}の{readable_topic}について、直近3日間に新しい決定、数値、結果は公表されていない。",
        "material_facts": [],
        "counter_evidence_checked": True,
    }


def item_candidate(category: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": category,
        "watch_topic_id": str(item["watch_topic_id"]),
        "title": str(item["title"]),
        "source_published_date": str(item["source_published_date"]),
        "source_urls": [str(source["url"]) for source in item["sources"]],
        "change_class": str(item.get("change_class", "new_event")),
        "summary": str(item["summary"]),
        "material_facts": [str(fact) for fact in item["confirmed_facts"]],
        "counter_evidence_checked": True,
    }


def item_decision(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_title": str(item["title"]),
        "adoption_decision": "adopt",
        "topic_value_class": str(item["topic_value_class"]),
        "reader_delta": str(item["why_it_matters"]),
        "materiality_basis": str(item["what_changed"]),
        "reject_reason_class": None,
        "reject_reason": None,
    }


def rejected_decision(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_title": str(candidate["title"]),
        "adoption_decision": "reject",
        "topic_value_class": "operational_status_change",
        "reader_delta": "前号後に読者の判断を変える新しい事実はない。",
        "materiality_basis": "直接資料と補助情報で新しい決定、数値、結果がないことを確認した。",
        "reject_reason_class": "no_material_change",
        "reject_reason": "直近3日間の実質的な変化がない。",
    }


def signal_candidate(category: str, signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": category,
        "watch_topic_id": str(signal["watch_topic_id"]),
        "title": str(signal["title"]),
        "source_published_date": str(signal["source_published_date"]),
        "source_urls": [str(signal["source_url"])],
        "change_class": str(signal["change_class"]),
        "summary": str(signal["summary"]),
        "material_facts": [],
        "counter_evidence_checked": True,
    }


def signal_decision(signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_title": str(signal["title"]),
        "adoption_decision": "reject",
        "topic_value_class": str(
            signal.get("topic_value_class", "operational_status_change")
        ),
        "reader_delta": str(signal["summary"]),
        "materiality_basis": str(signal["rejection_reason"]),
        "reject_reason_class": str(signal["rejection_reason_class"]),
        "reject_reason": str(signal["rejection_reason"]),
    }


def item_card(category: str, section_id: str, item: dict[str, Any]) -> dict[str, Any]:
    facts = [str(fact) for fact in item["confirmed_facts"]]
    source_urls = [str(source["url"]) for source in item["sources"]]
    return {
        "candidate_title": str(item["title"]),
        "title": str(item["title"]),
        "summary": str(item["summary"]),
        "section_id": section_id,
        "category": category,
        "source_published_date": str(item["source_published_date"]),
        "topic_value_class": str(item["topic_value_class"]),
        "priority_class": str(item["priority_class"]),
        "detail": {
            "slug": str(item["slug"]),
            "sources": item["sources"],
            "summary": str(item["detail_summary"]),
            "summary_basis": {
                "what_changed": str(item["what_changed"]),
                "why_it_matters": str(item["why_it_matters"]),
                "confirmed_facts": facts,
                "fact_sources": [
                    {"fact": fact, "source_urls": source_urls}
                    for fact in facts
                ],
                "limits_or_unknowns": str(item["limits_or_unknowns"]),
                "source_dates": [str(item["source_published_date"])],
            },
        },
    }


def import_bundle(issue_date: str, bundle_path: Path, state_root: Path) -> dict[str, Any]:
    bundle = read_bundle(bundle_path)
    items_by_category = validate_bundle(bundle, issue_date)
    base = state_root / issue_date
    base.mkdir(parents=True, exist_ok=True)
    plan_path = base / "collection_plan.json"
    if not plan_path.exists():
        state.write_collection_plan(issue_date, state_root)
    plan = state.read_json(plan_path)
    observations = build_observations(bundle, items_by_category, plan)
    findings = build_findings(bundle, observations)
    frontier = state.build_frontier(state.read_json(state.CONFIG_PATH))
    state.validate_observation_records(observations, frontier)

    configs = category_config()
    observation_url_by_topic = {
        (str(item["category"]), str(item["watch_topic_id"])): str(item["url"])
        for item in observations
    }
    results_by_category: dict[str, dict[str, Any]] = {}
    for category, config in configs.items():
        items = items_by_category[category]
        signals = [
            signal
            for signal in bundle["categories"][category]["signals"]
            if isinstance(signal, dict)
        ]
        item_topics = {str(item["watch_topic_id"]) for item in items}
        candidates = [item_candidate(category, item) for item in items]
        candidates.extend(signal_candidate(category, signal) for signal in signals)
        for frontier_item in frontier:
            if frontier_item["category"] != category:
                continue
            topic_id = str(frontier_item["watch_topic_id"])
            if topic_id in item_topics:
                continue
            candidates.append(
                no_change_candidate(
                    category,
                    topic_id,
                    issue_date,
                    observation_url_by_topic[(category, topic_id)],
                )
            )
        item_titles = {str(item["title"]) for item in items}
        signal_titles = {str(signal["title"]) for signal in signals}
        decisions = [
            item_decision(next(item for item in items if item["title"] == candidate["title"]))
            if candidate["title"] in item_titles
            else signal_decision(
                next(signal for signal in signals if signal["title"] == candidate["title"])
            )
            if candidate["title"] in signal_titles
            else rejected_decision(candidate)
            for candidate in candidates
        ]
        cards = [
            item_card(category, str(config["section_id"]), item)
            for item in items
        ]
        results_by_category[category] = {
            "category": category,
            "candidates": candidates,
            "decisions": decisions,
            "cards": cards,
            "no_change_checks": [
                {
                    "topic_id": "category_horizon",
                    "result": str(bundle["categories"][category]["no_change_summary"]),
                    "evidence_urls": sorted(
                        {
                            str(result["url"])
                            for observation in observations
                            if observation["category"] == category
                            for result in observation["source_target_results"]
                        }
                    ),
                }
            ],
        }

    candidates = [
        item
        for result in results_by_category.values()
        for item in result["candidates"]
    ]
    decisions = [
        item
        for result in results_by_category.values()
        for item in result["decisions"]
    ]
    cards = [
        item
        for result in results_by_category.values()
        for item in result["cards"]
    ]
    manifest = synthesize.minimal_manifest(issue_date, results_by_category)
    manifest["last_checked_jst"] = str(bundle["checked_at_jst"])
    manifest["note"] = "Reviewed research imported through the canonical state contract."

    write_jsonl(base / "observations.jsonl", observations)
    write_jsonl(base / "findings.jsonl", findings)
    write_jsonl(base / "candidates.jsonl", candidates)
    write_jsonl(base / "decisions.jsonl", decisions)
    write_jsonl(base / "cards.jsonl", cards)
    (base / "coverage_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = state.assemble_issue_state(issue_date, state_root)
    return {
        **result,
        "research_bundle": str(bundle_path),
        "categories": len(results_by_category),
    }


def self_test() -> None:
    if no_change_candidate("OpenAI", "product_release", "2099-01-01", "https://openai.com/")["change_class"] != "background_only":
        fail("no-change candidate generation failed")
    print("NIGHT SIGNAL RESEARCH IMPORT SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument(
        "--bundle",
        type=Path,
        help="defaults to state/YYYY-MM-DD/research_bundle.json",
    )
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    bundle = args.bundle or args.state_root / args.issue_date / "research_bundle.json"
    print(
        json.dumps(
            import_bundle(args.issue_date, bundle, args.state_root),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
