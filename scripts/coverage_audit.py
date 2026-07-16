#!/usr/bin/env python3
"""Validate broad Evidence coverage and its direct projection into an Issue."""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import night_signal_state as state
import night_signal_evidence as evidence_store
import night_signal_core as core


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "night_signal_coverage.json"
STATE_ROOT = ROOT / "state"
SITE_ROOT = ROOT / "site"


def fail(message: str) -> None:
    print(f"COVERAGE AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail(f"cannot load {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {exc}")
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def load_contract() -> dict[str, Any]:
    return load_object(CONFIG_PATH)


def max_adopted_source_age_days(contract: dict[str, Any]) -> int:
    return int(contract.get("maximum_adopted_candidate_source_age_days", 3))


def visible_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def validate(issue_date: str) -> dict[str, int]:
    try:
        datetime.strptime(issue_date, "%Y-%m-%d")
    except ValueError:
        fail(f"invalid issue date: {issue_date}")
    base = STATE_ROOT / issue_date
    issue_path = base / "issue.json"
    issue = load_object(issue_path)
    bundle = load_object(base / "evidence.json")
    state.validate_issue_state(issue, issue_path)
    contract = load_contract()
    try:
        evidence_report = evidence_store.validate_bundle(bundle, issue_date)
    except evidence_store.EvidenceContractError as exc:
        fail(str(exc))
    editor_coverage_gaps = core.remaining_editor_coverage_gaps(
        bundle,
        evidence_report,
    )
    if editor_coverage_gaps:
        fail(
            "material watch topics lack resolved source content: "
            + ", ".join(editor_coverage_gaps)
        )
    configured = {
        str(category["label"]): category
        for category in contract.get("categories", [])
        if isinstance(category, dict)
    }
    cards = [card for card in issue.get("cards", []) if isinstance(card, dict)]

    dated_index = SITE_ROOT / issue_date / "index.html"
    root_index = SITE_ROOT / "index.html"
    if dated_index.exists() and root_index.exists():
        dated_text = visible_text(dated_index.read_text(encoding="utf-8"))
        root_text = visible_text(root_index.read_text(encoding="utf-8"))
        for label, config in configured.items():
            if label not in dated_text or str(config.get("section_id")) not in dated_index.read_text(
                encoding="utf-8"
            ):
                fail(f"dated page is missing category section: {label}")
        for card in cards:
            title = str(card.get("title"))
            if title not in dated_text or title not in root_text:
                fail(f"public pages are missing current update: {title}")

    return {
        "categories": len(configured),
        "cards": len(cards),
        "source_checks": evidence_report["source_checks"],
        "discovery_checks": evidence_report["discovery_checks"],
        "observed_urls": len(evidence_report["observed_urls"]),
    }


def self_test() -> None:
    issue_date = "2099-01-02"
    source_url = "https://example.com/news"
    coverage = {
        "required_watch_topic_channels": ["web"],
        "categories": [
            {
                "label": "Test",
                "identity_terms": ["Test"],
                "required_watch_topic_channels": ["web"],
                "watch_topics": [{"id": "topic-one"}],
            }
        ],
    }
    entry = {
        "records": [{"url": source_url, "observed": True}],
        "source_checks": [
            {
                "watch_topic_ids": [],
                "channel": "web",
                "url": source_url,
                "slot_state": "observed_live",
                "checked_at_jst": f"{issue_date}T17:00:00+09:00",
                "evidence_summary": "source reached",
                "verification_method": "direct_fetch",
            }
        ],
        "discovery_checks": [
            {
                "purpose": "watch_topic",
                "channel": "web",
                "watch_topic_ids": ["topic-one"],
                "query": "Test update when:3d",
                "url": "https://example.com/search/topic",
                "slot_state": "searched_unresolved",
                "result_count": 2,
                "relevant_result_count": 1,
                "material_candidate_count": 1,
                "resolved_candidate_count": 0,
                "checked_at_jst": f"{issue_date}T17:00:00+09:00",
                "evidence_summary": "topic searched",
            },
            {
                "purpose": "horizon",
                "channel": "web",
                "watch_topic_ids": [],
                "query": "Test adjacent change when:3d",
                "url": "https://example.com/search/horizon",
                "slot_state": "searched_no_results",
                "result_count": 0,
                "relevant_result_count": 0,
                "material_candidate_count": 0,
                "resolved_candidate_count": 0,
                "checked_at_jst": f"{issue_date}T17:00:00+09:00",
                "evidence_summary": "horizon searched",
            },
        ],
    }
    bundle = {
        "issue_date": issue_date,
        "checked_at_jst": f"{issue_date}T17:00:00+09:00",
        "categories": {"Test": entry},
    }
    registry = {"categories": {"Test": [{"url": source_url}]}}
    report = evidence_store.validate_bundle(
        bundle,
        issue_date,
        coverage=coverage,
        registry=registry,
    )
    if (
        report["source_checks"] != 1
        or report["discovery_checks"] != 2
        or len(report["observed_urls"]) != 1
    ):
        fail(f"unexpected self-test metrics: {report}")
    if report["editor_coverage_gaps"] != ["Test/topic-one"]:
        fail("unresolved material watch topic was not exposed as a coverage gap")
    resolved = json.loads(json.dumps(bundle))
    resolved["categories"]["Test"]["discovery_checks"][0][
        "resolved_candidate_count"
    ] = 1
    resolved_report = evidence_store.validate_bundle(
        resolved,
        issue_date,
        coverage=coverage,
        registry=registry,
    )
    if resolved_report["editor_coverage_gaps"]:
        fail("resolved material watch topic remained a coverage gap")
    invalid = json.loads(json.dumps(bundle))
    invalid["categories"]["Test"]["discovery_checks"][0]["watch_topic_ids"] = []
    try:
        evidence_store.validate_bundle(
            invalid,
            issue_date,
            coverage=coverage,
            registry=registry,
        )
    except evidence_store.EvidenceContractError:
        pass
    else:
        fail("canonical Evidence validation accepted an unchecked watch topic")
    scoped_registry = {
        "version": "2099-01-01.1",
        "categories": {
            "Test": [
                {
                    "url": source_url,
                    "source_role": "primary_or_official",
                    "official_scope": "test_scope",
                }
            ]
        },
    }
    scoped_coverage = json.loads(json.dumps(coverage))
    scoped_coverage["categories"][0]["required_official_scopes"] = ["test_scope"]
    scoped_coverage["categories"][0]["required_local_horizon_locales"] = ["ja-JP"]
    evidence_store.validate_source_configuration(scoped_coverage, scoped_registry)
    missing_scope_registry = json.loads(json.dumps(scoped_registry))
    missing_scope_registry["categories"]["Test"][0].pop("official_scope")
    try:
        evidence_store.validate_source_configuration(
            scoped_coverage,
            missing_scope_registry,
        )
    except evidence_store.EvidenceContractError:
        pass
    else:
        fail("source preflight accepted a missing required official scope")
    frozen = json.loads(json.dumps(bundle))
    frozen["collector_contract_version"] = evidence_store.collector_contract_version()
    frozen["source_registry_contract"] = evidence_store.source_registry_contract(
        scoped_registry
    )
    frozen["categories"]["Test"]["discovery_checks"][1]["locale"] = {
        "id": "ja-JP"
    }
    expanded_registry = json.loads(json.dumps(scoped_registry))
    expanded_registry["categories"]["Test"].append(
        {
            "url": "https://example.com/new-source",
            "source_role": "primary_or_official",
            "official_scope": "test_scope",
        }
    )
    evidence_store.validate_bundle(
        frozen,
        issue_date,
        coverage=scoped_coverage,
        registry=expanded_registry,
    )
    missing_snapshot = json.loads(json.dumps(frozen))
    missing_snapshot.pop("source_registry_contract")
    try:
        evidence_store.validate_bundle(
            missing_snapshot,
            issue_date,
            coverage=scoped_coverage,
            registry=scoped_registry,
        )
    except evidence_store.EvidenceContractError:
        pass
    else:
        fail("current Evidence validation accepted a missing source registry contract")
    tampered_snapshot = json.loads(json.dumps(frozen))
    tampered_snapshot["source_registry_contract"]["categories"]["Test"][0][
        "url"
    ] = "https://example.com/tampered"
    try:
        evidence_store.validate_bundle(
            tampered_snapshot,
            issue_date,
            coverage=scoped_coverage,
            registry=scoped_registry,
        )
    except evidence_store.EvidenceContractError:
        pass
    else:
        fail("Evidence validation accepted a tampered source registry contract")
    expanded_snapshot = json.loads(json.dumps(frozen))
    expanded_snapshot["source_registry_contract"] = evidence_store.source_registry_contract(
        expanded_registry
    )
    try:
        evidence_store.validate_bundle(
            expanded_snapshot,
            issue_date,
            coverage=scoped_coverage,
            registry=expanded_registry,
        )
    except evidence_store.EvidenceContractError:
        pass
    else:
        fail("Evidence validation accepted an unchecked newly configured seed source")
    print("COVERAGE AUDIT SELF-TEST PASSED")


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        self_test()
        return 0
    issue_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().date().isoformat()
    result = validate(issue_date)
    print(
        f"COVERAGE AUDIT PASSED: {issue_date}, categories={result['categories']}, "
        f"cards={result['cards']}, source_checks={result['source_checks']}, "
        f"discovery_checks={result['discovery_checks']}, "
        f"observed_urls={result['observed_urls']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
