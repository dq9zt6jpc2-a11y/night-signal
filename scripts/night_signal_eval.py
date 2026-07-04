#!/usr/bin/env python3
"""Evaluate Evidence coverage and published fact provenance without persisting logs."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import night_signal_state as state
import night_signal_evidence as evidence_store


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL EVAL FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def normalized_host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail(f"cannot load {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def evaluate(issue_date: str, state_root: Path) -> dict[str, Any]:
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
    observed_urls = set(evidence_report["observed_urls"])
    unavailable_urls: set[str] = set()
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

    expected_topics = {
        (label, topic)
        for label, topics in configured.items()
        for topic in topics
    }
    cards = [card for card in issue.get("cards", []) if isinstance(card, dict)]
    facts = 0
    mapped_facts = 0
    cited_urls: set[str] = set()
    for card in cards:
        detail = card.get("detail")
        basis = detail.get("summary_basis") if isinstance(detail, dict) else None
        if not isinstance(basis, dict):
            continue
        confirmed = [fact for fact in basis.get("confirmed_facts", []) if isinstance(fact, str)]
        mappings = [mapping for mapping in basis.get("fact_sources", []) if isinstance(mapping, dict)]
        facts += len(confirmed)
        mapped = {
            str(mapping.get("fact"))
            for mapping in mappings
            if isinstance(mapping.get("source_urls"), list) and mapping.get("source_urls")
        }
        mapped_facts += sum(fact in mapped for fact in confirmed)
        cited_urls.update(
            str(url)
            for mapping in mappings
            for url in mapping.get("source_urls", [])
            if isinstance(url, str)
        )

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
        "observed_urls": len(observed_urls),
        "unavailable_urls": len(unavailable_urls),
        "evidence_hosts": len({normalized_host(url) for url in observed_urls}),
        "published_updates": len(cards),
        "confirmed_facts": facts,
        "facts_with_sources": mapped_facts,
        "collection_mode": bundle.get("collection_mode"),
    }
    return {
        "issue_date": issue_date,
        "evaluated_at_jst": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "failures": [name for name, passed in checks.items() if not passed],
    }


def self_test() -> None:
    if normalized_host("https://www.openai.com/index/test") != "openai.com":
        fail("host normalization failed")
    print("NIGHT SIGNAL EVAL SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    report = evaluate(args.issue_date, args.state_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        fail(", ".join(report["failures"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
