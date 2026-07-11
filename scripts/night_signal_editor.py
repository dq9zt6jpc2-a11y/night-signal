#!/usr/bin/env python3
"""Edit collected Evidence into the canonical NIGHT SIGNAL Issue."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import night_signal_models as models
import night_signal_evidence as evidence_store
import night_signal_state as state
import night_signal_core as core


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
TOPIC_VALUE_CLASS_MAP = {
    "capital_market_shift": "market_or_financial_impact",
    "competitive_result": "event_result_or_outcome",
    "macro_policy_data": "market_or_financial_impact",
    "roster_change": "operational_status_change",
}
SUMMARY_LABEL_RE = re.compile(r"(?:変更点|重要性|確認事実|未確定点)\s*[:：]")
EVENT_BOUNDARY_REJECTION_REASONS = {
    "missing_event_id",
    "unknown_event_id",
    "event_evidence_mismatch",
    "mixed_event_boundary",
}


class UnpublishableItem(RuntimeError):
    """A single evidence item cannot support reader-facing copy."""


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL RESEARCH IMPORT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def topic_value_class(value: Any) -> str:
    normalized = str(value)
    return TOPIC_VALUE_CLASS_MAP.get(normalized, normalized)


def compact_text(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value).split())[:limit]


def public_card_title(item: dict[str, Any]) -> str:
    return compact_text(item.get("title", ""), 180)


def summary_is_reader_facing(title: str, summary: str) -> bool:
    if state.public_render_copy_violations(summary, kind="summary"):
        return False
    if state.GENERIC_CONTEXT_RE.search(summary):
        return False
    return not state.reader_summary_violations(title, summary)


def public_card_summary(item: dict[str, Any], title: str) -> str:
    facts = state.normalize_material_facts(
        title,
        item.get("confirmed_facts", []),
    )
    summary = compact_text(item.get("summary", ""), 2600)
    if (
        summary_is_reader_facing(title, summary)
        and state.summary_covers_material_facts(f"{title}。 {summary}", facts)
    ):
        return summary
    raise UnpublishableItem(f"model summary violates the canonical content contract: {title}")


def public_item_copy(item: dict[str, Any]) -> tuple[str, str]:
    title = public_card_title(item)
    summary = public_card_summary(item, title)
    return title, summary


def quality_model_required(category_payload: dict[str, Any]) -> bool:
    evidence = [
        item
        for event in category_payload.get("events", [])
        if isinstance(event, dict)
        for item in event.get("evidence", [])
        if isinstance(item, dict)
    ]
    for item in evidence:
        title = str(item.get("title", ""))
        body = str(item.get("body", ""))
        if (
            state.analysis_headline(title)
            or bool(re.search(r"(?:\|\s*-{3,}\s*\||表\s*[:：]|グラフ|チャート|図\s*[:：]|chart|table|graph)", body, re.I))
            or len(re.findall(r"\d+(?:\.\d+)?", body)) >= 18
        ):
            return True
    return False


def has_non_boundary_rejection(items: Any) -> bool:
    return any(
        set(item.get("reasons", [])) - EVENT_BOUNDARY_REJECTION_REASONS
        for item in items or []
        if isinstance(item, dict)
    )


def sanitize_editor_title(value: Any) -> str:
    title = core.reader_facing_text(value, 180)
    for character in state.TITLE_FORBIDDEN_CHARS:
        title = title.replace(character, " ")
    for phrase in state.VAGUE_TITLE_PHRASES:
        title = re.sub(
            rf"(?:と|、|・)\s*[^、。]{{0,24}}{re.escape(phrase)}\s*$",
            "",
            title,
        )
        title = title.replace(phrase, "")
    return compact_text(title.strip(" 、・"), 180)


def sanitize_model_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Merge repeated model points without changing their supported wording."""
    sanitized = {**raw, "items": []}
    for raw_item in raw.get("items", []):
        if not isinstance(raw_item, dict):
            sanitized["items"].append(raw_item)
            continue
        points: list[dict[str, Any]] = []
        for raw_point in raw_item.get("summary_points", []):
            if not isinstance(raw_point, dict):
                points.append(raw_point)
                continue
            text = compact_text(raw_point.get("text", ""), 500)
            evidence_ids = list(
                dict.fromkeys(
                    value
                    for value in raw_point.get("evidence_ids", [])
                    if isinstance(value, str) and value
                )
            )
            duplicate = next(
                (
                    point
                    for point in points
                    if isinstance(point, dict)
                    and state.materially_same_fact(
                        str(point.get("text", "")),
                        text,
                    )
                ),
                None,
            )
            if duplicate is None:
                points.append(
                    {
                        "text": text,
                        "evidence_ids": evidence_ids,
                    }
                )
            else:
                duplicate["evidence_ids"] = list(
                    dict.fromkeys([*duplicate.get("evidence_ids", []), *evidence_ids])
                )
        sanitized["items"].append(
            {
                **raw_item,
                "title": sanitize_editor_title(raw_item.get("title", "")),
                "summary_points": points,
            }
        )
    return sanitized


