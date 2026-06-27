#!/usr/bin/env python3
"""Build the canonical Evidence bundle from verified source results."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = ROOT / "config" / "night_signal_sources.json"
COVERAGE_CONFIG = ROOT / "config" / "night_signal_coverage.json"


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL EVIDENCE FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail(f"cannot load {path}: {exc}")
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


def source_check(
    category: str,
    source: dict[str, Any],
    topics: list[str],
    checked_at: str,
    unavailable: dict[str, str],
    evidence_by_url: dict[str, str],
) -> dict[str, Any]:
    url = str(source["url"])
    if url in unavailable:
        state = "source_unavailable"
        summary = str(unavailable[url])
        method = "unavailable"
    elif url in evidence_by_url:
        state = "observed_live"
        summary = str(evidence_by_url[url])
        method = "reviewed_live_web"
    else:
        fail(f"source lacks an observed or unavailable result: {category}: {url}")
    return {
        "watch_topic_ids": topics,
        "source_role": str(source["source_role"]),
        "channel": str(source["channel"]),
        "label": str(source["label"]),
        "url": url,
        "slot_state": state,
        "published_date": None,
        "evidence_summary": summary,
        "checked_at_jst": checked_at,
        "verification_method": method,
    }


def additional_check(
    category: str,
    topic_ids: list[str],
    source: dict[str, Any],
    checked_at: str,
) -> dict[str, Any]:
    url = str(source.get("url", ""))
    summary = str(source.get("evidence_summary", "")).strip()
    if not url.startswith(("http://", "https://")) or not summary:
        fail(f"additional evidence is incomplete: {category}: {url}")
    return {
        "watch_topic_ids": topic_ids,
        "source_role": str(source.get("source_role", "independent_media_or_data")),
        "channel": str(source.get("channel", "web")),
        "label": str(source.get("label") or url),
        "url": url,
        "slot_state": "observed_live",
        "published_date": source.get("published_date"),
        "evidence_summary": summary,
        "checked_at_jst": checked_at,
        "verification_method": "reviewed_live_web",
    }


def build_bundle(
    issue_date: str,
    checked_at: str,
    reviewed_categories: dict[str, dict[str, Any]],
    unavailable: dict[str, str],
    evidence_by_url: dict[str, str],
    *,
    collection_mode: str,
) -> dict[str, Any]:
    if not checked_at.startswith(issue_date):
        fail("checked_at_jst must be on the issue date")
    registry = load_object(SOURCE_CONFIG).get("categories")
    if not isinstance(registry, dict):
        fail("source registry categories must be an object")
    topics_by_category = category_topics()
    if set(reviewed_categories) != set(topics_by_category):
        fail("review must cover every configured category exactly once")

    output: dict[str, Any] = {}
    for category, topics in topics_by_category.items():
        reviewed = reviewed_categories[category]
        items = reviewed.get("items", [])
        signals = reviewed.get("signals", [])
        discovery = reviewed.get("discovery_sources", [])
        no_change = reviewed.get("no_change_summary")
        if not all(isinstance(value, list) for value in (items, signals, discovery)):
            fail(f"{category} items, signals, and discovery_sources must be lists")
        if not isinstance(no_change, str) or len(no_change) < 20:
            fail(f"{category} no_change_summary is too short")

        checks = [
            source_check(category, source, topics, checked_at, unavailable, evidence_by_url)
            for source in registry.get(category, [])
            if isinstance(source, dict)
        ]
        checked_urls = {str(check["url"]) for check in checks}

        extra_sources: list[tuple[list[str], dict[str, Any]]] = []
        for source in discovery:
            if isinstance(source, dict):
                extra_sources.append((topics, source))
        for item in items:
            if not isinstance(item, dict):
                fail(f"{category} item must be an object")
            topic_ids = [str(item.get("watch_topic_id"))]
            for source in item.get("sources", []):
                if isinstance(source, dict):
                    extra_sources.append((topic_ids, source))
        for signal in signals:
            if not isinstance(signal, dict):
                fail(f"{category} signal must be an object")
            extra_sources.append(
                (
                    [str(signal.get("watch_topic_id"))],
                    {
                        "label": signal.get("source_label", signal.get("title")),
                        "url": signal.get("source_url"),
                        "source_role": signal.get("observation_source_role", "independent_media_or_data"),
                        "channel": signal.get("observation_channel", "web"),
                        "published_date": signal.get("source_published_date"),
                        "evidence_summary": signal.get("summary"),
                    },
                )
            )
        for topic_ids, source in extra_sources:
            url = str(source.get("url", ""))
            if url in checked_urls:
                continue
            checks.append(additional_check(category, topic_ids, source, checked_at))
            checked_urls.add(url)

        output[category] = {
            "items": items,
            "signals": signals,
            "source_checks": checks,
            "no_change_summary": no_change,
        }
    return {
        "issue_date": issue_date,
        "checked_at_jst": checked_at,
        "collection_mode": collection_mode,
        "categories": output,
    }


def write_bundle(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
