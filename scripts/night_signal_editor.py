#!/usr/bin/env python3
"""Edit collected Evidence into the canonical NIGHT SIGNAL Issue."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date
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
MAX_EDITOR_EVENT_CANDIDATES_PER_CATEGORY = 4
MAX_EDITOR_RECORDS_PER_EVENT = 2
EXTRA_EDITOR_EVENTS_PER_CATEGORY = 1
MAX_SEMANTIC_DEDUP_EVENTS_PER_CATEGORY = 12
MAX_MODEL_RESPONSES_PER_SCOPE = 2
NOVELTY_CHANGE_RE = re.compile(
    r"(延期|中止|承認|却下|開始|終了|発売|提供開始|公開|更新|"
    r"増加|減少|上昇|下落|急落|契約|提携|買収|出資|資金調達|"
    r"就任|退任|移籍|獲得|勝利|敗北|達成|突破|"
    r"delay|cancel|approve|reject|launch|release|update|"
    r"increase|decrease|rise|fall|sign|acquire|invest|raise)",
    re.I,
)


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


def validation_attempt_limit(successful_response_seen: bool) -> int:
    """Allow one correction on the first model that actually returns a response."""
    return 1 if successful_response_seen else 2


def sanitize_editor_title(value: Any) -> str:
    title = core.reader_facing_text(value, 180)
    title = re.split(r"[。！？!?](?:\s+|$)", title, maxsplit=1)[0]
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


def record_material_sentences(record: dict[str, Any]) -> list[str]:
    return [
        sentence
        for sentence in core.sentence_parts(core.editor_source_text(record, 2400))
        if len(state.copy_signature(sentence)) >= 18
        and not state.material_fact_violations(sentence)
        and not state.GENERIC_ENTITY_OVERVIEW_RE.search(sentence)
        and not core.INVESTMENT_GUIDE_RE.search(sentence)
        and not core.NON_NEWS_GUIDE_RE.search(sentence)
    ]


def novelty_numbers(text: str) -> set[str]:
    without_dates = re.sub(
        r"20\d{2}(?:年|[-/.])\d{1,2}(?:月|[-/.])\d{1,2}日?|"
        r"(?<!\d)\d{1,2}(?:月|/)\d{1,2}日?",
        " ",
        str(text),
    )
    return set(re.findall(r"\d+(?:\.\d+)?", without_dates))


def summary_output_budget(record_count: int) -> int:
    """Bound generated JSON to the number of Evidence records in one request."""
    return min(4_000, max(1_600, 700 + 550 * max(1, record_count)))


def records_describe_same_information(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    left_title = core.record_public_title(left)
    right_title = core.record_public_title(right)
    if core.same_material_event(left_title, right_title):
        return True
    left_body = core.editor_source_text(left, 2400)
    right_body = core.editor_source_text(right, 2400)
    if state.materially_same_fact(left_body, right_body):
        return True
    if state.text_overlap(left_title, right_title) < 2:
        return False
    return any(
        state.materially_same_fact(left_fact, right_fact)
        for left_fact in record_material_sentences(left)
        for right_fact in record_material_sentences(right)
    )


def event_group_has_new_information(
    group: list[dict[str, Any]],
    previous_updates: list[dict[str, Any]],
    issue_date: str,
) -> bool:
    """Conservatively reject an event already covered by the prior public issue."""
    if not previous_updates:
        return True
    issue_day = date.fromisoformat(issue_date)
    for record in group:
        title = core.record_public_title(record)
        matches = [
            update
            for update in previous_updates
            if core.same_material_event(title, str(update.get("title", "")))
        ]
        if not matches:
            return True
        prior_facts = [
            sentence
            for update in matches
            for sentence in core.sentence_parts(
                f"{update.get('title', '')}。 {update.get('summary', '')}"
            )
        ]
        title_numbers = novelty_numbers(title)
        prior_numbers = novelty_numbers(" ".join(prior_facts))
        title_changes = {
            value.casefold() for value in NOVELTY_CHANGE_RE.findall(title)
        }
        prior_changes = {
            value.casefold()
            for value in NOVELTY_CHANGE_RE.findall(" ".join(prior_facts))
        }
        if (title_changes - prior_changes) or (title_numbers - prior_numbers):
            return True
        for fact in record_material_sentences(record):
            if re.search(r"20\d{2}年.{0,30}(?:設立|創業|移行)", fact):
                continue
            fact_dates = core.explicit_title_event_dates(fact, issue_day)
            if fact_dates and all(
                event_date <= issue_day and (issue_day - event_date).days > 7
                for event_date in fact_dates
            ):
                continue
            if not any(
                state.materially_same_fact(fact, prior_fact)
                for prior_fact in prior_facts
            ):
                return True
    return False


def event_record_priority(record: dict[str, Any]) -> tuple[int, int, int, int, str]:
    title = core.record_public_title(record)
    role_score = {
        "official_primary": 4,
        "primary_or_official": 4,
        "independent_media_or_data": 3,
        "social_or_video_signal": 2,
    }.get(str(record.get("source_role", "")), 1)
    return (
        role_score,
        int(core.record_evidence_depth(title, record) == "body"),
        int(bool(core.PUBLICATION_EVENT_RE.search(title))),
        int(bool(re.search(r"\d+(?:\.\d+)?", title))),
        compact_text(title, 180),
    )


def bounded_event_records(
    group: list[dict[str, Any]],
    *,
    max_records: int = MAX_EDITOR_RECORDS_PER_EVENT,
) -> list[dict[str, Any]]:
    """Keep a small, source-diverse evidence set for one material event."""
    ranked = sorted(group, key=event_record_priority, reverse=True)
    selected: list[dict[str, Any]] = []
    seen_routes: set[tuple[str, str, str]] = set()
    for record in ranked:
        route = (
            str(record.get("source_role", "")),
            str(record.get("channel", "")),
            str(record.get("label", "")),
        )
        if route in seen_routes:
            continue
        selected.append(record)
        seen_routes.add(route)
        if len(selected) >= max_records:
            return selected
    for record in ranked:
        if record in selected:
            continue
        selected.append(record)
        if len(selected) >= max_records:
            break
    return selected


def event_group_priority(
    category: dict[str, Any],
    group: list[dict[str, Any]],
) -> tuple[int, int, int, int, int, int, str]:
    topics = {
        str(topic_id)
        for record in group
        for topic_id in record.get("watch_topic_ids", [])
        if str(topic_id)
    }
    titles = " ".join(core.record_public_title(record) for record in group)
    roles = {str(record.get("source_role", "")) for record in group}
    configured_topics = {
        str(topic.get("id"))
        for topic in category.get("watch_topics", [])
        if isinstance(topic, dict) and topic.get("id")
    }
    return (
        int(bool({"official_primary", "primary_or_official"} & roles)),
        int(bool(core.PUBLICATION_EVENT_RE.search(titles))),
        int(bool(core.MATERIAL_SIGNAL_RE.search(titles))),
        int(bool(re.search(r"\d+(?:\.\d+)?", titles))),
        sum(
            core.record_evidence_depth(core.record_public_title(record), record)
            == "body"
            for record in group
        ),
        len(topics & configured_topics),
        compact_text(titles, 300),
    )


def bounded_candidate_groups(
    category: dict[str, Any],
    event_groups: list[list[dict[str, Any]]],
    *,
    max_events: int | None = None,
) -> list[list[dict[str, Any]]]:
    """Preserve watch-topic breadth, then keep only the strongest events."""
    if max_events is None:
        topic_count = sum(
            isinstance(topic, dict) and bool(topic.get("id"))
            for topic in category.get("watch_topics", [])
        )
        max_events = min(
            MAX_EDITOR_EVENT_CANDIDATES_PER_CATEGORY,
            max(2, topic_count + EXTRA_EDITOR_EVENTS_PER_CATEGORY),
        )
    ranked = sorted(
        event_groups,
        key=lambda group: event_group_priority(category, group),
        reverse=True,
    )
    selected: list[list[dict[str, Any]]] = []
    for topic in category.get("watch_topics", []):
        if not isinstance(topic, dict) or not topic.get("id"):
            continue
        topic_id = str(topic["id"])
        group = next(
            (
                candidate
                for candidate in ranked
                if candidate not in selected
                and any(
                    topic_id in {
                        str(value) for value in record.get("watch_topic_ids", [])
                    }
                    for record in candidate
                )
            ),
            None,
        )
        if group is not None:
            selected.append(group)
        if len(selected) >= max_events:
            break
    for group in ranked:
        if len(selected) >= max_events:
            break
        if group not in selected:
            selected.append(group)
    return [bounded_event_records(group) for group in selected]


def publication_candidate_groups(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
    *,
    previous_updates: list[dict[str, Any]] | None = None,
) -> list[list[dict[str, Any]]]:
    """Deduplicate, suppress unchanged prior events, and bound model candidates."""
    selected = [
        record
        for _, record in core.editor_evidence_records(category, issue_date, records)
    ]
    exact_groups: dict[str, list[dict[str, Any]]] = {}
    for record in selected:
        key = core.record_cluster_key(record) or str(record.get("url", ""))
        exact_groups.setdefault(key, []).append(record)
    event_groups = list(exact_groups.values())
    grouped_events = len(event_groups)
    if previous_updates:
        event_groups = [
            group
            for group in event_groups
            if event_group_has_new_information(group, previous_updates, issue_date)
        ]
    novel_events = len(event_groups)
    preselected = bounded_candidate_groups(
        category,
        event_groups,
        max_events=MAX_SEMANTIC_DEDUP_EVENTS_PER_CATEGORY,
    )
    semantically_merged: list[list[dict[str, Any]]] = []
    for group in preselected:
        matching = next(
            (
                candidate
                for candidate in semantically_merged
                if any(
                    records_describe_same_information(record, existing)
                    for record in group
                    for existing in candidate
                )
            ),
            None,
        )
        if matching is None:
            semantically_merged.append(list(group))
        else:
            matching.extend(group)
    bounded = bounded_candidate_groups(category, semantically_merged)
    print(
        json.dumps(
            {
                "phase": "deterministic_candidate_filter",
                "category": str(category.get("label", "")),
                "evidence_records": len(selected),
                "grouped_events": grouped_events,
                "novel_events": novel_events,
                "semantic_dedup_pool": len(preselected),
                "model_candidates": len(bounded),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return bounded


def previous_category_updates(
    state_root: Path,
    issue_date: str,
    category_label: str,
    *,
    max_updates: int = 20,
) -> list[dict[str, Any]]:
    """Return bounded prior public updates as novelty context, never as Evidence."""
    issue_paths = sorted(
        (
            path
            for path in state_root.glob("20??-??-??/issue.json")
            if path.parent.name < issue_date
        ),
        reverse=True,
    )
    updates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for issue_path in issue_paths:
        try:
            issue = json.loads(issue_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cards = issue.get("cards")
        if not isinstance(cards, list):
            continue
        for card in cards:
            if (
                not isinstance(card, dict)
                or str(card.get("category", "")) != category_label
            ):
                continue
            title = compact_text(card.get("title", ""), 180)
            summary = compact_text(card.get("summary", ""), 700)
            signature = state.copy_signature(f"{title} {summary}")
            if not title or signature in seen:
                continue
            updates.append(
                {
                    "date": issue.get("issue_date"),
                    "title": title,
                    "summary": summary,
                }
            )
            seen.add(signature)
            if len(updates) >= max_updates:
                return updates
    return updates


def model_payload_bytes(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> int:
    return len(
        json.dumps(
            core.category_prompt(category, issue_date, records),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def representative_event_records(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
    *,
    max_payload_bytes: int = 20_000,
    selection_limit: int = 8,
) -> list[dict[str, Any]]:
    """Bound a duplicate-heavy event without shortening any selected source."""
    if len(records) == 1:
        if model_payload_bytes(category, issue_date, records) <= 30_000:
            return list(records)
        raise ValueError("one complete Evidence record exceeds the event request limit")
    if (
        model_payload_bytes(category, issue_date, records) <= max_payload_bytes
    ):
        return list(records)

    def rank(indexed: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        index, record = indexed
        title = core.record_public_title(record)
        body = str(record.get("excerpt") or record.get("evidence") or "")
        japanese = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", f"{title} {body}"))
        return (int(japanese >= 12), min(len(body), 8000), -index)

    selected: list[dict[str, Any]] = []
    for _, record in sorted(enumerate(records), key=rank, reverse=True):
        proposed = [*selected, record]
        if len(proposed) > selection_limit:
            continue
        if model_payload_bytes(category, issue_date, proposed) <= max_payload_bytes:
            selected = proposed
    if not selected:
        raise ValueError("no complete representative source fits the event request limit")
    return selected


def publication_record_chunks(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
    *,
    event_groups: list[list[dict[str, Any]]] | None = None,
    previous_updates: list[dict[str, Any]] | None = None,
    max_records: int = 10,
    max_payload_bytes: int = 25_000,
) -> list[list[dict[str, Any]]]:
    """Pack complete events without splitting one event across requests."""
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
        decorated_group = [
            {
                **record,
                "_editor_event_id": f"g{index:03d}",
                "_editor_previous_updates": matching_previous,
            }
            for record in group
        ]
        groups.append(
            representative_event_records(
                category,
                issue_date,
                decorated_group,
            )
        )
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for group in groups:
        group_payload_size = model_payload_bytes(category, issue_date, group)
        if current:
            combined = [*current, *group]
            combined_size = model_payload_bytes(category, issue_date, combined)
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
        raise ValueError("representative event payload still exceeds the chunk limit")
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def fit_model_payload(
    payload: dict[str, Any],
    *,
    max_bytes: int = 26_000,
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


def synchronize_card_source_links(card: dict[str, Any]) -> dict[str, Any]:
    """Expose every validated fact-source URL in the card's clickable sources."""
    detail = card.get("detail")
    if not isinstance(detail, dict):
        return card
    sources = detail.get("sources")
    basis = detail.get("summary_basis")
    if not isinstance(sources, list) or not isinstance(basis, dict):
        return card
    facts = [
        str(value)
        for value in basis.get("confirmed_facts", [])
        if isinstance(value, str) and value.strip()
    ]
    mappings = [
        mapping
        for mapping in basis.get("fact_sources", [])
        if isinstance(mapping, dict)
    ]
    aligned_mappings: list[dict[str, Any]] = []
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
            aligned_mappings.append({"fact": fact, "source_urls": urls})
    if len(aligned_mappings) == len(facts):
        basis["fact_sources"] = aligned_mappings
    by_url = {
        str(source.get("url")): source
        for source in sources
        if isinstance(source, dict) and source.get("url")
    }
    for mapping in basis.get("fact_sources", []):
        if not isinstance(mapping, dict):
            continue
        for value in mapping.get("source_urls", []):
            url = str(value)
            if not url.startswith(("http://", "https://")):
                continue
            by_url.setdefault(
                url,
                {
                    "label": core.reader_facing_source_label("", url),
                    "url": url,
                },
            )
    detail["sources"] = list(by_url.values())
    source_dates = [
        str(value)
        for value in basis.get("source_dates", [])
        if str(value).strip()
    ]
    card_source_date = str(card.get("source_published_date", "")).strip()
    basis["source_dates"] = list(
        dict.fromkeys(
            [*source_dates, *([card_source_date] if card_source_date else [])]
        )
    )
    return card