def flatten_event_response(
    raw: dict[str, Any],
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool, dict[str, Any]]:
    evidence_entries = core.editor_evidence_records(category, issue_date, records)
    event_evidence_ids: dict[str, set[str]] = {}
    for evidence_id, record in evidence_entries:
        event_id = str(record.get("_editor_event_id") or evidence_id)
        event_evidence_ids.setdefault(event_id, set()).add(evidence_id)
    expected_event_ids = set(event_evidence_ids)
    seen_event_ids: list[str] = []
    unknown_event_ids: set[str] = set()
    cross_event_evidence_ids: set[str] = set()
    invalid_event_decisions: dict[str, str] = {}
    malformed_event_results = 0
    flattened = {"items": [], "excluded_events": []}
    for event_result in raw.get("events", []):
        if not isinstance(event_result, dict):
            malformed_event_results += 1
            continue
        event_id = str(event_result.get("event_id", ""))
        if event_id not in expected_event_ids:
            unknown_event_ids.add(event_id)
            continue
        seen_event_ids.append(event_id)
        allowed_ids = event_evidence_ids[event_id]
        decision = str(event_result.get("decision", ""))
        event_items = event_result.get("items", [])
        if not isinstance(event_items, list):
            malformed_event_results += 1
            continue
        if decision not in models.EVENT_DECISIONS:
            invalid_event_decisions[event_id] = "unknown_decision"
        elif decision == "publish" and not event_items:
            invalid_event_decisions[event_id] = "publish_without_items"
        elif decision != "publish" and event_items:
            invalid_event_decisions[event_id] = "excluded_event_with_items"
        elif decision != "publish":
            flattened["excluded_events"].append(
                {"event_id": event_id, "reason": decision}
            )
        for item in event_items:
            if not isinstance(item, dict):
                malformed_event_results += 1
                continue
            flattened["items"].append({**item, "event_id": event_id})
            cited_ids = {
                str(evidence_id)
                for point in item.get("summary_points", [])
                if isinstance(point, dict)
                for evidence_id in point.get("evidence_ids", [])
                if isinstance(evidence_id, str)
            }
            cross_event_evidence_ids.update(cited_ids - allowed_ids)
    duplicate_event_ids = sorted(
        event_id
        for event_id in set(seen_event_ids)
        if seen_event_ids.count(event_id) > 1
    )
    missing_event_ids = sorted(expected_event_ids - set(seen_event_ids))
    feedback = {
        "missing_event_ids": missing_event_ids,
        "duplicate_event_ids": duplicate_event_ids,
        "unknown_event_ids": sorted(unknown_event_ids),
        "cross_event_evidence_ids": sorted(cross_event_evidence_ids),
        "invalid_event_decisions": invalid_event_decisions,
        "malformed_event_results": malformed_event_results,
    }
    accepted = not any(
        (
            missing_event_ids,
            duplicate_event_ids,
            unknown_event_ids,
            cross_event_evidence_ids,
            invalid_event_decisions,
            malformed_event_results,
        )
    )
    return flattened, accepted, feedback


