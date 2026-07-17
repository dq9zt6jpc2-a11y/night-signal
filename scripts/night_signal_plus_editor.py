#!/usr/bin/env python3
"""Prepare and import a zero-additional-charge ChatGPT Plus editorial review.

Collection and candidate filtering stay deterministic.  The resulting compact
packet is reviewed once by the repository's Web Scheduled task, then this module
re-applies the same source, novelty, and public-copy validators used by the
former hosted-model editor.  No API or GitHub Models request is made here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import night_signal_core as core
import night_signal_editor as editor
import night_signal_evidence as evidence_store
import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
PACKET_CONTRACT = "codex-plus-editor-v1"
COLLECTION_MODE = "web_evidence_plus_review"


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL PLUS REVIEW FAILED: {message}", file=__import__("sys").stderr)
    raise SystemExit(1)


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_json_compact_atomic(path: Path, value: dict[str, Any]) -> None:
    """Keep the lossless review packet small without shortening Evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"JSON root must be an object: {path}")
    return value


def request_id(category_label: str, chunk_index: int, payload: dict[str, Any]) -> str:
    # Policy guidance may evolve without changing the Evidence/event identity.
    # Excluding it preserves completed reviews across importer-only upgrades and
    # avoids repeating model work.
    identity_payload = {
        key: value
        for key, value in payload.items()
        if key != "allowed_topic_value_classes"
    }
    digest = hashlib.sha256(
        json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]
    section = str(editor.category_config().get(category_label, {}).get("section_id", "review"))
    return f"{section}-{chunk_index:02d}-{digest}"


