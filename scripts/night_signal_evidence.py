#!/usr/bin/env python3
"""Build the canonical Evidence bundle from verified source results."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = ROOT / "config" / "night_signal_sources.json"
COVERAGE_CONFIG = ROOT / "config" / "night_signal_coverage.json"
# Bump only when collection semantics or the Evidence schema changes. Editor and
# renderer changes must not invalidate an already verified same-day collection.
COLLECTOR_CONTRACT_REVISION = "2971bda468f60d99"
SOURCE_CHECK_STATES = {"observed_live", "source_unavailable"}
DISCOVERY_CHECK_STATES = {
    "searched_no_results",
    "searched_no_material_results",
    "searched_resolved",
    "searched_unresolved",
    "search_unavailable",
}


class EvidenceContractError(ValueError):
    """The collector output does not satisfy the canonical Evidence contract."""


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


def collector_contract_version() -> str:
    return COLLECTOR_CONTRACT_REVISION


def required_channels(contract: dict[str, Any], category: dict[str, Any]) -> set[str]:
    values = category.get(
        "required_watch_topic_channels",
        contract.get("required_watch_topic_channels", ["web"]),
    )
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise EvidenceContractError(
            f"{category.get('label', '<unknown>')} has invalid required channels"
        )
    return {value for value in values if value}


def required_discovery_channels(
    contract: dict[str, Any],
    category: dict[str, Any],
) -> set[str]:
    values = category.get(
        "required_discovery_channels",
        contract.get("required_discovery_channels", ["web"]),
    )
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise EvidenceContractError(
            f"{category.get('label', '<unknown>')} has invalid discovery channels"
        )
    return {value for value in values if value}


def category_identity_terms(category: dict[str, Any]) -> tuple[str, ...]:
    values = category.get("identity_terms")
    if not isinstance(values, list) or not values or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise EvidenceContractError(
            f"{category.get('label', '<unknown>')} must define non-empty identity_terms"
        )
    return tuple(dict.fromkeys(value.strip() for value in values))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceContractError(message)


def validate_bundle(
    bundle: dict[str, Any],
    issue_date: str,
    *,
    coverage: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate collection once and return facts reused by every later stage."""
    coverage = coverage or load_object(COVERAGE_CONFIG)
    registry_value = registry or load_object(SOURCE_CONFIG)
    registry_categories = registry_value.get("categories")
    _require(isinstance(registry_categories, dict), "source registry categories must be an object")
    configured = {
        str(category["label"]): category
        for category in coverage.get("categories", [])
        if isinstance(category, dict) and isinstance(category.get("label"), str)
    }
    _require(bundle.get("issue_date") == issue_date, "Evidence date does not match issue date")
    checked_at = bundle.get("checked_at_jst")
    _require(
        isinstance(checked_at, str) and checked_at.startswith(issue_date),
        "Evidence checked_at_jst must be on the issue date",
    )
    try:
        checked_datetime = datetime.fromisoformat(str(checked_at))
    except ValueError as exc:
        raise EvidenceContractError("Evidence checked_at_jst must be ISO-8601") from exc
    _require(checked_datetime.tzinfo is not None, "Evidence checked_at_jst must include a timezone")
    categories = bundle.get("categories")
    _require(
        isinstance(categories, dict) and set(categories) == set(configured),
        "Evidence must cover every configured category exactly once",
    )
    category_reports: dict[str, Any] = {}
    totals = {
        "source_checks": 0,
        "discovery_checks": 0,
        "observed_urls": set(),
        "unresolved_queries": [],
        "editor_coverage_gaps": [],
    }

    for label, category in configured.items():
        category_identity_terms(category)
        _require(
            isinstance(category.get("allow_sports_results", False), bool),
            f"{label} allow_sports_results must be boolean",
        )
        entry = categories[label]
        _require(isinstance(entry, dict), f"Evidence category must be an object: {label}")
        topics = {
            str(topic["id"])
            for topic in category.get("watch_topics", [])
            if isinstance(topic, dict) and isinstance(topic.get("id"), str)
        }
        checked_topics: set[str] = set()
        checked_channels: set[str] = set()
        checked_discovery_channels: set[str] = set()
        checked_seed_urls: set[str] = set()
        observed_urls: set[str] = set()

        source_checks = entry.get("source_checks")
        _require(isinstance(source_checks, list) and bool(source_checks), f"{label} has no source checks")
        for index, check in enumerate(source_checks, start=1):
            _require(isinstance(check, dict), f"{label} source_checks[{index}] must be an object")
            url = check.get("url")
            check_state = check.get("slot_state")
            check_topics = check.get("watch_topic_ids")
            channel = check.get("channel")
            _require(
                isinstance(url, str) and url.startswith(("http://", "https://")),
                f"{label} source_checks[{index}] has an invalid URL",
            )
            _require(check_state in SOURCE_CHECK_STATES, f"{label} source_checks[{index}] has an invalid state")
            _require(
                isinstance(check_topics, list) and all(topic in topics for topic in check_topics),
                f"{label} source_checks[{index}] has invalid watch topics",
            )
            _require(isinstance(channel, str) and bool(channel), f"{label} source_checks[{index}] has no channel")
            _require(
                str(check.get("checked_at_jst", "")).startswith(issue_date),
                f"{label} source_checks[{index}] has a stale check time",
            )
            _require(
                isinstance(check.get("evidence_summary"), str)
                and bool(str(check.get("evidence_summary")).strip()),
                f"{label} source_checks[{index}] has no evidence summary",
            )
            method = check.get("verification_method")
            _require(isinstance(method, str) and bool(method), f"{label} source_checks[{index}] has no verification method")
            _require(
                (check_state == "source_unavailable") == (method == "unavailable"),
                f"{label} source_checks[{index}] has an inconsistent verification result",
            )
            checked_channels.add(channel)
            checked_seed_urls.add(url)
            if check_state == "observed_live":
                observed_urls.add(url)

        discovery_checks = entry.get("discovery_checks", [])
        _require(
            isinstance(discovery_checks, list) and bool(discovery_checks),
            f"{label} has no discovery checks",
        )
        horizon_searched = False
        unresolved_queries: list[str] = []
        topic_resolution = {
            topic: {"material_candidates": 0, "resolved_candidates": 0}
            for topic in topics
        }
        for index, check in enumerate(discovery_checks, start=1):
            _require(isinstance(check, dict), f"{label} discovery_checks[{index}] must be an object")
            check_state = check.get("slot_state")
            check_topics = check.get("watch_topic_ids")
            purpose = check.get("purpose")
            channel = check.get("channel")
            url = check.get("url")
            _require(
                isinstance(url, str) and url.startswith(("http://", "https://")),
                f"{label} discovery_checks[{index}] has an invalid URL",
            )
            _require(check_state in DISCOVERY_CHECK_STATES, f"{label} discovery_checks[{index}] has an invalid state")
            _require(
                isinstance(check_topics, list) and all(topic in topics for topic in check_topics),
                f"{label} discovery_checks[{index}] has invalid watch topics",
            )
            _require(
                (purpose == "watch_topic" and len(check_topics) == 1)
                or (purpose == "horizon" and not check_topics),
                f"{label} discovery_checks[{index}] has an invalid purpose mapping",
            )
            _require(
                str(check.get("checked_at_jst", "")).startswith(issue_date),
                f"{label} discovery_checks[{index}] has a stale check time",
            )
            _require(
                isinstance(check.get("query"), str) and bool(str(check.get("query")).strip()),
                f"{label} discovery_checks[{index}] has no query",
            )
            _require(
                isinstance(channel, str) and bool(channel),
                f"{label} discovery_checks[{index}] has no channel",
            )
            _require(
                isinstance(check.get("evidence_summary"), str)
                and bool(str(check.get("evidence_summary")).strip()),
                f"{label} discovery_checks[{index}] has no evidence summary",
            )
            for metric in (
                "result_count",
                "relevant_result_count",
                "material_candidate_count",
                "resolved_candidate_count",
            ):
                _require(
                    isinstance(check.get(metric), int) and int(check[metric]) >= 0,
                    f"{label} discovery_checks[{index}] has invalid {metric}",
                )
            _require(
                int(check["resolved_candidate_count"])
                <= int(check["material_candidate_count"]),
                f"{label} discovery_checks[{index}] resolves more candidates than it found",
            )
            checked_discovery_channels.add(str(channel))
            if check_state != "search_unavailable":
                checked_topics.update(str(topic) for topic in check_topics)
                horizon_searched = horizon_searched or purpose == "horizon"
            if int(check["material_candidate_count"]) and not int(
                check["resolved_candidate_count"]
            ):
                unresolved_queries.append(str(check.get("query_id", index)))
            if purpose == "watch_topic":
                topic = str(check_topics[0])
                topic_resolution[topic]["material_candidates"] += int(
                    check["material_candidate_count"]
                )
                topic_resolution[topic]["resolved_candidates"] += int(
                    check["resolved_candidate_count"]
                )

        seed_urls = {
            str(source.get("url"))
            for source in registry_categories.get(label, [])
            if isinstance(source, dict) and isinstance(source.get("url"), str)
        }
        _require(seed_urls <= checked_seed_urls, f"{label} has seed sources without explicit result states")
        _require(topics <= checked_topics, f"{label} has unchecked watch topics")
        _require(horizon_searched, f"{label} has no completed horizon search")
        _require(
            required_channels(coverage, category) <= checked_channels,
            f"{label} has unchecked channels",
        )
        _require(
            required_discovery_channels(coverage, category)
            <= checked_discovery_channels,
            f"{label} has unchecked discovery channels",
        )

        records = entry.get("records")
        _require(isinstance(records, list), f"{label} records must be a list")
        records_by_url: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            url = str(record.get("url", ""))
            if not url.startswith(("http://", "https://")):
                continue
            records_by_url.setdefault(url, []).append(record)
            if record.get("observed"):
                observed_urls.add(url)
        observed_record_urls = {
            url
            for url, url_records in records_by_url.items()
            if any(record.get("observed") for record in url_records)
        }
        _require(bool(observed_urls), f"{label} has no observed evidence URL")
        editor_coverage_gaps = [
            topic
            for topic, counts in topic_resolution.items()
            if counts["material_candidates"] > 0
            and counts["resolved_candidates"] == 0
        ]
        category_reports[label] = {
            "topics": topics,
            "checked_topics": checked_topics,
            "checked_discovery_channels": checked_discovery_channels,
            "records_by_url": records_by_url,
            "observed_urls": observed_urls,
            "observed_record_urls": observed_record_urls,
            "source_checks": len(source_checks),
            "discovery_checks": len(discovery_checks),
            "unresolved_queries": unresolved_queries,
            "topic_resolution": topic_resolution,
            "editor_coverage_gaps": editor_coverage_gaps,
        }
        totals["source_checks"] += len(source_checks)
        totals["discovery_checks"] += len(discovery_checks)
        totals["observed_urls"].update(observed_urls)
        totals["unresolved_queries"].extend(
            f"{label}: {query_id}" for query_id in unresolved_queries
        )
        totals["editor_coverage_gaps"].extend(
            f"{label}/{topic}" for topic in editor_coverage_gaps
        )

    return {
        "categories": category_reports,
        "source_checks": totals["source_checks"],
        "discovery_checks": totals["discovery_checks"],
        "observed_urls": totals["observed_urls"],
        "unresolved_queries": totals["unresolved_queries"],
        "editor_coverage_gaps": totals["editor_coverage_gaps"],
    }


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
    bundle = {
        "issue_date": issue_date,
        "checked_at_jst": checked_at,
        "collection_mode": collection_mode,
        "collector_contract_version": collector_contract_version(),
        "categories": categories,
    }
    try:
        validate_bundle(bundle, issue_date)
    except EvidenceContractError as exc:
        fail(str(exc))
    return bundle


def write_bundle(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def bundle_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
