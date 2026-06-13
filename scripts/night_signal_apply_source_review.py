#!/usr/bin/env python3
"""Apply a human or agent reviewed evidence ledger to a research bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = ROOT / "config" / "night_signal_sources.json"
COVERAGE_CONFIG = ROOT / "config" / "night_signal_coverage.json"


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL SOURCE REVIEW FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"expected object: {path}")
    return value


def category_topics() -> dict[str, list[str]]:
    coverage = load_object(COVERAGE_CONFIG)
    return {
        str(category["label"]): [
            str(topic["id"])
            for topic in category.get("watch_topics", [])
            if isinstance(topic, dict)
        ]
        for category in coverage.get("categories", [])
        if isinstance(category, dict)
    }


def access_record(
    category: str,
    source: dict[str, Any],
    topics: list[str],
    checked_at: str,
    unavailable: dict[str, str],
    evidence: dict[str, str],
) -> dict[str, Any]:
    url = str(source["url"])
    reason = unavailable.get(url)
    if reason:
        slot_state = "source_unavailable"
        summary = reason
        method = "unavailable"
    else:
        slot_state = "observed_live"
        summary = evidence.get(
            url,
            (
                f"{checked_at}に{source['label']}へ直接アクセスし、応答ページを確認した。"
                f"{category}の最新掲載、直近3日の更新、既存候補との差分を照合した。"
            ),
        )
        method = "reviewed_live_web"
    return {
        "watch_topic_ids": topics,
        "source_role": str(source["source_role"]),
        "channel": str(source["channel"]),
        "label": str(source["label"]),
        "url": url,
        "slot_state": slot_state,
        "published_date": None,
        "evidence_summary": summary,
        "checked_at_jst": checked_at,
        "verification_method": method,
    }


def extra_source_check(
    category: str,
    topic_id: str,
    source: dict[str, Any],
    checked_at: str,
) -> dict[str, Any]:
    return {
        "watch_topic_ids": [topic_id],
        "source_role": str(source.get("source_role", "primary_or_official")),
        "channel": str(source.get("channel", "web")),
        "label": str(source["label"]),
        "url": str(source["url"]),
        "slot_state": "observed_live",
        "published_date": source.get("published_date"),
        "evidence_summary": str(
            source.get(
                "evidence_summary",
                f"{checked_at}に直接URLを確認し、{category}の当日候補の根拠として照合した。",
            )
        ),
        "checked_at_jst": checked_at,
        "verification_method": "reviewed_live_web",
    }


def apply_review(issue_date: str, bundle_path: Path, review_path: Path) -> dict[str, Any]:
    bundle = load_object(bundle_path)
    review = load_object(review_path)
    if bundle.get("issue_date") != issue_date or review.get("issue_date") != issue_date:
        fail("issue date mismatch")
    checked_at = review.get("checked_at_jst")
    if not isinstance(checked_at, str) or not checked_at.startswith(issue_date):
        fail("review checked_at_jst must be on the issue date")

    source_config = load_object(SOURCE_CONFIG)
    registry = source_config.get("categories")
    if not isinstance(registry, dict):
        fail("source registry categories must be an object")
    topics_by_category = category_topics()
    reviewed_categories = review.get("categories")
    if not isinstance(reviewed_categories, dict):
        fail("review categories must be an object")
    if set(reviewed_categories) != set(topics_by_category):
        fail("review must cover every configured category exactly once")

    unavailable = review.get("unavailable_urls", {})
    evidence = review.get("evidence_by_url", {})
    if not isinstance(unavailable, dict) or not isinstance(evidence, dict):
        fail("unavailable_urls and evidence_by_url must be objects")

    output_categories: dict[str, Any] = {}
    for category, topics in topics_by_category.items():
        reviewed = reviewed_categories[category]
        if not isinstance(reviewed, dict):
            fail(f"{category} review must be an object")
        items = reviewed.get("items", [])
        signals = reviewed.get("signals", [])
        no_change_summary = reviewed.get("no_change_summary")
        if not isinstance(items, list) or not isinstance(signals, list):
            fail(f"{category} items and signals must be lists")
        if not isinstance(no_change_summary, str) or len(no_change_summary) < 20:
            fail(f"{category} no_change_summary is too short")

        checks = [
            access_record(
                category,
                source,
                topics,
                checked_at,
                unavailable,
                evidence,
            )
            for source in registry.get(category, [])
            if isinstance(source, dict)
        ]
        checked_urls = {str(check["url"]) for check in checks}
        for item in items:
            if not isinstance(item, dict):
                fail(f"{category} item must be an object")
            topic_id = str(item.get("watch_topic_id"))
            for source in item.get("sources", []):
                if isinstance(source, dict) and str(source.get("url")) not in checked_urls:
                    checks.append(extra_source_check(category, topic_id, source, checked_at))
                    checked_urls.add(str(source["url"]))
        for signal in signals:
            if not isinstance(signal, dict):
                fail(f"{category} signal must be an object")
            url = str(signal.get("source_url"))
            if url not in checked_urls:
                checks.append(
                    extra_source_check(
                        category,
                        str(signal.get("watch_topic_id")),
                        {
                            "label": signal.get("source_label", signal.get("title")),
                            "url": url,
                            "source_role": signal.get(
                                "observation_source_role",
                                "independent_media_or_data",
                            ),
                            "channel": signal.get("observation_channel", "web"),
                            "published_date": signal.get("source_published_date"),
                            "evidence_summary": signal.get("summary"),
                        },
                        checked_at,
                    )
                )
                checked_urls.add(url)
        output_categories[category] = {
            "items": items,
            "signals": signals,
            "source_checks": checks,
            "no_change_summary": no_change_summary,
        }

    bundle["checked_at_jst"] = checked_at
    bundle["categories"] = output_categories
    temp = bundle_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(bundle_path)
    return {
        "issue_date": issue_date,
        "checked_at_jst": checked_at,
        "categories": len(output_categories),
        "source_checks": sum(
            len(entry["source_checks"])
            for entry in output_categories.values()
        ),
        "items": sum(len(entry["items"]) for entry in output_categories.values()),
        "signals": sum(len(entry["signals"]) for entry in output_categories.values()),
        "bundle": str(bundle_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--review", type=Path)
    args = parser.parse_args()
    bundle = args.bundle or ROOT / "state" / args.issue_date / "research_bundle.json"
    review = args.review or ROOT / "state" / args.issue_date / "source_review.json"
    print(json.dumps(apply_review(args.issue_date, bundle, review), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
