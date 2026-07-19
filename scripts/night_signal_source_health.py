#!/usr/bin/env python3
"""Shared source-depth diagnostics for pre-editor and post-publication stages."""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse

import night_signal_core as core


def normalized_host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def collection_observation(entry: dict[str, Any]) -> dict[str, Any]:
    unavailable = [
        {
            "label": str(check.get("label", "")),
            "url": str(check.get("url", "")),
        }
        for check in entry.get("source_checks", [])
        if isinstance(check, dict)
        and check.get("channel") == "web"
        and check.get("slot_state") == "source_unavailable"
    ]
    depth_results = [
        {
            "query_id": str(check.get("query_id", "")),
            "slot_state": str(check.get("slot_state", "")),
            "target_source_class": str(check.get("target_source_class", "")),
            "allowed_hosts": [
                str(host)
                for host in check.get("allowed_hosts", [])
                if isinstance(host, str)
            ],
            "fallback_attempted": bool(check.get("fallback_attempted")),
            "material_candidates": int(check.get("material_candidate_count", 0)),
            "resolved_candidates": int(check.get("resolved_candidate_count", 0)),
        }
        for check in entry.get("discovery_checks", [])
        if isinstance(check, dict)
        and str(check.get("query_id", "")).startswith("depth:")
    ]
    return {
        "unavailable_web_seeds": unavailable,
        "depth_query_results": depth_results,
    }


def pre_editor_report(
    issue_date: str,
    evidence: dict[str, Any],
    gaps: list[str],
) -> dict[str, Any]:
    """Preserve source causes even if editor packet preparation must stop."""
    categories: dict[str, Any] = {}
    for label, entry in evidence.get("categories", {}).items():
        if not isinstance(entry, dict):
            continue
        observation = collection_observation(entry)
        category_gaps = [
            gap for gap in gaps if str(gap).startswith(f"{label}/")
        ]
        causes: list[str] = []
        actions: list[str] = []
        if category_gaps:
            causes.append("material_topic_without_resolved_body")
            actions.append("accessible_primary_or_specialist_corroboration")
        if observation["unavailable_web_seeds"]:
            causes.append("web_seed_unavailable")
            actions.append("bounded_reader_and_source_search_fallback")
        categories[str(label)] = {
            "editor_coverage_gaps": category_gaps,
            **observation,
            "causes": causes,
            "actions": actions,
        }
    return {
        "contract": "night-signal-source-gap-v1",
        "issue_date": issue_date,
        "collector_contract_version": evidence.get("collector_contract_version"),
        "publisher_portfolio_version": evidence.get(
            "publisher_portfolio_contract", {}
        ).get("portfolio_version"),
        "editor_coverage_gaps": gaps,
        "categories": categories,
        "automatic_config_mutation": False,
    }