def review_requests(
    issue_date: str,
    evidence: dict[str, Any],
    state_root: Path,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    categories = evidence.get("categories")
    if not isinstance(categories, dict):
        fail("Evidence categories must be an object")
    for category in core.category_contracts():
        label = str(category["label"])
        entry = categories.get(label)
        if not isinstance(entry, dict) or not isinstance(entry.get("records"), list):
            fail(f"Evidence records are missing: {label}")
        records = [record for record in entry["records"] if isinstance(record, dict)]
        previous_updates = editor.previous_category_updates(
            state_root,
            issue_date,
            label,
        )
        event_groups = editor.publication_candidate_groups(
            category,
            issue_date,
            records,
            previous_updates=previous_updates,
        )
        chunks = editor.publication_record_chunks(
            category,
            issue_date,
            records,
            event_groups=event_groups,
            previous_updates=previous_updates,
        )
        for chunk_index, chunk_records in enumerate(chunks, start=1):
            payload = editor.fit_model_payload(
                core.category_prompt(category, issue_date, chunk_records)
            )
            requests.append(
                {
                    "request_id": request_id(label, chunk_index, payload),
                    "category": label,
                    "quality_route": editor.quality_model_required(payload),
                    "payload": payload,
                    "_records": chunk_records,
                    "_category_contract": category,
                }
            )
    return requests


def public_request(request: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in request.items()
        if not key.startswith("_")
    }


def prepare_packet(
    issue_date: str,
    *,
    evidence_path: Path,
    state_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    evidence = read_json(evidence_path)
    if evidence.get("collection_mode") not in {
        COLLECTION_MODE,
        "github_models_unattended",
    }:
        fail(f"unsupported Evidence collection mode: {evidence.get('collection_mode')}")
    try:
        report = evidence_store.validate_bundle(evidence, issue_date)
    except evidence_store.EvidenceContractError as exc:
        fail(str(exc))
    gaps = core.remaining_editor_coverage_gaps(evidence, report)
    if gaps:
        fail(
            "Evidence has material watch topics without resolved source content: "
            + ", ".join(gaps)
        )
    requests = review_requests(issue_date, evidence, state_root)
    evidence_hash = evidence_store.bundle_sha256(evidence_path)
    packet = {
        "contract": PACKET_CONTRACT,
        "issue_date": issue_date,
        "evidence_sha256": evidence_hash,
        "editor_contract_sha256": state.editor_contract_sha256(),
        "policy": {
            "no_publication_quota": True,
            "review_every_event": True,
            "previous_updates_are_novelty_only": True,
            "source_publication_date_is_not_an_event_delta": True,
            "novelty_context_must_support_why_today": True,
            "natural_japanese_required": True,
            "every_summary_point_requires_evidence_ids": True,
            "every_published_item_requires_information_complete": True,
            "allowed_topic_value_classes": sorted(core.ALLOWED_TOPIC_VALUES),
            "one_point_only_for_one_distinct_supported_delta": True,
            "no_background_or_repetition_for_length": True,
            "earnings_results_and_material_market_moves_are_not_routine": True,
            "headline_only_requires_insufficient_evidence": True,
        },
        "requests": [public_request(request) for request in requests],
        "metrics": {
            "categories": len(core.category_contracts()),
            "requests": len(requests),
            "candidate_events": sum(
                len(request["payload"].get("events", [])) for request in requests
            ),
            "candidate_payload_bytes": sum(
                len(
                    json.dumps(
                        request["payload"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                for request in requests
            ),
            "source_checks": report["source_checks"],
            "discovery_checks": report["discovery_checks"],
            "publisher_portfolio_version": evidence.get(
                "publisher_portfolio_contract", {}
            ).get("portfolio_version"),
            "depth_recovery_queries": sum(
                1
                for entry in evidence.get("categories", {}).values()
                if isinstance(entry, dict)
                for check in entry.get("discovery_checks", [])
                if isinstance(check, dict)
                and str(check.get("query_id", "")).startswith("depth:")
            ),
            "depth_recovery_resolved_candidates": sum(
                int(check.get("resolved_candidate_count", 0))
                for entry in evidence.get("categories", {}).values()
                if isinstance(entry, dict)
                for check in entry.get("discovery_checks", [])
                if isinstance(check, dict)
                and str(check.get("query_id", "")).startswith("depth:")
            ),
            "observed_urls": len(report["observed_urls"]),
        },
    }
    write_json_compact_atomic(output_path, packet)
    return {
        "issue_date": issue_date,
        "packet": str(output_path),
        **packet["metrics"],
        "model_requests": 0,
        "additional_paid_api_requests": 0,
    }


def cards_from_response(
    raw: dict[str, Any],
    request: dict[str, Any],
    issue_date: str,
) -> list[dict[str, Any]]:
    category = request["_category_contract"]
    records = request["_records"]
    flattened, response_accepted, response_feedback = editor.flatten_event_response(
        raw,
        category,
        issue_date,
        records,
    )
    flattened = editor.sanitize_model_result(flattened)
    normalized = core.normalize_result(flattened, category, issue_date, records)
    failures: list[str] = []
    cards: list[dict[str, Any]] = []
    for item in normalized["items"]:
        try:
            card = editor.item_card(
                str(category["label"]),
                str(
                    editor.category_config()[str(category["label"])][
                        "section_id"
                    ]
                ),
                item,
                issue_date,
            )
            card["_review_event_id"] = (
                f"{request['request_id']}:{item.get('event_id', '')}"
            )
            cards.append(card)
        except editor.UnpublishableItem as exc:
            failures.append(str(exc))
    if (
        not response_accepted
        or not normalized["coverage_complete"]
        or normalized["rejected_items"]
        or failures
    ):
        fail(
            "review response failed deterministic validation for "
            f"{request['request_id']}: "
            + json.dumps(
                {
                    "event_response": response_feedback,
                    "missing_event_ids": normalized["missing_event_ids"],
                    "conflicting_event_ids": normalized["conflicting_event_ids"],
                    "rejected_items": normalized["rejected_items"],
                    "unpublishable_items": failures,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return cards


def merge_within_event_boundaries(
    cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge repeated wording only inside one deterministic event boundary."""
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for index, card in enumerate(cards):
        event_id = str(card.get("_review_event_id") or f"unbound-{index}")
        if event_id not in groups:
            groups[event_id] = []
            order.append(event_id)
        groups[event_id].append(card)
    merged: list[dict[str, Any]] = []
    for event_id in order:
        for card in editor.merge_repeated_cards(groups[event_id]):
            card.pop("_review_event_id", None)
            merged.append(card)
    return merged


def category_review_audit(
    evidence: dict[str, Any],
    requests: list[dict[str, Any]],
    response_by_id: dict[str, dict[str, Any]],
    cards_by_category: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Explain every low-count category without imposing a publication quota."""
    evidence_categories = evidence.get("categories", {})
    audits: list[dict[str, Any]] = []
    for category in core.category_contracts():
        label = str(category["label"])
        category_requests = [
            request for request in requests if str(request.get("category")) == label
        ]
        decisions: dict[str, int] = {}
        body_events = 0
        headline_only_events = 0
        candidate_events = 0
        for request in category_requests:
            for event in request.get("payload", {}).get("events", []):
                if not isinstance(event, dict):
                    continue
                candidate_events += 1
                depths = {
                    str(item.get("evidence_depth", ""))
                    for item in event.get("evidence", [])
                    if isinstance(item, dict)
                }
                if "body" in depths:
                    body_events += 1
                elif "headline" in depths:
                    headline_only_events += 1
            response = response_by_id.get(str(request.get("request_id")), {})
            for event in response.get("events", []):
                if not isinstance(event, dict):
                    continue
                decision = str(event.get("decision", ""))
                decisions[decision] = decisions.get(decision, 0) + 1
        entry = (
            evidence_categories.get(label, {})
            if isinstance(evidence_categories, dict)
            else {}
        )
        source_checks = entry.get("source_checks", []) if isinstance(entry, dict) else []
        discovery_checks = (
            entry.get("discovery_checks", []) if isinstance(entry, dict) else []
        )
        unavailable_sources = sum(
            isinstance(check, dict)
            and check.get("slot_state") == "source_unavailable"
            for check in source_checks
        )
        resolved_searches = sum(
            isinstance(check, dict)
            and int(check.get("resolved_candidate_count", 0)) > 0
            for check in discovery_checks
        )
        unresolved_searches = sum(
            isinstance(check, dict)
            and check.get("slot_state") == "searched_unresolved"
            for check in discovery_checks
        )
        depth_queries = sum(
            isinstance(check, dict)
            and str(check.get("query_id", "")).startswith("depth:")
            for check in discovery_checks
        )
        depth_resolved = sum(
            int(check.get("resolved_candidate_count", 0))
            for check in discovery_checks
            if isinstance(check, dict)
            and str(check.get("query_id", "")).startswith("depth:")
        )
        final_cards = len(cards_by_category.get(label, []))
        low_count = final_cards <= 1
        needs_follow_up = bool(
            low_count
            and (
                decisions.get("insufficient_evidence", 0)
                or unresolved_searches
                or resolved_searches == 0
                or (
                    source_checks
                    and unavailable_sources * 3 >= len(source_checks)
                )
            )
        )
        audits.append(
            {
                "category": label,
                "candidate_events": candidate_events,
                "body_events": body_events,
                "headline_only_events": headline_only_events,
                "decisions": decisions,
                "final_cards": final_cards,
                "source_checks": len(source_checks),
                "unavailable_sources": unavailable_sources,
                "resolved_searches": resolved_searches,
                "unresolved_searches": unresolved_searches,
                "depth_recovery_queries": depth_queries,
                "depth_recovery_resolved_candidates": depth_resolved,
                "low_count_status": (
                    "limited_evidence"
                    if needs_follow_up
                    else "supported"
                    if low_count
                    else "not_low_count"
                ),
                "needs_follow_up": needs_follow_up,
            }
        )
    return audits


def apply_review(
    issue_date: str,
    *,
    evidence_path: Path,
    review_path: Path,
    state_root: Path,
) -> dict[str, Any]:
    evidence = read_json(evidence_path)
    try:
        evidence_store.validate_bundle(evidence, issue_date)
    except evidence_store.EvidenceContractError as exc:
        fail(str(exc))
    evidence_hash = evidence_store.bundle_sha256(evidence_path)
    review = read_json(review_path)
    if review.get("contract") != PACKET_CONTRACT:
        fail(f"review contract must be {PACKET_CONTRACT}")
    if review.get("issue_date") != issue_date:
        fail("review issue date does not match")
    if review.get("evidence_sha256") != evidence_hash:
        fail("review was generated from different Evidence")
    responses = review.get("responses")
    if not isinstance(responses, list):
        fail("review responses must be an array")
    response_by_id: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for entry in responses:
        if not isinstance(entry, dict):
            fail("each review response must be an object")
        identifier = str(entry.get("request_id", ""))
        response = entry.get("response")
        if identifier in response_by_id:
            duplicates.add(identifier)
        if not identifier or not isinstance(response, dict):
            fail("each review response needs request_id and response")
        response_by_id[identifier] = response
    if duplicates:
        fail("duplicate review request ids: " + ", ".join(sorted(duplicates)))
    requests = review_requests(issue_date, evidence, state_root)
    expected_ids = {str(request["request_id"]) for request in requests}
    supplied_ids = set(response_by_id)
    if expected_ids != supplied_ids:
        fail(
            "review must account for every request exactly once: "
            + json.dumps(
                {
                    "missing_request_ids": sorted(expected_ids - supplied_ids),
                    "unknown_request_ids": sorted(supplied_ids - expected_ids),
                },
                ensure_ascii=False,
            )
        )
    cards_by_category: dict[str, list[dict[str, Any]]] = {}
    for request in requests:
        cards_by_category.setdefault(str(request["category"]), []).extend(
            cards_from_response(
                response_by_id[str(request["request_id"])],
                request,
                issue_date,
            )
        )
    cards = [
        card
        for category_label in editor.category_config()
        for card in merge_within_event_boundaries(
            cards_by_category.get(category_label, [])
        )
    ]
    if not cards:
        fail("review produced no evidence-backed important update")
    category_audit = category_review_audit(
        evidence,
        requests,
        response_by_id,
        cards_by_category,
    )
    manifest = state.build_coverage_manifest(
        issue_date,
        collection_mode=str(evidence.get("collection_mode")),
        collection_completed_at_jst=str(evidence.get("checked_at_jst")),
        evidence_sha256=evidence_hash,
    )
    issue = {
        "issue_date": issue_date,
        "cards": cards,
        "coverage_manifest": manifest,
    }
    issue_path = state_root / issue_date / "issue.json"
    state.validate_issue_state(issue, issue_path, evidence)
    write_json_atomic(issue_path, issue)
    receipt = {
        "contract": PACKET_CONTRACT,
        "issue_date": issue_date,
        "evidence_sha256": evidence_hash,
        "requests": len(requests),
        "candidate_events": sum(
            len(request["payload"].get("events", [])) for request in requests
        ),
        "published_cards": len(cards),
        "excluded_events": sum(
            1
            for response in response_by_id.values()
            for event in response.get("events", [])
            if isinstance(event, dict) and event.get("decision") != "publish"
        ),
        "model_requests_from_repository": 0,
        "additional_paid_api_requests": 0,
        "category_audit": category_audit,
        "low_count_categories_needing_follow_up": [
            audit["category"]
            for audit in category_audit
            if audit["needs_follow_up"]
        ],
    }
    write_json_atomic(state_root / issue_date / "plus_review_receipt.json", receipt)
    return {**receipt, "issue_state": str(issue_path)}


def self_test() -> None:
    payload = {
        "category": "OpenAI",
        "events": [{"id": "g001", "previous_updates": [], "evidence": []}],
    }
    first = request_id("OpenAI", 1, payload)
    if first != request_id("OpenAI", 1, json.loads(json.dumps(payload))):
        fail("review request id is not deterministic")
    if first != request_id(
        "OpenAI",
        1,
        {
            **payload,
            "allowed_topic_value_classes": sorted(core.ALLOWED_TOPIC_VALUES),
        },
    ):
        fail("policy-only guidance changed an existing request identity")
    if first == request_id("OpenAI", 2, payload):
        fail("review request id did not bind its chunk position")
    repeated = {
        "category": "OpenAI",
        "title": "OpenAIが新機能を公開",
        "detail": {"sources": [], "summary_basis": {"confirmed_facts": []}},
    }
    bounded = merge_within_event_boundaries(
        [
            {**repeated, "_review_event_id": "request:g001"},
            {**repeated, "_review_event_id": "request:g002"},
        ]
    )
    if len(bounded) != 2:
        fail("Plus review merged cards across event boundaries")
    headline_category = {
        "label": "OpenAI",
        "watch_topics": [
            {
                "id": "product_release",
                "terms": ["OpenAI", "GPT", "release"],
                "event_classes": ["technical_or_product_shift"],
            }
        ],
    }
    headline_record = {
        "label": "Example Technology News",
        "url": "https://example.com/openai-new-model",
        "source_role": "independent_media_or_data",
        "channel": "web",
        "source_class": "discovered_media",
        "observed": True,
        "published_date": "2099-01-02",
        "title": "OpenAI releases GPT-9 with a new reasoning mode",
        "excerpt": (
            "OpenAI releases GPT-9 with a new reasoning mode "
            "Example Technology News"
        ),
        "watch_topic_ids": ["product_release"],
        "_editor_event_id": "g001",
    }
    _, accepted_no_material, no_material_feedback = editor.flatten_event_response(
        {
            "events": [
                {
                    "event_id": "g001",
                    "decision": "no_material_update",
                    "items": [],
                }
            ]
        },
        headline_category,
        "2099-01-02",
        [headline_record],
    )
    if accepted_no_material or no_material_feedback["invalid_event_decisions"].get(
        "g001"
    ) != "headline_only_requires_insufficient_evidence":
        fail("Plus review allowed a headline-only event to be silently discarded")
    _, accepted_insufficient, _ = editor.flatten_event_response(
        {
            "events": [
                {
                    "event_id": "g001",
                    "decision": "insufficient_evidence",
                    "items": [],
                }
            ]
        },
        headline_category,
        "2099-01-02",
        [headline_record],
    )
    if not accepted_insufficient:
        fail("Plus review rejected an honest headline-only evidence hold")
    with tempfile.TemporaryDirectory() as temporary_directory:
        path = Path(temporary_directory) / "value.json"
        write_json_atomic(path, {"日本語": "根拠"})
        if read_json(path) != {"日本語": "根拠"}:
            fail("review JSON round trip failed")
    source = Path(__file__).read_text(encoding="utf-8")
    if "models." + "github.ai" in source:
        fail("Plus review module must never call GitHub Models")
    if "api." + "openai.com" in source:
        fail("Plus review module must never call a paid OpenAI API")
    print("NIGHT SIGNAL PLUS REVIEW SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--apply-review", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    evidence_path = args.evidence or args.state_root / args.issue_date / "evidence.json"
    if args.prepare == bool(args.apply_review):
        fail("choose exactly one of --prepare or --apply-review")
    if args.prepare:
        output = args.output or args.state_root / args.issue_date / "editor_packet.json"
        result = prepare_packet(
            args.issue_date,
            evidence_path=evidence_path,
            state_root=args.state_root,
            output_path=output,
        )
    else:
        result = apply_review(
            args.issue_date,
            evidence_path=evidence_path,
            review_path=args.apply_review,
            state_root=args.state_root,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
