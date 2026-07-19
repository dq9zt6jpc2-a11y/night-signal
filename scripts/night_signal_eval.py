#!/usr/bin/env python3
"""Evaluate coverage, precision, quality, and efficiency with a short history."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import night_signal_state as state
import night_signal_evidence as evidence_store
import night_signal_core as core
import night_signal_source_health as source_health


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL EVAL FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def review_packet_metrics(base: Path) -> dict[str, int]:
    path = base / "editor_packet.json"
    if not path.exists():
        return {"review_requests": 0, "review_events": 0, "review_payload_bytes": 0}
    packet = read_object(path)
    requests = [value for value in packet.get("requests", []) if isinstance(value, dict)]
    return {
        "review_requests": len(requests),
        "review_events": sum(
            len(request.get("payload", {}).get("events", []))
            for request in requests
            if isinstance(request.get("payload"), dict)
        ),
        "review_payload_bytes": len(
            json.dumps(requests, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ),
    }


def metric_deltas(current: dict[str, Any], previous: dict[str, Any]) -> dict[str, int]:
    keys = (
        "source_checks",
        "discovery_checks",
        "material_candidates",
        "resolved_candidates",
        "published_updates",
        "unavailable_urls",
        "review_requests",
        "review_events",
        "review_payload_bytes",
        "local_horizon_queries",
        "local_horizon_material_candidates",
        "local_horizon_resolved_candidates",
        "scoped_official_sources_configured",
        "scoped_official_sources_observed",
        "expanded_evidence_records",
        "expanded_published_updates",
        "confirmed_facts",
        "summary_characters",
        "one_fact_updates",
        "facts_per_update_milli",
        "summary_chars_per_update_milli",
        "one_fact_update_ratio_milli",
        "body_evidence_records",
        "trusted_body_evidence_records",
        "specialist_body_evidence_records",
        "multi_source_updates",
        "specialist_source_updates",
        "analysis_updates",
        "body_backed_cited_urls",
        "non_body_cited_urls",
        "editor_coverage_gap_count",
        "unattempted_editor_coverage_gap_count",
        "targeted_depth_queries",
        "specialist_depth_resolved_candidates",
        "depth_fallback_queries",
    )
    return {
        key: int(current.get(key, 0)) - int(previous.get(key, 0))
        for key in keys
    }


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail(f"cannot load {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def evaluate(
    issue_date: str,
    state_root: Path,
    *,
    include_history: bool = True,
) -> dict[str, Any]:
    base = state_root / issue_date
    issue_path = base / "issue.json"
    issue = read_object(issue_path)
    bundle = read_object(base / "evidence.json")
    state.validate_issue_state(issue, issue_path)
    try:
        evidence_report = evidence_store.validate_bundle(bundle, issue_date)
    except evidence_store.EvidenceContractError as exc:
        fail(str(exc))

    contract = state.read_json(state.CONFIG_PATH)
    configured = {
        str(category["label"]): {
            str(topic.get("id"))
            for topic in category.get("watch_topics", [])
            if isinstance(topic, dict)
        }
        for category in contract.get("categories", [])
        if isinstance(category, dict)
    }
    categories = bundle.get("categories")
    if not isinstance(categories, dict):
        fail("research bundle categories must be an object")

    source_checks = evidence_report["source_checks"]
    discovery_checks = evidence_report["discovery_checks"]
    material_candidates = 0
    resolved_candidates = 0
    unresolved_queries = list(evidence_report["unresolved_queries"])
    editor_coverage_gaps = [
        str(value) for value in evidence_report.get("editor_coverage_gaps", [])
    ]
    unattempted_editor_coverage_gaps = core.remaining_editor_coverage_gaps(
        bundle,
        evidence_report,
    )
    observed_urls = set(evidence_report["observed_urls"])
    unavailable_urls: set[str] = set()
    local_horizon_queries = 0
    local_horizon_relevant_results = 0
    local_horizon_material_candidates = 0
    local_horizon_resolved_candidates = 0
    targeted_depth_queries = 0
    specialist_depth_resolved_candidates = 0
    depth_fallback_queries = 0
    reviewed_topics = {
        (label, topic)
        for label, report in evidence_report["categories"].items()
        for topic in report["checked_topics"]
    }
    for entry in categories.values():
        if not isinstance(entry, dict):
            continue
        for check in entry.get("source_checks", []):
            if not isinstance(check, dict):
                continue
            url = check.get("url")
            if isinstance(url, str) and check.get("slot_state") == "source_unavailable":
                unavailable_urls.add(url)
        for check in entry.get("discovery_checks", []):
            if not isinstance(check, dict):
                continue
            material_candidates += int(check.get("material_candidate_count", 0))
            resolved_candidates += int(check.get("resolved_candidate_count", 0))
            if str(check.get("query_id", "")).startswith("depth:"):
                targeted_depth_queries += bool(check.get("allowed_hosts"))
                depth_fallback_queries += bool(check.get("fallback_attempted"))
                if check.get("target_source_class") == "specialist_media":
                    specialist_depth_resolved_candidates += int(
                        check.get("resolved_candidate_count", 0)
                    )
            if str(check.get("query_id", "")).startswith(
                "horizon:local-language:"
            ):
                local_horizon_queries += 1
                local_horizon_relevant_results += int(
                    check.get("relevant_result_count", 0)
                )
                local_horizon_material_candidates += int(
                    check.get("material_candidate_count", 0)
                )
                local_horizon_resolved_candidates += int(
                    check.get("resolved_candidate_count", 0)
                )

    expanded_urls = {
        str(record.get("url"))
        for entry in categories.values()
        if isinstance(entry, dict)
        for record in entry.get("records", [])
        if isinstance(record, dict)
        and core.record_from_expanded_scope(record)
        and str(record.get("url", "")).startswith(("http://", "https://"))
    }
    all_records = [
        record
        for entry in categories.values()
        if isinstance(entry, dict)
        for record in entry.get("records", [])
        if isinstance(record, dict) and record.get("observed")
    ]
    body_urls = {
        str(record.get("url"))
        for record in all_records
        if core.record_evidence_depth(core.record_public_title(record), record)
        == "body"
    }
    trusted_body_urls = {
        str(record.get("url"))
        for record in all_records
        if str(record.get("url")) in body_urls
        and core.record_has_trusted_editor_source(record)
    }
    specialist_body_urls = {
        str(record.get("url"))
        for record in all_records
        if str(record.get("url")) in body_urls
        and core.effective_source_class(record) == "specialist_media"
    }
    frozen_registry = bundle.get("source_registry_contract")
    frozen_categories = (
        frozen_registry.get("categories", {})
        if isinstance(frozen_registry, dict)
        else {}
    )
    scoped_official_urls = {
        str(source.get("url"))
        for sources in frozen_categories.values()
        if isinstance(sources, list)
        for source in sources
        if isinstance(source, dict) and source.get("official_scope")
    }

    expected_topics = {
        (label, topic)
        for label, topics in configured.items()
        for topic in topics
    }
    cards = [card for card in issue.get("cards", []) if isinstance(card, dict)]
    facts = 0
    mapped_facts = 0
    summary_characters = 0
    one_fact_updates = 0
    cited_urls: set[str] = set()
    expanded_published_updates = 0
    multi_source_updates = 0
    specialist_source_updates = 0
    analysis_updates = 0
    for card in cards:
        detail = card.get("detail")
        basis = detail.get("summary_basis") if isinstance(detail, dict) else None
        if not isinstance(basis, dict):
            continue
        confirmed = [fact for fact in basis.get("confirmed_facts", []) if isinstance(fact, str)]
        summary = card.get("summary")
        if isinstance(summary, str):
            summary_characters += len(summary.strip())
        one_fact_updates += len(confirmed) == 1
        mappings = [mapping for mapping in basis.get("fact_sources", []) if isinstance(mapping, dict)]
        facts += len(confirmed)
        mapped = {
            str(mapping.get("fact"))
            for mapping in mappings
            if isinstance(mapping.get("source_urls"), list) and mapping.get("source_urls")
        }
        mapped_facts += sum(fact in mapped for fact in confirmed)
        card_urls = {
            str(url)
            for mapping in mappings
            for url in mapping.get("source_urls", [])
            if isinstance(url, str)
        }
        cited_urls.update(card_urls)
        expanded_published_updates += bool(card_urls & expanded_urls)
        multi_source_updates += len(card_urls) >= 2
        specialist_source_updates += bool(card_urls & specialist_body_urls)
        analysis_updates += bool(basis.get("why_it_matters"))

    checks = {
        "all_categories_collected": set(categories) == set(configured),
        "all_watch_topics_reviewed": reviewed_topics >= expected_topics,
        "evidence_contract_valid": True,
        "public_updates_present": bool(cards),
        "all_facts_cited": facts > 0 and mapped_facts == facts,
        "all_citations_observed": bool(cited_urls) and cited_urls <= observed_urls,
    }
    metrics = {
        "categories": len(categories),
        "watch_topics_expected": len(expected_topics),
        "watch_topics_reviewed": len(reviewed_topics & expected_topics),
        "source_checks": source_checks,
        "discovery_checks": discovery_checks,
        "material_candidates": material_candidates,
        "resolved_candidates": resolved_candidates,
        "unresolved_queries": unresolved_queries,
        "editor_coverage_gaps": editor_coverage_gaps,
        "editor_coverage_gap_count": len(editor_coverage_gaps),
        "unattempted_editor_coverage_gaps": unattempted_editor_coverage_gaps,
        "unattempted_editor_coverage_gap_count": len(
            unattempted_editor_coverage_gaps
        ),
        "targeted_depth_queries": targeted_depth_queries,
        "specialist_depth_resolved_candidates": (
            specialist_depth_resolved_candidates
        ),
        "depth_fallback_queries": depth_fallback_queries,
        "observed_urls": len(observed_urls),
        "unavailable_urls": len(unavailable_urls),
        "evidence_hosts": len(
            {source_health.normalized_host(url) for url in observed_urls}
        ),
        "published_updates": len(cards),
        "confirmed_facts": facts,
        "facts_with_sources": mapped_facts,
        "summary_characters": summary_characters,
        "one_fact_updates": one_fact_updates,
        "facts_per_update_milli": facts * 1000 // len(cards) if cards else 0,
        "summary_chars_per_update_milli": (
            summary_characters * 1000 // len(cards) if cards else 0
        ),
        "one_fact_update_ratio_milli": (
            one_fact_updates * 1000 // len(cards) if cards else 0
        ),
        "body_evidence_records": len(body_urls),
        "trusted_body_evidence_records": len(trusted_body_urls),
        "specialist_body_evidence_records": len(specialist_body_urls),
        "multi_source_updates": multi_source_updates,
        "specialist_source_updates": specialist_source_updates,
        "analysis_updates": analysis_updates,
        "body_backed_cited_urls": len(cited_urls & body_urls),
        "non_body_cited_urls": len(cited_urls - body_urls),
        "local_horizon_queries": local_horizon_queries,
        "local_horizon_relevant_results": local_horizon_relevant_results,
        "local_horizon_material_candidates": local_horizon_material_candidates,
        "local_horizon_resolved_candidates": local_horizon_resolved_candidates,
        "scoped_official_sources_configured": len(scoped_official_urls),
        "scoped_official_sources_observed": len(
            scoped_official_urls & observed_urls
        ),
        "expanded_evidence_records": sum(
            core.record_from_expanded_scope(record)
            for entry in categories.values()
            if isinstance(entry, dict)
            for record in entry.get("records", [])
            if isinstance(record, dict)
        ),
        "expanded_published_updates": expanded_published_updates,
        "collection_mode": bundle.get("collection_mode"),
        **review_packet_metrics(base),
    }
    source_diagnostics = source_health.post_publication_diagnostics(
        bundle, issue, issue_date
    )
    result = {
        "issue_date": issue_date,
        "evaluated_at_jst": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "source_diagnostics": source_diagnostics,
        "failures": [name for name, passed in checks.items() if not passed],
    }
    if not include_history:
        return result

    prior_dates = sorted(
        (
            path.parent.name
            for path in state_root.glob("20??-??-??/issue.json")
            if path.parent.name < issue_date
            and (path.parent / "evidence.json").exists()
        ),
        reverse=True,
    )[:3]
    history: list[dict[str, Any]] = []
    for prior_date in prior_dates:
        try:
            prior = evaluate(prior_date, state_root, include_history=False)
        except SystemExit:
            continue
        history.append(
            {
                "issue_date": prior_date,
                "passed": prior["passed"],
                "metrics": prior["metrics"],
                "source_diagnostics": prior.get("source_diagnostics", {}),
            }
        )
    previous_metrics = history[0]["metrics"] if history else {}
    deltas = metric_deltas(metrics, previous_metrics) if history else {}
    improvement_signals: list[str] = []
    if history and metrics["unavailable_urls"] > max(
        int(previous_metrics.get("unavailable_urls", 0)) + 3,
        int(previous_metrics.get("unavailable_urls", 0)) * 3 // 2,
    ):
        improvement_signals.append("source_availability_regression")
    if (
        history
        and int(previous_metrics.get("review_payload_bytes", 0)) > 0
        and metrics["review_payload_bytes"]
        > int(previous_metrics["review_payload_bytes"]) * 5 // 4
        and metrics["published_updates"]
        <= int(previous_metrics.get("published_updates", 0))
    ):
        improvement_signals.append("review_payload_efficiency_regression")
    if (
        history
        and metrics["material_candidates"] > 0
        and int(previous_metrics.get("material_candidates", 0)) > 0
        and metrics["resolved_candidates"] / metrics["material_candidates"]
        + 0.15
        < int(previous_metrics.get("resolved_candidates", 0))
        / int(previous_metrics["material_candidates"])
    ):
        improvement_signals.append("candidate_resolution_regression")
    previous_updates = int(previous_metrics.get("published_updates", 0))
    current_updates = int(metrics["published_updates"])
    if (
        history
        and current_updates >= 10
        and previous_updates >= 10
        and int(previous_metrics.get("confirmed_facts", 0)) > 0
        and int(previous_metrics.get("summary_characters", 0)) > 0
        and int(metrics["confirmed_facts"]) * previous_updates * 100
        < int(previous_metrics["confirmed_facts"]) * current_updates * 65
        and int(metrics["summary_characters"]) * previous_updates * 100
        < int(previous_metrics["summary_characters"]) * current_updates * 65
    ):
        improvement_signals.append("summary_information_retention_regression")
    if (
        history
        and current_updates >= 10
        and previous_updates >= 10
        and int(metrics["one_fact_update_ratio_milli"])
        >= int(previous_metrics.get("one_fact_update_ratio_milli", 0)) + 100
        and int(metrics["facts_per_update_milli"]) * 100
        < int(previous_metrics.get("facts_per_update_milli", 0)) * 95
    ):
        improvement_signals.append("summary_depth_regression")
    if (
        metrics["trusted_body_evidence_records"] >= max(4, current_updates // 2)
        and current_updates >= 4
        and metrics["multi_source_updates"] * 5 < current_updates
    ):
        improvement_signals.append("multi_source_synthesis_gap")
    if metrics["non_body_cited_urls"]:
        improvement_signals.append("published_fact_body_gap")
    if metrics["editor_coverage_gap_count"]:
        improvement_signals.append("unresolved_source_depth_gap")
    expansion_window = [metrics, *(value["metrics"] for value in history[:2])]
    if len(expansion_window) == 3 and all(
        int(value.get("expanded_evidence_records", 0)) > 0
        and int(value.get("expanded_published_updates", 0)) == 0
        for value in expansion_window
    ):
        improvement_signals.append("expanded_scope_needs_precision_review")
    current_causes = {
        (category_label, cause)
        for category_label, diagnostic in source_diagnostics.items()
        for cause in diagnostic.get("causes", [])
    }
    historical_cause_frequency: Counter[tuple[str, str]] = Counter()
    for historical in history:
        historical_cause_frequency.update(
            (category_label, cause)
            for category_label, diagnostic in historical.get(
                "source_diagnostics", {}
            ).items()
            for cause in diagnostic.get("causes", [])
        )
    recurring_causes = [
        {
            "category": category_label,
            "cause": cause,
            "days": historical_cause_frequency[(category_label, cause)] + 1,
        }
        for category_label, cause in sorted(current_causes)
        if historical_cause_frequency[(category_label, cause)] >= 1
    ]
    recently_resolved_causes = [
        {"category": category_label, "cause": cause, "prior_days": frequency}
        for (category_label, cause), frequency in sorted(
            historical_cause_frequency.items()
        )
        if frequency >= 2 and (category_label, cause) not in current_causes
    ]
    if recurring_causes:
        improvement_signals.append("recurring_source_depth_gap")
    result.update(
        {
            "history": history,
            "deltas_vs_previous": deltas,
            "improvement_signals": improvement_signals,
            "learning": {
                "contract_version": "2026-07-18.1",
                "history_days": 3,
                "current_causes": [
                    {"category": category_label, "cause": cause}
                    for category_label, cause in sorted(current_causes)
                ],
                "recurring_causes": recurring_causes,
                "recently_resolved_causes": recently_resolved_causes,
                "applied_or_recommended_actions": {
                    category_label: diagnostic.get("actions", [])
                    for category_label, diagnostic in source_diagnostics.items()
                    if diagnostic.get("actions")
                },
                "automatic_config_mutation": False,
                "reason": (
                    "Daily evidence may reprioritize bounded specialist searches, "
                    "but publisher registry changes remain deterministic and reviewed."
                ),
            },
            "automatic_policy": {
                "scope_auto_reduction": False,
                "quality_gate_bypass": False,
                "safe_runtime_recovery_only": True,
                "minimum_summary_length": False,
                "background_padding_allowed": False,
            },
        }
    )
    return result


def self_test() -> None:
    source_health.self_test()
    if source_health.normalized_host("https://www.openai.com/index/test") != "openai.com":
        fail("host normalization failed")
    if not core.record_from_expanded_scope({"official_scope": "mexico"}):
        fail("expanded official source was not recognized")
    if not core.record_from_expanded_scope(
        {"discovery_query_ids": ["horizon:local-language:es-MX:identity-1"]}
    ):
        fail("expanded local horizon was not recognized")
    if metric_deltas({"source_checks": 12}, {"source_checks": 10})[
        "source_checks"
    ] != 2:
        fail("history delta calculation failed")
    if not {
        "Business Network",
        "ITmedia Mobile",
        "K-tai Watch",
    } <= {
        str(publisher.get("label"))
        for publisher in core.discovery_publishers_for_topic(
            "SoftBank", "domestic_services"
        )
    }:
        fail("source-depth diagnostics lost topic-specific publisher routing")
    print("NIGHT SIGNAL EVAL SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    report = evaluate(args.issue_date, args.state_root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        fail(", ".join(report["failures"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