def cards_describe_same_information(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    if core.same_material_event(left.get("title"), right.get("title")):
        return True
    if state.text_overlap(str(left.get("title", "")), str(right.get("title", ""))) < 2:
        return False
    left_facts = (
        left.get("detail", {}).get("summary_basis", {}).get("confirmed_facts", [])
    )
    right_facts = (
        right.get("detail", {}).get("summary_basis", {}).get("confirmed_facts", [])
    )
    if not left_facts or not right_facts:
        return False
    matching = sum(
        any(state.materially_same_fact(str(fact), str(other)) for other in right_facts)
        for fact in left_facts
    )
    return matching >= min(len(left_facts), len(right_facts))


def merge_repeated_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    priority_rank = {"top": 0, "priority": 1, "standard": 2}
    for card in cards:
        card = synchronize_card_source_links(card)
        existing = next(
            (
                candidate
                for candidate in merged
                if candidate.get("category") == card.get("category")
                and cards_describe_same_information(candidate, card)
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


def checkpoint_cards(checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    """Return each previously validated card once, independent of old chunking."""
    chunks = checkpoint.get("chunks", {})
    if not isinstance(chunks, dict):
        return []
    unique: dict[str, dict[str, Any]] = {}
    for cards in chunks.values():
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict):
                continue
            fingerprint = hashlib.sha256(
                json.dumps(
                    card,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            unique.setdefault(fingerprint, card)
    return list(unique.values())


def event_checkpoint_key(
    category_label: str,
    event_records: list[dict[str, Any]],
) -> str:
    """Bind one decision to its complete Evidence and novelty context."""
    payload = {
        "category": category_label,
        "records": [
            {
                key: value
                for key, value in record.items()
                if key != "_editor_event_id"
            }
            for record in event_records
        ],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def reusable_event_decision(
    decisions: dict[str, Any],
    category_label: str,
    event_records: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Return a validated publish or exclusion decision for this exact event."""
    value = decisions.get(event_checkpoint_key(category_label, event_records))
    if not isinstance(value, list) or not all(isinstance(card, dict) for card in value):
        return None
    event_urls = {
        str(record.get("url"))
        for record in event_records
        if record.get("url")
    }
    for card in value:
        if str(card.get("category", "")) != category_label:
            return None
        detail = card.get("detail")
        if not isinstance(detail, dict):
            return None
        sources = detail.get("sources", [])
        if not isinstance(sources, list):
            return None
        source_urls = {
            str(source.get("url"))
            for source in sources
            if isinstance(source, dict) and source.get("url")
        }
        if not source_urls or not source_urls <= event_urls:
            return None
    return copy.deepcopy(value)


def reusable_cards_for_event(
    cards: list[dict[str, Any]],
    category_label: str,
    event_records: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Reuse validated output only when every cited source belongs to this event."""
    event_urls = {
        str(record.get("url"))
        for record in event_records
        if record.get("url")
    }
    matched: list[dict[str, Any]] = []
    for card in cards:
        if str(card.get("category", "")) != category_label:
            continue
        detail = card.get("detail")
        if not isinstance(detail, dict):
            continue
        sources = detail.get("sources", [])
        if not isinstance(sources, list):
            continue
        source_urls = {
            str(source.get("url"))
            for source in sources
            if isinstance(source, dict) and source.get("url")
        }
        if source_urls and source_urls == event_urls:
            matched.append(copy.deepcopy(card))
    return merge_repeated_cards(matched) if matched else None


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
    editor_coverage_gaps = core.remaining_editor_coverage_gaps(
        evidence,
        evidence_report,
    )
    if editor_coverage_gaps:
        fail(
            "Evidence has material watch topics without resolved source content: "
            + ", ".join(editor_coverage_gaps)
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
        "events": {},
    }
    try:
        stored_checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        stored_checkpoint = None
    model_config = models.load_config().get("extraction", {})
    compatible_contracts = {
        editor_contract_hash,
        *(
            str(value)
            for value in model_config.get("compatible_checkpoint_contracts", [])
            if isinstance(value, str)
        ),
    }
    if (
        isinstance(stored_checkpoint, dict)
        and stored_checkpoint.get("evidence_sha256") == evidence_hash
        and stored_checkpoint.get("editor_contract_sha256") in compatible_contracts
        and isinstance(stored_checkpoint.get("chunks"), dict)
    ):
        checkpoint = stored_checkpoint
        checkpoint["editor_contract_sha256"] = editor_contract_hash
        checkpoint.setdefault("events", {})
    if not isinstance(checkpoint.get("events"), dict):
        checkpoint["events"] = {}
    reusable_checkpoint_cards = checkpoint_cards(checkpoint)

    def save_checkpoint() -> None:
        write_json_atomic(checkpoint_path, checkpoint)

    unavailable_models: set[str] = set()
    editor_failures: list[str] = []

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
        fallback_on_validation: bool,
    ) -> tuple[Any | None, dict[str, Any], bool]:
        feedback: dict[str, Any] = {}
        last_result: Any | None = None
        successful_response_seen = False
        response_count = 0
        for model_name in model_chain:
            if response_count >= MAX_MODEL_RESPONSES_PER_SCOPE:
                break
            if model_name in unavailable_models:
                continue
            attempt_messages = messages
            max_attempts = min(
                validation_attempt_limit(successful_response_seen),
                MAX_MODEL_RESPONSES_PER_SCOPE - response_count,
            )
            request_failed = False
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
                    request_failed = True
                    if exc.rate_limited:
                        unavailable_models.add(model_name)
                    print(
                        json.dumps(
                            {
                                **log_context,
                                "phase": "model_request_failed",
                                "model": model_name,
                            "status_code": exc.status_code,
                            "rate_limited": exc.rate_limited,
                            "schema_invalid": exc.schema_invalid,
                            "error": str(exc),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    if exc.schema_invalid:
                        return None, feedback, False
                    if exc.rate_limited or model_name != model_chain[-1]:
                        break
                    raise
                successful_response_seen = True
                response_count += 1
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
            if not request_failed and not fallback_on_validation:
                return last_result, feedback, False
        return last_result, feedback, False

    def cards_from_raw(
        raw: dict[str, Any],
        category: dict[str, Any],
        label: str,
        records: list[dict[str, Any]],
    ) -> tuple[
        list[dict[str, Any]],
        int,
        bool,
        dict[str, Any],
        dict[str, list[dict[str, Any]]],
    ]:
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
        cards_by_event: dict[str, list[dict[str, Any]]] = {}
        failed_event_ids: set[str] = set()
        failed = 0
        for item in normalized["items"]:
            event_id = str(item.get("event_id", ""))
            try:
                card = item_card(
                    label,
                    str(configs[label]["section_id"]),
                    item,
                    issue_date,
                )
                cards.append(card)
                cards_by_event.setdefault(event_id, []).append(card)
            except UnpublishableItem as exc:
                failed += 1
                failed_event_ids.add(event_id)
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
        invalid_event_ids = {
            *normalized["missing_event_ids"],
            *normalized["conflicting_event_ids"],
            *failed_event_ids,
            *(
                str(rejected.get("event_id", ""))
                for rejected in normalized["rejected_items"]
                if isinstance(rejected, dict)
            ),
        }
        event_decisions = (
            {
                event_id: copy.deepcopy(cards_by_event.get(event_id, []))
                for event_id in normalized["expected_event_ids"]
                if event_id not in invalid_event_ids
            }
            if event_response_accepted
            else {}
        )
        return cards, failed, accepted, feedback, event_decisions

    def review_category(category: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        label = str(category["label"])
        entry = categories[label]
        if not isinstance(entry, dict) or not isinstance(entry.get("records"), list):
            fail(f"Evidence records are missing: {label}")
        records = [record for record in entry["records"] if isinstance(record, dict)]
        previous_updates = previous_category_updates(state_root, issue_date, label)
        selected_event_groups = publication_candidate_groups(
            category,
            issue_date,
            records,
            previous_updates=previous_updates,
        )
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
            records_by_event: dict[str, list[dict[str, Any]]] = {}
            for record in chunk_records:
                records_by_event.setdefault(
                    str(record.get("_editor_event_id", "")), []
                ).append(record)
            reused_chunk_cards: list[dict[str, Any]] = []
            pending_chunk_records: list[dict[str, Any]] = []
            reused_events = 0
            for event_records in records_by_event.values():
                event_decision = reusable_event_decision(
                    checkpoint["events"],
                    label,
                    event_records,
                )
                if event_decision is not None:
                    reused_chunk_cards.extend(event_decision)
                    reused_events += 1
                    continue
                event_cards = reusable_cards_for_event(
                    reusable_checkpoint_cards,
                    label,
                    event_records,
                )
                if event_cards is None:
                    pending_chunk_records.extend(event_records)
                    continue
                reused_chunk_cards.extend(event_cards)
                reused_events += 1
            if reused_events:
                print(
                    json.dumps(
                        {
                            "phase": "editor_event_checkpoint_reused",
                            "category": label,
                            "chunk": chunk_index,
                            "chunks": len(chunks),
                            "events": reused_events,
                            "cards": len(reused_chunk_cards),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

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
                    max_output_tokens=summary_output_budget(
                        len(request_records_value)
                    ),
                    validate=validate_summary,
                    correction=lambda value: (
                        "Return the entire corrected JSON for the supplied events. Apply "
                        "only the fixes named by validation. For title_copy, use a concise "
                        "concrete reader title without a colon, pipe, brackets, publisher "
                        "wording, or vague phrases such as latest developments. For "
                        "English Evidence, translate every title and summary point into "
                        "natural Japanese; never return English reader text. Treat a "
                        "company overview, profile, index, or navigation page as "
                        "background_or_navigation, not a published update. For "
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
                    fallback_on_validation=not quality_required,
                )

            chunk_cards = reused_chunk_cards
            work_queue: list[tuple[list[dict[str, Any]], str]] = (
                [(pending_chunk_records, "")]
                if pending_chunk_records
                else []
            )
            failed_scope = False
            recovery_round = 0
            while work_queue:
                pending_records, suffix = work_queue.pop(0)
                selected_result, feedback, accepted = request_records(
                    pending_records,
                    suffix,
                )
                if selected_result is None:
                    records_by_event: dict[str, list[dict[str, Any]]] = {}
                    for record in pending_records:
                        records_by_event.setdefault(
                            str(record.get("_editor_event_id", "")), []
                        ).append(record)
                    if len(records_by_event) > 1:
                        work_queue = [
                            (event_records, f" event-{event_id}")
                            for event_id, event_records in records_by_event.items()
                        ] + work_queue
                        continue
                    failed_scope = True
                    break
                event_records_by_id: dict[str, list[dict[str, Any]]] = {}
                for record in pending_records:
                    event_records_by_id.setdefault(
                        str(record.get("_editor_event_id", "")), []
                    ).append(record)
                stored_event_count = 0
                for event_id, event_cards in selected_result[4].items():
                    event_records = event_records_by_id.get(event_id)
                    if event_records is None:
                        continue
                    checkpoint["events"][
                        event_checkpoint_key(label, event_records)
                    ] = copy.deepcopy(event_cards)
                    stored_event_count += 1
                if stored_event_count:
                    save_checkpoint()
                    print(
                        json.dumps(
                            {
                                "phase": "editor_event_checkpoint_saved",
                                "category": label,
                                "chunk": chunk_index,
                                "chunks": len(chunks),
                                "events": stored_event_count,
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                if accepted:
                    chunk_cards.extend(selected_result[0])
                    continue
                missing_ids = set(feedback.get("missing_event_ids", []))
                next_pending = [
                    record
                    for record in pending_records
                    if str(record.get("_editor_event_id", "")) in missing_ids
                ]
                if next_pending and len(next_pending) < len(pending_records):
                    chunk_cards.extend(selected_result[0])
                    recovery_round += 1
                    work_queue.insert(
                        0,
                        (next_pending, f" recovery-{recovery_round}"),
                    )
                    continue
                records_by_event: dict[str, list[dict[str, Any]]] = {}
                for record in pending_records:
                    records_by_event.setdefault(
                        str(record.get("_editor_event_id", "")), []
                    ).append(record)
                if len(records_by_event) > 1:
                    work_queue = [
                        (event_records, f" event-{event_id}")
                        for event_id, event_records in records_by_event.items()
                    ] + work_queue
                    continue
                failed_scope = True
                break
            if failed_scope:
                editor_failures.append(
                    f"{label} chunk {chunk_index}/{len(chunks)}"
                )
                continue
            chunk_cards = merge_repeated_cards(chunk_cards)
            checkpoint["chunks"][checkpoint_key] = chunk_cards
            save_checkpoint()
            category_cards.extend(chunk_cards)
        return label, merge_repeated_cards(category_cards)

    cards_by_category: dict[str, list[dict[str, Any]]] = {}
    for category in contracts:
        label, category_cards = review_category(category)
        cards_by_category[label] = category_cards
    if editor_failures:
        displayed = "; ".join(editor_failures[:12])
        remaining = len(editor_failures) - 12
        if remaining > 0:
            displayed += f"; and {remaining} more"
        fail(
            "Editor could not produce a valid decision for every event: "
            + displayed
        )
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
    if sanitize_editor_title(
        "8歳の候補者が選出された。 今後の活躍に期待。 夢は続く。"
    ) != "8歳の候補者が選出された":
        fail("Editor did not remove sentence padding from a model title")
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
    if validation_attempt_limit(False) != 2 or validation_attempt_limit(True) != 1:
        fail("Editor did not preserve one correction for the first responding model")
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
    if novelty_numbers("2099年1月2日更新、利用上限は2倍") != {"2"}:
        fail("Editor novelty comparison treated a date stamp as new information")
    if summary_output_budget(1) != 1_600 or summary_output_budget(6) != 4_000:
        fail("Editor summary output budget is outside its bounded range")
    previous_openai_update = [
        {
            "date": "2099-01-01",
            "title": "OpenAIが新モデルを公開",
            "summary": "OpenAIは新モデルを公開し、企業向け制御を追加した。",
        }
    ]
    if publication_candidate_groups(
        review_category,
        "2099-01-02",
        [review_records[0]],
        previous_updates=previous_openai_update,
    ):
        fail("Editor sent an unchanged prior update back to the model")
    novel_limit_update = {
        **review_records[0],
        "url": "https://openai.com/release-limit-update",
        "title": "OpenAIが新モデルを更新、利用上限を2倍に拡大",
        "excerpt": "OpenAIは新モデルの利用上限を2倍に拡大した。",
    }
    if not publication_candidate_groups(
        review_category,
        "2099-01-02",
        [novel_limit_update],
        previous_updates=previous_openai_update,
    ):
        fail("Editor removed a prior event that contained a new material number")
    duplicate_sources = [
        {
            **review_records[0],
            "url": f"https://example.com/openai-release-{index}",
            "label": f"Release Source {index}",
        }
        for index in range(5)
    ]
    if len(bounded_event_records(duplicate_sources)) != MAX_EDITOR_RECORDS_PER_EVENT:
        fail("Editor retained too many duplicate source records for one event")
    budget_groups = [
        [
            {
                **review_records[0],
                "url": f"https://example.com/openai-event-{index}",
                "label": f"Source {index}",
                "title": f"OpenAIが製品機能{index}を公開",
                "excerpt": f"OpenAIは製品機能{index}を公開し、対象条件を発表した。",
                "watch_topic_ids": [
                    "product_release" if index % 2 == 0 else "ipo_financing"
                ],
            }
        ]
        for index in range(20)
    ]
    if len(bounded_candidate_groups(review_category, budget_groups)) != 3:
        fail("Editor dynamic candidate budget did not stay at watch topics plus one")
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
    oversized_event = [
        {
            **review_records[0],
            "url": f"https://example.com/large-duplicate-{index}",
            "title": (
                "OpenAIが新モデルを公開"
                if index == 0
                else f"OpenAI launches the model with enterprise feature {index}"
            ),
            "excerpt": (
                "OpenAIは新モデルを公開し、企業向け制御を追加した。"
                + " ".join(f"固有情報{number}" for number in range(500))
                if index == 0
                else " ".join(
                    f"source{index}_detail{number}" for number in range(500)
                )
            ),
        }
        for index in range(12)
    ]
    oversized_chunks = publication_record_chunks(
        review_category,
        "2099-01-02",
        oversized_event,
        event_groups=[oversized_event],
    )
    if len(oversized_chunks) != 1:
        fail("A duplicate-heavy event was split across model requests")
    oversized_payload = core.category_prompt(
        review_category,
        "2099-01-02",
        oversized_chunks[0],
    )
    if (
        len(oversized_payload["events"]) != 1
        or model_payload_bytes(
            review_category,
            "2099-01-02",
            oversized_chunks[0],
        )
        > 20_000
        or not any("新モデル" in str(record.get("title")) for record in oversized_chunks[0])
    ):
        fail("Representative event selection lost its event boundary or strongest source")
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
    stale_source_card = copy.deepcopy(card)
    relay_url = "https://news.google.com/rss/articles/example"
    stale_source_card["detail"]["summary_basis"]["fact_sources"][0][
        "source_urls"
    ] = [relay_url]
    stale_source_card["detail"]["summary_basis"]["source_dates"] = []
    synchronized_card = merge_repeated_cards([stale_source_card])[0]
    if relay_url not in {
        source.get("url")
        for source in synchronized_card["detail"]["sources"]
        if isinstance(source, dict)
    }:
        fail("Editor did not expose a validated relay URL from an old checkpoint")
    if synchronized_card["source_published_date"] not in synchronized_card[
        "detail"
    ]["summary_basis"]["source_dates"]:
        fail("Editor did not restore a card source date in an old checkpoint")
    extra_mapping_card = copy.deepcopy(card)
    extra_mapping_card["detail"]["summary_basis"]["fact_sources"].append(
        copy.deepcopy(
            extra_mapping_card["detail"]["summary_basis"]["fact_sources"][0]
        )
    )
    aligned_card = merge_repeated_cards([extra_mapping_card])[0]
    aligned_basis = aligned_card["detail"]["summary_basis"]
    if len(aligned_basis["fact_sources"]) != len(aligned_basis["confirmed_facts"]):
        fail("Editor retained duplicate fact-source mappings from an old checkpoint")
    cached_cards = checkpoint_cards(
        {"chunks": {"old-a": [card], "old-b": [copy.deepcopy(card)]}}
    )
    if len(cached_cards) != 1:
        fail("Editor event checkpoint did not deduplicate validated cards")
    matching_event = [
        {
            "title": card["title"],
            "url": "https://openai.com/example",
            "_editor_event_id": "g001",
        }
    ]
    exclusion_decisions = {
        event_checkpoint_key("OpenAI", matching_event): []
    }
    if reusable_event_decision(
        exclusion_decisions,
        "OpenAI",
        [{**matching_event[0], "_editor_event_id": "g099"}],
    ) != []:
        fail("Editor did not reuse an exact validated exclusion decision")
    if reusable_event_decision(
        exclusion_decisions,
        "OpenAI",
        [{**matching_event[0], "title": "OpenAIが別製品を公開"}],
    ) is not None:
        fail("Editor reused an exclusion after its Evidence changed")
    publish_decisions = {
        event_checkpoint_key("OpenAI", matching_event): [card]
    }
    if reusable_event_decision(
        publish_decisions,
        "OpenAI",
        matching_event,
    ) != [card]:
        fail("Editor did not reuse an exact validated publish decision")
    if reusable_cards_for_event(cached_cards, "OpenAI", matching_event) != [card]:
        fail("Editor did not reuse a validated card for its exact source event")
    if reusable_cards_for_event(
        cached_cards,
        "OpenAI",
        [{**matching_event[0], "url": "https://example.com/unrelated"}],
    ) is not None:
        fail("Editor reused a validated card for an unrelated source event")
    if reusable_cards_for_event(
        cached_cards,
        "OpenAI",
        [
            *matching_event,
            {
                **matching_event[0],
                "url": "https://example.com/additional-source",
            },
        ],
    ) is not None:
        fail("Editor reused a card after its source event expanded")
    mixed_source_card = copy.deepcopy(card)
    mixed_source_card["detail"]["sources"].append(
        {"label": "Unrelated", "url": "https://example.com/unrelated"}
    )
    if reusable_cards_for_event(
        [mixed_source_card], "OpenAI", matching_event
    ) is not None:
        fail("Editor reused a card whose sources cross an event boundary")
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
