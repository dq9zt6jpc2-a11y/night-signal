#!/usr/bin/env python3
"""Build the canonical Evidence bundle from verified source results."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = ROOT / "config" / "night_signal_sources.json"
COVERAGE_CONFIG = ROOT / "config" / "night_signal_coverage.json"
COLLECTOR_CONTRACT_VERSION = 2


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


def build_evidence_bundle(
    issue_date: str,
    checked_at: str,
    records_by_category: dict[str, list[dict[str, Any]]],
    *,
    discovery_checks_by_category: dict[str, list[dict[str, Any]]],
    collection_mode: str,
) -> dict[str, Any]:
    """Build the pure collector output without editorial items or prose."""
    if not checked_at.startswith(issue_date):
        fail("checked_at_jst must be on the issue date")
    registry = load_object(SOURCE_CONFIG).get("categories")
    if not isinstance(registry, dict):
        fail("source registry categories must be an object")
    topics_by_category = category_topics()
    if set(records_by_category) != set(topics_by_category):
        fail("evidence must cover every configured category exactly once")
    if set(discovery_checks_by_category) != set(topics_by_category):
        fail("discovery checks must cover every configured category exactly once")

    categories: dict[str, Any] = {}
    for category, topics in topics_by_category.items():
        records = [record for record in records_by_category[category] if isinstance(record, dict)]
        by_url = {
            str(record.get("url")): record
            for record in records
            if str(record.get("url", "")).startswith(("http://", "https://"))
        }
        checks: list[dict[str, Any]] = []
        ordered_urls = [
            str(source.get("url"))
            for source in registry.get(category, [])
            if isinstance(source, dict)
        ]
        source_by_url = {
            str(source.get("url")): source
            for source in registry.get(category, [])
            if isinstance(source, dict)
        }
        for url in ordered_urls:
            record = by_url.get(url, {})
            source = source_by_url.get(url, record)
            observed = bool(record.get("observed"))
            summary = str(record.get("evidence") or record.get("excerpt") or "").strip()
            if not observed:
                summary = str(record.get("error") or "source could not be read").strip()
            if not summary:
                fail(f"evidence result has no summary: {category}: {url}")
            checks.append(
                {
                    "watch_topic_ids": [],
                    "source_role": str(source.get("source_role", "independent_media_or_data")),
                    "channel": str(source.get("channel", "web")),
                    "label": str(source.get("label") or record.get("label") or url),
                    "url": url,
                    "slot_state": "observed_live" if observed else "source_unavailable",
                    "published_date": record.get("published_date"),
                    "evidence_summary": summary,
                    "checked_at_jst": checked_at,
                    "verification_method": str(
                        record.get("verification_method")
                        or ("direct_fetch" if observed else "unavailable")
                    ),
                }
            )
        discovery_checks: list[dict[str, Any]] = []
        for check in discovery_checks_by_category[category]:
            if not isinstance(check, dict):
                continue
            summary = str(check.get("evidence_summary") or "").strip()
            if not summary:
                fail(f"discovery result has no summary: {category}")
            discovery_checks.append(
                {
                    **check,
                    "checked_at_jst": checked_at,
                    "evidence_summary": summary,
                }
            )
        categories[category] = {
            "records": records,
            "source_checks": checks,
            "discovery_checks": discovery_checks,
        }
    return {
        "issue_date": issue_date,
        "checked_at_jst": checked_at,
        "collection_mode": collection_mode,
        "collector_contract_version": COLLECTOR_CONTRACT_VERSION,
        "categories": categories,
    }


def write_bundle(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def bundle_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