def publication_candidate_groups(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    """Build deterministic event groups without discarding a distinct candidate."""
    selected = [
        record
        for _, record in core.editor_evidence_records(category, issue_date, records)
    ]
    event_groups: list[list[dict[str, Any]]] = []
    for record in selected:
        title = core.record_public_title(record)
        group = next(
            (
                candidate
                for candidate in event_groups
                if candidate
                and core.same_material_event(
                    title,
                    core.record_public_title(candidate[0]),
                )
            ),
            None,
        )
        if group is None:
            event_groups.append([record])
        else:
            group.append(record)
    return event_groups


def previous_category_updates(
    state_root: Path,
    issue_date: str,
    category_label: str,
) -> list[dict[str, Any]]:
    """Return the latest prior public issue as novelty context, never as Evidence."""
    issue_paths = sorted(
        (
            path
            for path in state_root.glob("20??-??-??/issue.json")
            if path.parent.name < issue_date
        ),
        reverse=True,
    )
    for issue_path in issue_paths:
        try:
            issue = json.loads(issue_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cards = issue.get("cards")
        if not isinstance(cards, list):
            continue
        return [
            {
                "date": issue.get("issue_date"),
                "title": card.get("title"),
                "summary": card.get("summary"),
            }
            for card in cards
            if isinstance(card, dict)
            and str(card.get("category", "")) == category_label
        ]
    return []


def publication_record_chunks(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
    *,
    event_groups: list[list[dict[str, Any]]] | None = None,
    previous_updates: list[dict[str, Any]] | None = None,
    max_records: int = 10,
    max_payload_bytes: int = 30_000,
) -> list[list[dict[str, Any]]]:
    """Pack selected events by model payload size while preserving every record."""
    raw_groups = (
        event_groups
        if event_groups is not None
        else publication_candidate_groups(category, issue_date, records)
    )
    groups: list[list[dict[str, Any]]] = []
    for index, group in enumerate(raw_groups, start=1):
        titles = [core.record_public_title(record) for record in group]
        matching_previous = [
            {
                "date": update.get("date"),
                "title": compact_text(update.get("title", ""), 180),
                "summary": compact_text(update.get("summary", ""), 700),
            }
            for update in previous_updates or []
            if any(
                core.same_material_event(title, str(update.get("title", "")))
                for title in titles
            )
        ]
        groups.append(
            [
                {
                    **record,
                    "_editor_event_id": f"g{index:03d}",
                    "_editor_previous_updates": matching_previous,
                }
                for record in group
            ]
        )
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for group in groups:
        group_payload_size = len(
            json.dumps(
                core.category_prompt(category, issue_date, group),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        if current:
            combined = [*current, *group]
            combined_size = len(
                json.dumps(
                    core.category_prompt(category, issue_date, combined),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if len(combined) <= max_records and combined_size <= max_payload_bytes:
                current = combined
                continue
            chunks.append(current)
            current = []
        if group_payload_size <= max_payload_bytes:
            current = list(group)
            if len(current) >= max_records:
                chunks.append(current)
                current = []
            continue
        for record in group:
            proposed = [*current, record]
            payload_size = len(
                json.dumps(
                    core.category_prompt(category, issue_date, proposed),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            if current and (
                len(proposed) > max_records or payload_size > max_payload_bytes
            ):
                chunks.append(current)
                current = [record]
            else:
                current = proposed
            if len(current) >= max_records:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def fit_model_payload(
    payload: dict[str, Any],
    *,
    max_bytes: int = 32_000,
) -> dict[str, Any]:
    size = len(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if size > max_bytes:
        raise ValueError(
            f"model payload exceeds the lossless request limit: {size} > {max_bytes}"
        )
    return payload


def read_evidence(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing research bundle: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid research bundle JSON: {exc}")
    if not isinstance(value, dict):
        fail("research bundle must be an object")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def category_config() -> dict[str, dict[str, Any]]:
    contract = state.read_json(state.CONFIG_PATH)
    return {
        str(category["label"]): category
        for category in contract.get("categories", [])
        if isinstance(category, dict)
    }


def item_card(
    category: str,
    section_id: str,
    item: dict[str, Any],
    issue_date: str,
) -> dict[str, Any]:
    card_title, card_summary = public_item_copy(item)
    facts = [
        fact
        for fact in state.normalize_material_facts(
            card_title,
            item["confirmed_facts"],
        )
        if state.fact_adds_information(card_title, fact)
    ]
    if not facts:
        raise UnpublishableItem(
            f"item lacks a confirmed fact beyond its public title: {card_title}"
        )
    slug = str(item["slug"])
    slug_stem = slug[:-5] if slug.endswith(".html") else slug
    if not slug_stem.endswith(f"-{issue_date}"):
        slug_stem = f"{slug_stem}-{issue_date}"
    slug = f"{slug_stem}.html"
    return {
        "watch_topic_id": str(item["watch_topic_id"]),
        "title": card_title,
        "summary": card_summary,
        "section_id": section_id,
        "category": category,
        "source_published_date": str(item["source_published_date"]),
        "topic_value_class": topic_value_class(item["topic_value_class"]),
        "priority_class": str(item["priority_class"]),
        "change_class": str(item["change_class"]),
        "detail": {
            "slug": slug,
            "sources": [
                {
                    "label": str(source["label"]),
                    "url": str(source["url"]),
                }
                for source in item["sources"]
            ],
            "summary": card_summary,
            "summary_basis": {
                "confirmed_facts": facts,
                "fact_sources": item["fact_sources"],
                "source_dates": sorted(
                    {
                        str(source.get("published_date"))
                        for source in item["sources"]
                        if source.get("published_date")
                    }
                ),
            },
        },
    }


def merge_repeated_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    priority_rank = {"top": 0, "priority": 1, "standard": 2}
    for card in cards:
        existing = next(
            (
                candidate
                for candidate in merged
                if candidate.get("category") == card.get("category")
                and core.same_material_event(candidate.get("title"), card.get("title"))
            ),
            None,
        )
        if existing is None:
            merged.append(card)
            continue

        existing_basis = existing["detail"]["summary_basis"]
        incoming_basis = card["detail"]["summary_basis"]
        raw_facts = [
            *existing_basis.get("confirmed_facts", []),
            *incoming_basis.get("confirmed_facts", []),
        ]
        facts = [
            fact
            for fact in state.normalize_material_facts(
                str(existing["title"]), raw_facts, limit=max(1, len(raw_facts))
            )
            if state.fact_adds_information(str(existing["title"]), fact)
        ]
        mappings = [
            mapping
            for mapping in [
                *existing_basis.get("fact_sources", []),
                *incoming_basis.get("fact_sources", []),
            ]
            if isinstance(mapping, dict)
        ]
        fact_sources = []
        for fact in facts:
            urls = list(
                dict.fromkeys(
                    str(url)
                    for mapping in mappings
                    if state.materially_same_fact(fact, str(mapping.get("fact", "")))
                    for url in mapping.get("source_urls", [])
                    if isinstance(url, str) and url
                )
            )
            if urls:
                fact_sources.append({"fact": fact, "source_urls": urls})
        if len(fact_sources) != len(facts):
            merged.append(card)
            continue

        existing["summary"] = " ".join(facts)
        existing["detail"]["summary"] = existing["summary"]
        existing_basis["confirmed_facts"] = facts
        existing_basis["fact_sources"] = fact_sources
        existing_basis["source_dates"] = sorted(
            set(existing_basis.get("source_dates", []))
            | set(incoming_basis.get("source_dates", []))
        )
        existing["detail"]["sources"] = list(
            {
                str(source.get("url")): source
                for source in [
                    *existing["detail"].get("sources", []),
                    *card["detail"].get("sources", []),
                ]
                if isinstance(source, dict) and source.get("url")
            }.values()
        )
        existing["source_published_date"] = max(
            str(existing.get("source_published_date", "")),
            str(card.get("source_published_date", "")),
        )
        if priority_rank.get(str(card.get("priority_class")), 2) < priority_rank.get(
            str(existing.get("priority_class")), 2
        ):
            existing["priority_class"] = card["priority_class"]
        if existing.get("change_class") != card.get("change_class"):
            existing["change_class"] = "material_update"
    return merged


def edit_evidence(
    issue_date: str,
    evidence_path: Path,
    state_root: Path,
    token: str,
) -> dict[str, Any]:
    evidence = read_evidence(evidence_path)
    try:
        evidence_report = evidence_store.validate_bundle(evidence, issue_date)
    except evidence_store.EvidenceContractError as exc:
        fail(str(exc))
    if evidence_report["editor_coverage_gaps"]:
        fail(
            "Evidence has material watch topics without resolved source content: "
            + ", ".join(evidence_report["editor_coverage_gaps"])
        )
    categories = evidence["categories"]
    configs = category_config()

    contracts = core.category_contracts()
    evidence_hash = evidence_store.bundle_sha256(evidence_path)
    editor_contract_hash = state.editor_contract_sha256()
    checkpoint_path = state_root / issue_date / "editor_checkpoint.json"
    checkpoint: dict[str, Any] = {
        "evidence_sha256": evidence_hash,
        "editor_contract_sha256": editor_contract_hash,
        "chunks": {},
    }
    try:
        stored_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        stored_checkpoint = None
    if (
        isinstance(stored_checkpoint, dict)
        and stored_checkpoint.get("evidence_sha256") == evidence_hash
        and stored_checkpoint.get("editor_contract_sha256") == editor_contract_hash
        and isinstance(stored_checkpoint.get("chunks"), dict)
    ):
        checkpoint = stored_checkpoint

    def save_checkpoint() -> None:
        write_json_atomic(checkpoint_path, checkpoint)

    def validated_model_result(
        *,
        messages: list[dict[str, str]],
        model_chain: list[str],
        request_label: str,
        response_schema: dict[str, Any] | None,
        response_schema_name: str,
        max_output_tokens: int | None,
        validate: Callable[[dict[str, Any]], tuple[Any, bool, dict[str, Any]]],
        correction: Callable[[dict[str, Any]], str],
        log_context: dict[str, Any],
        log_fields: Callable[[Any], dict[str, Any]],
    ) -> tuple[Any | None, dict[str, Any], bool]:
        quality_model = str(
            models.load_config().get("extraction", {}).get("quality_model", "")
        )
        feedback: dict[str, Any] = {}
        last_result: Any | None = None
        for model_index, model_name in enumerate(model_chain):
            attempt_messages = messages
            max_attempts = 2 if model_index == 0 else 1
            for attempt in range(1, max_attempts + 1):
                try:
                    raw = models.request(
                        token,
                        attempt_messages,
                        model_name=model_name,
                        retry_wait_cap=90,
                        request_label=request_label,
                        response_schema=response_schema,
                        response_schema_name=response_schema_name,
                        max_output_tokens=max_output_tokens,
                    )
                except models.ModelRequestError as exc:
                    print(
                        json.dumps(
                            {
                                **log_context,
                                "phase": "model_request_failed",
                                "model": model_name,
                                "status_code": exc.status_code,
                                "rate_limited": exc.rate_limited,
                                "error": str(exc),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    if exc.rate_limited or model_name != model_chain[-1]:
                        break
                    raise
                result, accepted, feedback = validate(raw)
                last_result = result
                print(
                    json.dumps(
                        {
                            **log_context,
                            "model": model_name,
                            "attempt": attempt,
                            **log_fields(result),
                            "accepted": accepted,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                if accepted:
                    return result, feedback, True
                attempt_messages = [
                    *messages,
                    {
                        "role": "assistant",
                        "content": "Previous JSON failed deterministic validation.",
                    },
                    {"role": "user", "content": correction(feedback)},
                ]
        return last_result, feedback, False

    def cards_from_raw(
        raw: dict[str, Any],
        category: dict[str, Any],
        label: str,
        records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, bool, dict[str, Any]]:
        flattened, event_response_accepted, event_response_feedback = (
            flatten_event_response(raw, category, issue_date, records)
        )
        flattened = sanitize_model_result(flattened)
        normalized = core.normalize_result(
            flattened,
            category,
            issue_date,
            records,
        )
        cards: list[dict[str, Any]] = []
        failed = 0
        for item in normalized["items"]:
            try:
                cards.append(
                    item_card(
                        label,
                        str(configs[label]["section_id"]),
                        item,
                        issue_date,
                    )
                )
            except UnpublishableItem as exc:
                failed += 1
                print(
                    json.dumps(
                        {
                            "phase": "unpublishable_item",
                            "category": label,
                            "title": str(item.get("title", "")),
                            "reason": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        accepted = (
            event_response_accepted
            and bool(normalized["coverage_complete"])
            and not normalized["rejected_items"]
            and failed == 0
        )
        if not accepted:
            print(
                json.dumps(
                    {
                        "phase": "editor_result_rejected",
                        "category": label,
                        "missing_event_ids": normalized["missing_event_ids"],
                        "unpublishable_items": failed,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        feedback = {
            "missing_event_ids": normalized["missing_event_ids"],
            "conflicting_event_ids": normalized["conflicting_event_ids"],
            "unknown_excluded_event_ids": normalized[
                "unknown_excluded_event_ids"
            ],
            "unpublishable_items": failed,
            "rejected_items": normalized["rejected_items"],
            "event_response": event_response_feedback,
        }
        return cards, failed, accepted, feedback

    def review_category(category: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        label = str(category["label"])
        entry = categories[label]
        if not isinstance(entry, dict) or not isinstance(entry.get("records"), list):
            fail(f"Evidence records are missing: {label}")
        records = [record for record in entry["records"] if isinstance(record, dict)]
        selected_event_groups = publication_candidate_groups(
            category,
            issue_date,
            records,
        )
        previous_updates = previous_category_updates(state_root, issue_date, label)
        chunks = publication_record_chunks(
            category,
            issue_date,
            records,
            event_groups=selected_event_groups,
            previous_updates=previous_updates,
        )
        category_cards: list[dict[str, Any]] = []
        for chunk_index, chunk_records in enumerate(chunks, start=1):
            category_payload = fit_model_payload(
                core.category_prompt(category, issue_date, chunk_records)
            )
            checkpoint_key = hashlib.sha256(
                json.dumps(
                    category_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            stored_cards = checkpoint["chunks"].get(checkpoint_key)
            if isinstance(stored_cards, list) and all(
                isinstance(card, dict) for card in stored_cards
            ):
                category_cards.extend(stored_cards)
                print(
                    json.dumps(
                        {
                            "phase": "editor_checkpoint_reused",
                            "category": label,
                            "chunk": chunk_index,
                            "chunks": len(chunks),
                            "cards": len(stored_cards),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                continue
            def request_records(
                request_records_value: list[dict[str, Any]],
                request_suffix: str,
            ) -> tuple[Any | None, dict[str, Any], bool]:
                request_payload = fit_model_payload(
                    core.category_prompt(
                        category,
                        issue_date,
                        request_records_value,
                    )
                )
                quality_required = quality_model_required(request_payload)
                messages = [
                    {"role": "system", "content": models.SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            request_payload,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                ]

                def validate_summary(
                    raw: dict[str, Any],
                ) -> tuple[Any, bool, dict[str, Any]]:
                    result = cards_from_raw(
                        raw,
                        category,
                        label,
                        request_records_value,
                    )
                    return result, result[2], result[3]

                model_chain = models.routed_models(
                    quality_required=quality_required
                )
                if (
                    quality_required
                    and len(request_payload.get("events", [])) == 1
                    and models.extraction_model() not in model_chain
                ):
                    model_chain.append(models.extraction_model())
                return validated_model_result(
                    messages=messages,
                    model_chain=model_chain,
                    request_label=(
                        f"{label} {chunk_index}/{len(chunks)}{request_suffix}"
                    ),
                    response_schema=models.editor_response_schema(
                        [str(event["id"]) for event in request_payload["events"]]
                    ),
                    response_schema_name="night_signal_editor_result",
                    max_output_tokens=None,
                    validate=validate_summary,
                    correction=lambda value: (
                        "Return the entire corrected JSON for the supplied events. Apply "
                        "only the fixes named by validation. For title_copy, use a concise "
                        "concrete reader title without a colon, pipe, brackets, publisher "
                        "wording, or vague phrases such as latest developments. For "
                        "summary_copy, summary_repetition, insufficient_facts, or "
                        "generic_padding, remove title restatements and generic context "
                        "while retaining every distinct source-backed fact. For each "
                        "unsupported_facts entry, rewrite it closely from the cited "
                        "Evidence or remove it; never expand the number of facts. Keep "
                        "every item inside its exact event_id. Set decision=publish only "
                        "when at least one valid item remains; otherwise return no items "
                        "and choose the applicable event exclusion decision. Validation "
                        "feedback: "
                        + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                    ),
                    log_context={
                        "phase": "model_route",
                        "category": label,
                        "route": "quality" if quality_required else "routine",
                        "chunk": chunk_index,
                        "chunks": len(chunks),
                        "scope": request_suffix.strip() or "full",
                    },
                    log_fields=lambda value: {
                        "cards": len(value[0]),
                        "unpublishable_items": value[1],
                    },
                )

            chunk_cards: list[dict[str, Any]] = []
            work_queue: list[tuple[list[dict[str, Any]], str]] = [
                (chunk_records, "")
            ]
            failed_scope = False
            recovery_round = 0
            while work_queue:
                pending_records, suffix = work_queue.pop(0)
                selected_result, feedback, accepted = request_records(
                    pending_records,
                    suffix,
                )
                if selected_result is None:
                    failed_scope = True
                    break
                if accepted:
                    chunk_cards.extend(selected_result[0])
                    continue
                event_feedback = feedback.get("event_response", {})
                invalid_event_response = any(event_feedback.values())
                unsafe_non_event_feedback = (
                    feedback.get("conflicting_event_ids")
                    or feedback.get("unknown_excluded_event_ids")
                    or has_non_boundary_rejection(feedback.get("rejected_items"))
                    or feedback.get("unpublishable_items")
                )
                if invalid_event_response and not unsafe_non_event_feedback:
                    records_by_event: dict[str, list[dict[str, Any]]] = {}
                    for record in pending_records:
                        event_id = str(record.get("_editor_event_id", ""))
                        records_by_event.setdefault(event_id, []).append(record)
                    if len(records_by_event) > 1:
                        isolated = [
                            (records, f" event-{event_id}")
                            for event_id, records in records_by_event.items()
                        ]
                        work_queue = [*isolated, *work_queue]
                        continue
                missing_ids = set(feedback.get("missing_event_ids", []))
                next_pending = [
                    record
                    for record in pending_records
                    if str(record.get("_editor_event_id", "")) in missing_ids
                ]
                if (
                    unsafe_non_event_feedback
                    or invalid_event_response
                    or not next_pending
                    or len(next_pending) >= len(pending_records)
                ):
                    if (
                        not unsafe_non_event_feedback
                        and not invalid_event_response
                        and len(pending_records) > 1
                    ):
                        records_by_event: dict[str, list[dict[str, Any]]] = {}
                        for record in pending_records:
                            records_by_event.setdefault(
                                str(record.get("_editor_event_id", "")), []
                            ).append(record)
                        isolated_events = [
                            (event_records, f" event-{event_id}")
                            for event_id, event_records in records_by_event.items()
                        ]
                        if len(isolated_events) > 1:
                            work_queue = [*isolated_events, *work_queue]
                            continue
                    failed_scope = True
                    break
                chunk_cards.extend(selected_result[0])
                recovery_round += 1
                work_queue.insert(
                    0,
                    (next_pending, f" recovery-{recovery_round}"),
                )
            if failed_scope:
                fail(
                    "Editor could not produce a valid decision for every event: "
                    f"{label} chunk {chunk_index}/{len(chunks)}"
                )
            chunk_cards = merge_repeated_cards(chunk_cards)
            checkpoint["chunks"][checkpoint_key] = chunk_cards
            save_checkpoint()
            category_cards.extend(chunk_cards)
        return label, merge_repeated_cards(category_cards)

    cards_by_category: dict[str, list[dict[str, Any]]] = {}
    for category in contracts:
        label, category_cards = review_category(category)
        cards_by_category[label] = category_cards
    cards = [
        card
        for category in configs
        for card in cards_by_category.get(category, [])
    ]
    if not cards:
        fail("Editor produced no evidence-backed important update")

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
    base = state_root / issue_date
    base.mkdir(parents=True, exist_ok=True)
    issue_path = base / "issue.json"
    state.validate_issue_state(issue, issue_path, evidence)
    temp = issue_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(issue_path)
    return {
        "issue_date": issue_date,
        "issue_state": str(issue_path),
        "cards": len(cards),
        "categories": len(configs),
        "evidence": str(evidence_path),
    }


def self_test() -> None:
    core.self_test()
    if sanitize_editor_title(
        "OpenAIの政府株式提供提案とAI業界の最新動向"
    ) != "OpenAIの政府株式提供提案":
        fail("Editor did not remove a trailing vague title phrase")
    with tempfile.TemporaryDirectory() as temporary_directory:
        sample_evidence = Path(temporary_directory) / "evidence.json"
        sample_evidence.write_bytes(b"canonical evidence")
        expected_hash = hashlib.sha256(b"canonical evidence").hexdigest()
        if evidence_store.bundle_sha256(sample_evidence) != expected_hash:
            fail("Evidence checkpoint hash is not reproducible")
    sanitized = sanitize_model_result(
        {
            "items": [
                {
                    "summary_points": [
                        {
                            "text": "投資額は500億円。",
                            "evidence_ids": ["e001"],
                            "support_quotes": [
                                {"evidence_id": "e001", "quote": "投資額は500億円。"}
                            ],
                        },
                        {
                            "text": "投資額は500億円。",
                            "evidence_ids": ["e002"],
                            "support_quotes": [
                                {"evidence_id": "e002", "quote": "投資額は500億円。"}
                            ],
                        },
                    ]
                }
            ],
            "excluded_events": [],
        }
    )
    sanitized_points = sanitized["items"][0]["summary_points"]
    if len(sanitized_points) != 1 or sanitized_points[0]["evidence_ids"] != [
        "e001",
        "e002",
    ]:
        fail("Editor did not merge repeated model points and their evidence ids")
    bounded_payload = {
        "category": "Test",
        "allowed_watch_topic_ids": [],
        "events": [
            {
                "id": "g001",
                "previous_updates": [],
                "evidence": [
                    {
                        "id": f"e{index:03d}",
                        "title": f"題名{index}",
                        "body": "詳しい本文。" * 400,
                    }
                    for index in range(1, 4)
                ],
            }
        ],
    }
    fitted_payload = fit_model_payload(bounded_payload)
    fitted_bytes = len(
        json.dumps(
            fitted_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if fitted_bytes > 32_000 or {
        item["id"] for item in fitted_payload["events"][0]["evidence"]
    } != {"e001", "e002", "e003"}:
        fail("Editor payload fitting dropped evidence or exceeded the request bound")
    if fitted_payload != bounded_payload:
        fail("Editor payload fitting altered source bodies")
    too_large = {
        **bounded_payload,
        "events": [
            {
                **bounded_payload["events"][0],
                "evidence": [
                    {
                        "id": f"e{index:03d}",
                        "title": f"題名{index}",
                        "body": "詳しい本文。" * 2000,
                    }
                    for index in range(1, 4)
                ],
            }
        ],
    }
    try:
        fit_model_payload(too_large)
    except ValueError:
        pass
    else:
        fail("Editor accepted a payload only by silently shortening its source body")
    if quality_model_required(
        {"events": [{"evidence": [{"title": "企業が新製品を発売", "body": "企業は新製品を7月に発売した。"}]}]}
    ):
        fail("Editor routed a routine factual extraction to the quality model")
    if not quality_model_required(
        {"events": [{"evidence": [{"title": "【分析】市場構造を検証", "body": "複数の数値から市場構造を分析した。"}]}]}
    ):
        fail("Editor did not route analysis work to the quality model")
    if quality_model_required(
        {"events": [{"evidence": [{"title": "Product update", "body": "The company released a major product update with new enterprise controls."}]}]}
    ):
        fail("Editor routed a short factual translation to the quality model")
    if quality_model_required(
        {"events": [{"evidence": [{"title": "詳細発表", "body": "具体的な変更内容。" * 100}]}]}
    ):
        fail("Editor routed length alone to the quality model")
    if not quality_model_required(
        {
            "events": [
                {
                    "evidence": [
                        {
                            "title": "統計表を公表",
                            "body": "| 指標 | 前月 | 今月 |\n| --- | --- | --- |\n| 生産 | 10 | 12 |",
                        }
                    ]
                }
            ]
        }
    ):
        fail("Editor did not route a table-dependent summary to the quality model")
    if has_non_boundary_rejection(
        [{"reasons": ["event_evidence_mismatch", "mixed_event_boundary"]}]
    ):
        fail("Event-boundary recovery was blocked by its own rejection reason")
    if not has_non_boundary_rejection(
        [{"reasons": ["mixed_event_boundary", "unsupported_title"]}]
    ):
        fail("Event-boundary recovery ignored a real content rejection")
    review_category = {
        "label": "OpenAI",
        "watch_topics": [
            {"id": "product_release", "terms": ["OpenAI", "release"]},
            {"id": "ipo_financing", "terms": ["OpenAI", "IPO"]},
        ],
    }
    review_records = [
        {
            "label": "OpenAI",
            "url": "https://openai.com/release",
            "source_role": "official_primary",
            "channel": "web",
            "source_class": "discovered_media",
            "observed": True,
            "published_date": "2099-01-02",
            "title": "OpenAIが新モデルを公開",
            "excerpt": "OpenAIは新モデルを公開し、企業向け制御を追加した。",
            "watch_topic_ids": ["product_release"],
        },
        {
            "label": "Market Data",
            "url": "https://example.com/static-quote",
            "source_role": "independent_media_or_data",
            "channel": "web",
            "source_class": "discovered_media",
            "observed": True,
            "published_date": "2099-01-02",
            "title": "OpenAI IPOの価格情報",
            "excerpt": "OpenAI IPOの価格情報を表示する静的ページ。",
            "watch_topic_ids": ["ipo_financing"],
        },
    ]
    bridging_records = [
        review_records[0],
        {
            **review_records[0],
            "url": "https://example.com/openai-profile",
            "title": "OpenAI",
            "excerpt": "OpenAIの企業プロフィールとフォロワー数を掲載するページ。",
        },
        {
            **review_records[0],
            "url": "https://example.com/openai-lawsuit",
            "title": "新聞社がOpenAI著作権訴訟で制裁を申し立て",
            "excerpt": "新聞社は著作権訴訟でOpenAIへの制裁を裁判所に申し立てた。",
        },
    ]
    bridging_groups = publication_candidate_groups(
        review_category,
        "2099-01-02",
        bridging_records,
    )
    if any(
        {record.get("url") for record in group}
        >= {
            "https://openai.com/release",
            "https://example.com/openai-lawsuit",
        }
        for group in bridging_groups
    ):
        fail("Generic entity page bridged separate publication events")
    duplicate_report = {
        **review_records[0],
        "label": "Example News",
        "url": "https://example.com/openai-release",
        "title": "OpenAI、新モデルを一般公開",
    }
    grouped_summary_chunks = publication_record_chunks(
        review_category,
        "2099-01-02",
        review_records,
        event_groups=[[review_records[0], duplicate_report]],
        max_records=1,
    )
    if len(grouped_summary_chunks) != 1 or len(grouped_summary_chunks[0]) != 2:
        fail("Summary chunking split one event despite fitting the payload bound")
    grouped_payload = core.category_prompt(
        review_category,
        "2099-01-02",
        grouped_summary_chunks[0],
    )
    if len(grouped_payload["events"]) != 1 or not grouped_payload["events"][0][
        "evidence"
    ]:
        fail("Editor prompt lost the deterministic event boundary")
    event_result = {
        "events": [
            {
                "event_id": grouped_payload["events"][0]["id"],
                "decision": "duplicate_previous_event",
                "items": [],
            }
        ]
    }
    flattened, event_accepted, event_feedback = flatten_event_response(
        event_result,
        review_category,
        "2099-01-02",
        grouped_summary_chunks[0],
    )
    if (
        not event_accepted
        or event_feedback["missing_event_ids"]
        or len(flattened["excluded_events"]) != 1
    ):
        fail("Editor did not account for one complete event response")
    _, missing_event_accepted, missing_event_feedback = flatten_event_response(
        {"events": []},
        review_category,
        "2099-01-02",
        grouped_summary_chunks[0],
    )
    if missing_event_accepted or missing_event_feedback["missing_event_ids"] != [
        grouped_payload["events"][0]["id"]
    ]:
        fail("Editor accepted a missing event result")
    summary_chunks = publication_record_chunks(
        review_category,
        "2099-01-02",
        review_records,
        event_groups=[[review_records[0]]],
        max_records=1,
    )
    if len(summary_chunks) != 1 or summary_chunks[0][0]["url"] != review_records[0]["url"]:
        fail("Summary chunking reintroduced an excluded event")
    item = {
        "evidence_ids": ["e001"],
        "watch_topic_id": "product_release",
        "title": "OpenAIがCodex Security更新版を公開",
        "source_published_date": "2099-01-01",
        "topic_value_class": "technical_or_product_shift",
        "priority_class": "priority",
        "change_class": "material_update",
        "slug": "openai-codex-security",
        "confirmed_facts": [
            "更新版には脆弱性検出後の修正支援が追加された。",
            "企業向けコード監査で検出から修正までを一つの流れで扱える。",
        ],
        "summary": (
            "更新版には脆弱性検出後の修正支援が追加された。 "
            "企業向けコード監査で検出から修正までを一つの流れで扱える。"
        ),
        "fact_sources": [
            {
                "fact": "更新版には脆弱性検出後の修正支援が追加された。",
                "source_urls": ["https://openai.com/example"],
            },
            {
                "fact": "企業向けコード監査で検出から修正までを一つの流れで扱える。",
                "source_urls": ["https://openai.com/example"],
            },
        ],
        "sources": [
            {
                "label": "OpenAI",
                "url": "https://openai.com/example",
                "published_date": "2099-01-01",
            }
        ],
    }
    card = item_card("OpenAI", "openai", item, "2099-01-01")
    if set(card) != {
        "title",
        "watch_topic_id",
        "summary",
        "section_id",
        "category",
        "source_published_date",
        "topic_value_class",
        "priority_class",
        "change_class",
        "detail",
    }:
        fail("Editor emitted fields outside the minimal public update contract")
    if not summary_is_reader_facing(card["title"], card["summary"]):
        fail("Editor emitted a title-only or repetitive summary")
    basis = card["detail"]["summary_basis"]
    if set(basis["confirmed_facts"]) != {
        mapping["fact"] for mapping in basis["fact_sources"]
    }:
        fail("Editor did not map every confirmed fact to evidence")
    rich_item = {
        **item,
        "title": "ベトナム、初の原子力発電所建設計画を加速",
        "confirmed_facts": [
            "建設候補地はニントゥアン省に置かれる。",
            "第1原発はロシアの協力で建設する計画となっている。",
            "第1原発はロシアの協力で建設する計画である。",
            "第2原発は日本との協力を想定している。",
            "政府は2030年までの着工を目標に掲げた。",
            "初号機の運転開始時期は2035年を想定している。",
            "設備容量は合計4ギガワットを計画している。",
        ],
        "sources": [
            {
                "label": "Government",
                "url": "https://example.com/nuclear",
                "published_date": "2099-01-01",
            }
        ],
    }
    rich_item["confirmed_facts"] = state.normalize_material_facts(
        rich_item["title"], rich_item["confirmed_facts"]
    )
    rich_item["summary"] = " ".join(rich_item["confirmed_facts"])
    rich_item["fact_sources"] = [
        {"fact": fact, "source_urls": ["https://example.com/nuclear"]}
        for fact in rich_item["confirmed_facts"]
    ]
    rich_card = item_card("日本経済", "japan-economy", rich_item, "2099-01-01")
    rich_facts = rich_card["detail"]["summary_basis"]["confirmed_facts"]
    if len(rich_facts) != 6:
        fail("Editor truncated distinct facts or retained a duplicate paraphrase")
    if not state.summary_covers_material_facts(
        f"{rich_card['title']}。 {rich_card['summary']}", rich_facts
    ):
        fail("Editor summary did not preserve every distinct confirmed fact")
    thin_item = {
        **item,
        "title": "企業が国内工場への追加投資を決定",
        "confirmed_facts": ["追加投資額は500億円で、2027年に新設備を稼働する。"],
        "summary": "追加投資額は500億円で、2027年に新設備を稼働する。",
        "fact_sources": [
            {
                "fact": "追加投資額は500億円で、2027年に新設備を稼働する。",
                "source_urls": ["https://openai.com/example"],
            }
        ],
    }
    thin_card = item_card("日本経済", "japan-economy", thin_item, "2099-01-01")
    if thin_card["summary"] != "追加投資額は500億円で、2027年に新設備を稼働する。":
        fail("Editor padded a thin source instead of keeping its supported fact concise")
    if SUMMARY_LABEL_RE.search(card["detail"]["summary"]):
        fail("Editor kept label-heavy detail copy")
    if set(card["detail"]["summary_basis"]) != {
        "confirmed_facts",
        "fact_sources",
        "source_dates",
    }:
        fail("Editor retained a second prose path in the summary basis")
    print("NIGHT SIGNAL EDITOR SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument(
        "--evidence",
        type=Path,
        help="defaults to state/YYYY-MM-DD/evidence.json",
    )
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        fail("GITHUB_TOKEN or GH_TOKEN is required for Editor model access")
    evidence = args.evidence or args.state_root / args.issue_date / "evidence.json"
    print(
        json.dumps(
            edit_evidence(args.issue_date, evidence, args.state_root, token),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