def post_publication_diagnostics(
    bundle: dict[str, Any],
    issue: dict[str, Any],
    issue_date: str,
) -> dict[str, dict[str, Any]]:
    """Explain source-depth gaps and bounded recovery for every category."""
    categories = bundle.get("categories", {})
    cards_by_category: dict[str, list[dict[str, Any]]] = {}
    for card in issue.get("cards", []):
        if isinstance(card, dict):
            cards_by_category.setdefault(str(card.get("category", "")), []).append(
                card
            )
    diagnostics: dict[str, dict[str, Any]] = {}
    for category in core.category_contracts():
        label = str(category["label"])
        entry = categories.get(label, {})
        if not isinstance(entry, dict):
            continue
        observation = collection_observation(entry)
        depth_results = observation["depth_query_results"]
        records = [
            record
            for record in entry.get("records", [])
            if isinstance(record, dict)
        ]
        body_records = [
            record
            for record in records
            if core.publication_evidence_record(category, issue_date, record)
            and core.record_evidence_depth(core.record_public_title(record), record)
            == "body"
        ]
        trusted_body_records = [
            record
            for record in body_records
            if core.record_has_trusted_editor_source(record)
        ]
        body_classes = Counter(
            core.effective_source_class(record) for record in body_records
        )
        trusted_body_topics = {
            str(topic_id)
            for record in trusted_body_records
            for topic_id in record.get("watch_topic_ids", [])
            if str(topic_id)
        }
        material_topics = {
            str(topic_id)
            for check in entry.get("discovery_checks", [])
            if isinstance(check, dict)
            and int(check.get("material_candidate_count", 0)) > 0
            for topic_id in check.get("watch_topic_ids", [])
            if str(topic_id)
        }
        weak_material_topics = sorted(material_topics - trusted_body_topics)
        depth_unresolved = sum(
            result["material_candidates"] > 0
            and result["resolved_candidates"] == 0
            for result in depth_results
        )

        record_by_url: dict[str, dict[str, Any]] = {}
        for record in records:
            for key in ("url", "resolved_url", "original_discovery_url"):
                value = str(record.get(key, ""))
                if value.startswith(("http://", "https://")):
                    record_by_url[value] = record
        published_cards = cards_by_category.get(label, [])
        citation_urls = {
            str(url)
            for card in published_cards
            for mapping in (
                card.get("detail", {}).get("summary_basis", {}).get(
                    "fact_sources", []
                )
                if isinstance(card.get("detail"), dict)
                else []
            )
            if isinstance(mapping, dict)
            for url in mapping.get("source_urls", [])
            if isinstance(url, str)
        }
        citation_hosts = {
            normalized_host(url) for url in citation_urls if normalized_host(url)
        }
        citation_classes = {
            core.effective_source_class(record_by_url[url])
            for url in citation_urls
            if url in record_by_url
        }
        configured_publishers = core.configured_depth_publishers().get(label, [])
        configured_specialist_hosts = {
            normalized_host(str(publisher.get("url", "")))
            for publisher in configured_publishers
            if publisher.get("source_class") == "specialist_media"
        }
        observed_specialist_hosts = {
            normalized_host(str(record.get("url", "")))
            for record in body_records
            if core.effective_source_class(record) == "specialist_media"
            and normalized_host(str(record.get("url", "")))
        }

        causes: list[str] = []
        actions: list[str] = []
        if weak_material_topics:
            causes.append("material_topic_without_trusted_body")
            actions.append("topic_targeted_specialist_depth_recovery")
        if depth_unresolved:
            causes.append("specialist_depth_candidate_unresolved")
            actions.append("accessible_primary_or_independent_corroboration")
        if observation["unavailable_web_seeds"]:
            causes.append("web_seed_unavailable")
            actions.append("bounded_reader_and_source_search_fallback")
        if (
            published_cards
            and configured_specialist_hosts
            and "specialist_media" not in citation_classes
        ):
            causes.append("published_without_specialist_corroboration")
            actions.append("retain_specialist_corroboration_priority")
        if len(published_cards) >= 2 and len(citation_hosts) == 1:
            causes.append("published_source_concentration")
            actions.append("seek_independent_specialist_source")
        diagnostics[label] = {
            "material_topics": sorted(material_topics),
            "trusted_body_topics": sorted(trusted_body_topics),
            "weak_material_topics": weak_material_topics,
            "body_records_by_source_class": dict(sorted(body_classes.items())),
            "configured_specialist_hosts": len(configured_specialist_hosts),
            "observed_specialist_body_host_count": len(observed_specialist_hosts),
            "observed_specialist_body_hosts": sorted(observed_specialist_hosts),
            "depth_recovery_queries": len(depth_results),
            "depth_recovery_resolved_candidates": sum(
                result["resolved_candidates"] for result in depth_results
            ),
            "depth_recovery_unresolved_queries": depth_unresolved,
            "depth_recovery_targeted_queries": sum(
                bool(result.get("allowed_hosts")) for result in depth_results
            ),
            "depth_recovery_specialist_resolved_candidates": sum(
                result["resolved_candidates"]
                for result in depth_results
                if result.get("target_source_class") == "specialist_media"
            ),
            "depth_recovery_fallback_queries": sum(
                bool(result.get("fallback_attempted")) for result in depth_results
            ),
            "depth_query_results": depth_results,
            "unavailable_web_seeds": len(
                observation["unavailable_web_seeds"]
            ),
            "published_updates": len(published_cards),
            "published_citation_hosts": sorted(citation_hosts),
            "published_source_classes": sorted(citation_classes),
            "causes": causes,
            "actions": list(dict.fromkeys(actions)),
        }
    return diagnostics


def self_test() -> None:
    observation = collection_observation(
        {
            "source_checks": [
                {
                    "label": "Official",
                    "url": "https://example.com/news",
                    "channel": "web",
                    "slot_state": "source_unavailable",
                }
            ],
            "discovery_checks": [
                {
                    "query_id": "depth:publisher:test:bing",
                    "slot_state": "searched_unresolved",
                    "material_candidate_count": 1,
                    "resolved_candidate_count": 0,
                }
            ],
        }
    )
    if len(observation["unavailable_web_seeds"]) != 1:
        raise AssertionError("source health lost an unavailable official source")
    if observation["depth_query_results"][0]["material_candidates"] != 1:
        raise AssertionError("source health lost a depth recovery result")
