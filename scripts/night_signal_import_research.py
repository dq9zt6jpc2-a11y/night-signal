#!/usr/bin/env python3
"""Import a reviewed research bundle into the canonical NIGHT SIGNAL state.

This is the API-independent recovery path. It accepts current research gathered
by Codex or another reviewed process, then expands it into the same observation,
candidate, decision, card, and manifest contracts used by the Responses path.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import night_signal_state as state
import night_signal_synthesize as synthesize


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
TOPIC_VALUE_CLASS_MAP = {
    "capital_market_shift": "market_or_financial_impact",
    "competitive_result": "event_result_or_outcome",
    "macro_policy_data": "market_or_financial_impact",
    "roster_change": "operational_status_change",
}
SUMMARY_LABEL_RE = re.compile(r"(?:変更点|重要性|確認事実|未確定点)\s*[:：]")
GENERIC_IMPORTANCE_RE = re.compile(
    r"重要更新として一覧に残す|変化を広めに把握|関連テーマは|出典日付は"
)
TRAILING_DOMAIN_RE = re.compile(r"\s*[-–—|｜]\s*[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:/[^\s。、]*)?\s*$")
EMPTY_JA_QUOTE_RE = re.compile(r"[「『]\s*[」』]")
DEFAULT_LIMITS_SENTENCE = "影響範囲、対象範囲、追加条件、続報の有無は引き続き確認が必要。"
TOPIC_CONTEXT_SENTENCES = {
    "technical_or_product_shift": "性能、提供範囲、既存製品との関係は、{category}の技術選択と競争力を判断する材料になる。",
    "market_or_financial_impact": "規模、条件、資金使途と市場反応は、{category}の投資余力と評価を判断する材料になる。",
    "risk_or_safety_signal": "対象範囲、対策の実効性と残る制約は、{category}の安全性と運用継続性を判断する材料になる。",
    "decision_or_policy": "対象範囲、実施時期と関係者の役割は、{category}の事業計画への影響を判断する材料になる。",
    "event_result_or_outcome": "今回の結果と次工程への影響は、{category}の計画進捗と今後の見通しを判断する材料になる。",
    "operational_status_change": "対象範囲、実施時期と継続性は、{category}の運営状況への影響を判断する材料になる。",
}


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL RESEARCH IMPORT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def topic_value_class(value: Any) -> str:
    normalized = str(value)
    return TOPIC_VALUE_CLASS_MAP.get(normalized, normalized)


def compact_text(value: Any, limit: int = 1600) -> str:
    return " ".join(str(value).split())[:limit]


def useful_fact(fact: Any, category: str) -> bool:
    text = compact_text(fact, 500)
    if len(text) < 18:
        return False
    if GENERIC_IMPORTANCE_RE.search(text):
        return False
    if category and f"{category}の重要更新として確認" in text:
        return False
    return True


def useful_importance(value: Any) -> bool:
    text = compact_text(value, 700)
    return bool(text) and not GENERIC_IMPORTANCE_RE.search(text)


def scrub_public_title(value: Any) -> str:
    title = compact_text(value, 180)
    title = re.sub(r"https?://\S+", "", title)
    title = state.DOMAIN_RE.sub("", title)
    title = EMPTY_JA_QUOTE_RE.sub("", title)
    for _ in range(3):
        cleaned = state.PUBLISHER_SUFFIX_RE.sub("", title)
        cleaned = TRAILING_DOMAIN_RE.sub("", cleaned)
        cleaned = EMPTY_JA_QUOTE_RE.sub("", cleaned)
        cleaned = cleaned.strip(" -–—|｜")
        if cleaned == title:
            break
        title = cleaned
    return compact_text(title.strip())


def scrub_public_summary(value: Any) -> str:
    text = compact_text(value, 2600)
    text = re.sub(r"https?://\S+", "", text)
    text = state.DOMAIN_RE.sub("", text)
    sentences = []
    for sentence in re.split(r"(?<=[。！？!?])", text):
        cleaned = state.PUBLISHER_SUFFIX_RE.sub("", sentence)
        cleaned = TRAILING_DOMAIN_RE.sub("", cleaned).strip(" -–—|｜")
        if cleaned:
            sentences.append(cleaned)
    return compact_text(" ".join(sentences), 2600)


def public_card_title(item: dict[str, Any]) -> str:
    candidates = [
        item.get("title", ""),
        re.split(r"(?<=[。！？!?])", compact_text(item.get("summary", ""), 180))[0],
        item.get("what_changed", ""),
        item.get("why_it_matters", ""),
        *[
            fact
            for fact in item.get("confirmed_facts", [])
            if useful_fact(fact, str(item.get("category", "")))
        ],
    ]
    first_cleaned = ""
    for candidate in candidates:
        cleaned = scrub_public_title(candidate)
        if cleaned and not first_cleaned:
            first_cleaned = cleaned
        if cleaned and not state.public_render_copy_violations(cleaned, kind="title"):
            return cleaned
    return first_cleaned


def summary_is_reader_facing(title: str, summary: str) -> bool:
    if state.public_render_copy_violations(summary, kind="summary"):
        return False
    return not state.reader_summary_violations(title, summary)


def public_focus_phrase(title: str, category: str) -> str:
    focus = scrub_public_title(title)
    if category:
        focus = re.sub(rf"^{re.escape(category)}[、,:：\s]+", "", focus).strip()
    return focus.strip("、。 ") or category or "この更新"


def sentence_from(value: Any, limit: int = 520) -> str:
    text = compact_text(scrub_public_summary(value), limit).rstrip("。")
    if not text:
        return ""
    return f"{text}。"


def reader_summary_from_parts(title: str, parts: list[Any], *, limit: int = 900) -> str:
    seen: set[str] = set()
    kept: list[str] = []
    for part in parts:
        sentence = sentence_from(part)
        if not sentence:
            continue
        key = state.copy_signature(sentence)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
        candidate = compact_text(" ".join(kept), limit)
        if len(kept) >= 2 and summary_is_reader_facing(title, candidate):
            return candidate
    candidate = compact_text(" ".join(kept), limit)
    if candidate and summary_is_reader_facing(title, candidate):
        return candidate
    return ""


def item_importance(item: dict[str, Any], category: str) -> str:
    importance = scrub_public_summary(item.get("why_it_matters", ""))
    if (
        useful_importance(importance)
        and not state.public_render_copy_violations(importance, kind="summary")
    ):
        return importance
    value_class = topic_value_class(item.get("topic_value_class", "operational_status_change"))
    template = TOPIC_CONTEXT_SENTENCES.get(
        value_class,
        TOPIC_CONTEXT_SENTENCES["operational_status_change"],
    )
    return template.format(category=category or "対象分野")


def public_card_summary(item: dict[str, Any], title: str, category: str) -> str:
    original = compact_text(scrub_public_summary(item.get("summary", "")), 900)
    if original and summary_is_reader_facing(title, original):
        return original

    facts = [
        compact_text(scrub_public_summary(fact), 320)
        for fact in item.get("confirmed_facts", [])
        if useful_fact(fact, category)
    ][:3]
    what_changed = compact_text(scrub_public_summary(item.get("what_changed", "")), 500)
    limits = compact_text(scrub_public_summary(item.get("limits_or_unknowns", "")), 500)
    importance = item_importance(item, category)
    event_parts = [part for part in (what_changed, *facts, original) if part]
    lead = event_parts[0] if event_parts else public_focus_phrase(title, category)
    summary = reader_summary_from_parts(
        title,
        [lead, importance, *event_parts[1:], limits or DEFAULT_LIMITS_SENTENCE],
        limit=900,
    )
    if summary:
        return summary

    summary = reader_summary_from_parts(
        title,
        [public_focus_phrase(title, category), importance, limits or DEFAULT_LIMITS_SENTENCE],
        limit=900,
    )
    if summary:
        return summary
    fail(f"unable to construct a reader-facing card summary: {title}")


def canonical_detail_summary(
    category: str,
    item: dict[str, Any],
    title: str,
    card_summary: str,
) -> str:
    existing = scrub_public_summary(item.get("detail_summary", ""))
    if (
        len(existing) >= 280
        and not SUMMARY_LABEL_RE.search(existing)
        and not state.public_render_copy_violations(existing, kind="summary")
        and summary_is_reader_facing(title, existing)
        and state.text_overlap(card_summary, existing) >= 2
    ):
        return existing

    optional_parts: list[Any] = [
        fact
        for fact in item.get("confirmed_facts", [])
        if useful_fact(fact, category)
        and state.title_repetition_score(title, scrub_public_summary(fact)) < 0.82
    ]
    optional_parts.append(item_importance(item, category))
    optional_parts.append(scrub_public_summary(item.get("limits_or_unknowns", "")))
    optional_parts.append(DEFAULT_LIMITS_SENTENCE)

    seen: set[str] = set()
    sentences: list[str] = []
    for part in re.split(r"(?<=[。！？!?])", card_summary):
        sentence = sentence_from(part, 700)
        key = state.copy_signature(sentence)
        if not sentence or not key or key in seen:
            continue
        seen.add(key)
        sentences.append(sentence)

    for part in optional_parts:
        sentence = sentence_from(part, 700)
        key = state.copy_signature(sentence)
        if not sentence or not key or key in seen:
            continue
        candidate = compact_text(" ".join([*sentences, sentence]), 2600)
        if not summary_is_reader_facing(title, candidate):
            continue
        seen.add(key)
        sentences.append(sentence)

    composed = compact_text(" ".join(sentences), 2600)
    if (
        composed
        and summary_is_reader_facing(title, composed)
        and state.text_overlap(card_summary, composed) >= 2
    ):
        return composed
    fail(f"unable to construct a card-bound detail summary: {title}")


def public_item_copy(category: str, item: dict[str, Any]) -> tuple[str, str]:
    title = public_card_title(item)
    summary = public_card_summary(item, title, category)
    return title, summary


def read_bundle(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing research bundle: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid research bundle JSON: {exc}")
    if not isinstance(value, dict):
        fail("research bundle must be an object")
    return value


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def category_config() -> dict[str, dict[str, Any]]:
    contract = state.read_json(state.CONFIG_PATH)
    return {
        str(category["label"]): category
        for category in contract.get("categories", [])
        if isinstance(category, dict)
    }


def validate_source_check(
    label: str,
    index: int,
    check: Any,
    *,
    issue_date: str,
    topic_keys: set[tuple[str, str]],
) -> dict[str, Any]:
    if not isinstance(check, dict):
        fail(f"{label} source_checks[{index}] must be an object")
    for key in (
        "source_role",
        "channel",
        "label",
        "url",
        "slot_state",
        "evidence_summary",
        "checked_at_jst",
        "verification_method",
    ):
        if not isinstance(check.get(key), str) or not check[key].strip():
            fail(f"{label} source_checks[{index}] missing {key}")
    topics = check.get("watch_topic_ids")
    if not isinstance(topics, list) or not topics:
        fail(f"{label} source_checks[{index}] needs watch_topic_ids")
    unknown = [
        str(topic_id)
        for topic_id in topics
        if (label, str(topic_id)) not in topic_keys
    ]
    if unknown:
        fail(f"{label} source_checks[{index}] uses unknown watch topics: {unknown}")
    if not str(check["url"]).startswith(("http://", "https://")):
        fail(f"{label} source_checks[{index}] url must be absolute")
    if not str(check["checked_at_jst"]).startswith(issue_date):
        fail(f"{label} source_checks[{index}] checked_at_jst must be on the issue date")
    if check["slot_state"] not in {"observed_live", "source_unavailable"}:
        fail(f"{label} source_checks[{index}] slot_state must be observed_live or source_unavailable")
    expected_method = (
        "unavailable"
        if check["slot_state"] == "source_unavailable"
        else "reviewed_live_web"
    )
    if check["verification_method"] != expected_method:
        fail(
            f"{label} source_checks[{index}] {check['slot_state']} "
            f"must use {expected_method}"
        )
    if check["slot_state"] == "source_unavailable" and len(str(check["evidence_summary"]).strip()) < 20:
        fail(f"{label} source_checks[{index}] unavailable reason is too short")
    published_date = check.get("published_date")
    if published_date is not None and (
        not isinstance(published_date, str) or len(published_date) != 10
    ):
        fail(f"{label} source_checks[{index}] published_date must be YYYY-MM-DD or null")
    return {
        **check,
        "watch_topic_ids": [str(topic_id) for topic_id in topics],
    }


def validate_bundle(bundle: dict[str, Any], issue_date: str) -> dict[str, list[dict[str, Any]]]:
    if bundle.get("issue_date") != issue_date:
        fail(f"bundle issue_date mismatch: {bundle.get('issue_date')} != {issue_date}")
    checked_at = bundle.get("checked_at_jst")
    if not isinstance(checked_at, str) or not checked_at.startswith(issue_date):
        fail("checked_at_jst must be an ISO timestamp on the issue date")
    categories = bundle.get("categories")
    if not isinstance(categories, dict):
        fail("bundle categories must be an object")
    configured = category_config()
    if set(categories) != set(configured):
        fail(
            "bundle category mismatch: "
            f"missing={sorted(set(configured) - set(categories))}, "
            f"extra={sorted(set(categories) - set(configured))}"
        )
    normalized: dict[str, list[dict[str, Any]]] = {}
    topic_keys = {
        (str(item["category"]), str(item["watch_topic_id"]))
        for item in state.build_frontier(state.read_json(state.CONFIG_PATH))
    }
    seen_titles: set[str] = set()
    for label, entry in categories.items():
        if not isinstance(entry, dict):
            fail(f"{label} bundle entry must be an object")
        items = entry.get("items")
        signals = entry.get("signals")
        source_checks = entry.get("source_checks")
        no_change_summary = entry.get("no_change_summary")
        if not isinstance(items, list):
            fail(f"{label} items must be a list")
        if not isinstance(signals, list):
            fail(f"{label} signals must be a list")
        if not isinstance(source_checks, list) or not source_checks:
            fail(f"{label} source_checks must be a non-empty list")
        if not isinstance(no_change_summary, str) or len(no_change_summary.strip()) < 20:
            fail(f"{label} no_change_summary is too short")
        normalized[label] = []
        entry["source_checks"] = [
            validate_source_check(
                label,
                index,
                check,
                issue_date=issue_date,
                topic_keys=topic_keys,
            )
            for index, check in enumerate(source_checks, start=1)
        ]
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                fail(f"{label} items[{index}] must be an object")
            required_strings = [
                "watch_topic_id",
                "title",
                "summary",
                "source_published_date",
                "topic_value_class",
                "priority_class",
                "slug",
                "detail_summary",
                "what_changed",
                "why_it_matters",
                "limits_or_unknowns",
            ]
            for key in required_strings:
                if not isinstance(item.get(key), str) or not item[key].strip():
                    fail(f"{label} items[{index}] missing {key}")
            if (label, str(item["watch_topic_id"])) not in topic_keys:
                fail(f"{label} items[{index}] uses unknown watch topic")
            if item["title"] in seen_titles:
                fail(f"duplicate item title: {item['title']}")
            seen_titles.add(item["title"])
            facts = item.get("confirmed_facts")
            sources = item.get("sources")
            if not isinstance(facts, list) or len(facts) < 3:
                fail(f"{label} items[{index}] needs at least three confirmed facts")
            if not isinstance(sources, list) or not sources or len(sources) > 3:
                fail(f"{label} items[{index}] needs one to three sources")
            for source in sources:
                if (
                    not isinstance(source, dict)
                    or not isinstance(source.get("label"), str)
                    or not isinstance(source.get("url"), str)
                    or not source["url"].startswith(("http://", "https://"))
                ):
                    fail(f"{label} items[{index}] contains invalid source")
            normalized[label].append(item)
        for index, signal in enumerate(signals, start=1):
            if not isinstance(signal, dict):
                fail(f"{label} signals[{index}] must be an object")
            for key in (
                "watch_topic_id",
                "title",
                "summary",
                "source_published_date",
                "source_url",
                "change_class",
                "rejection_reason_class",
                "rejection_reason",
            ):
                if not isinstance(signal.get(key), str) or not signal[key].strip():
                    fail(f"{label} signals[{index}] missing {key}")
            if (label, str(signal["watch_topic_id"])) not in topic_keys:
                fail(f"{label} signals[{index}] uses unknown watch topic")
            if not str(signal["source_url"]).startswith(("http://", "https://")):
                fail(f"{label} signals[{index}] source_url must be absolute")
            if signal["title"] in seen_titles:
                fail(f"duplicate signal title: {signal['title']}")
            seen_titles.add(signal["title"])
        verified_checks = {
            (str(check["url"]), str(topic_id))
            for check in entry["source_checks"]
            if check["slot_state"] == "observed_live"
            for topic_id in check["watch_topic_ids"]
        }
        for item in items:
            for source in item["sources"]:
                key = (str(source["url"]), str(item["watch_topic_id"]))
                if key not in verified_checks:
                    fail(
                        f"{label} item source lacks an explicit observed source_check: "
                        f"{source['url']}"
                    )
        for signal in signals:
            key = (str(signal["source_url"]), str(signal["watch_topic_id"]))
            if key not in verified_checks:
                fail(
                    f"{label} signal source lacks an explicit observed source_check: "
                    f"{signal['source_url']}"
                )
    return normalized


def matching_items(
    items: list[dict[str, Any]],
    topic_id: str,
    source_role: str,
    channel: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item["watch_topic_id"] == topic_id
        and item.get("observation_source_role", "primary_or_official")
        == source_role
        and item.get("observation_channel", "web") == channel
    ]


def matching_signals(
    signals: list[dict[str, Any]],
    topic_id: str,
    source_role: str,
    channel: str,
) -> list[dict[str, Any]]:
    return [
        signal
        for signal in signals
        if signal["watch_topic_id"] == topic_id
        and signal.get(
            "observation_source_role",
            "independent_media_or_data",
        )
        == source_role
        and signal.get("observation_channel", "web") == channel
    ]


def source_results(
    task: dict[str, Any],
    source_checks: list[dict[str, Any]],
    topic_id: str,
) -> list[dict[str, Any]]:
    matching = [
        check
        for check in source_checks
        if topic_id in check["watch_topic_ids"]
        and check["source_role"] == task["source_role"]
        and (
            check["channel"] == task["channel"]
            or (
                task["source_role"] == "social_or_video_signal"
                and task["channel"] == "sns_x"
                and check["channel"] in {"sns_x", "instagram", "facebook"}
            )
        )
    ]
    by_url = {str(check["url"]): check for check in matching}
    missing_seed_urls = [
        str(target["url"])
        for target in task.get("source_targets", [])
        if isinstance(target, dict) and str(target["url"]) not in by_url
    ]
    if missing_seed_urls:
        fail(
            f"{task.get('slot_id')} / {topic_id} has seed targets without explicit checks: "
            + ", ".join(missing_seed_urls[:6])
        )
    return [
        {
            "label": str(check["label"]),
            "url": str(check["url"]),
            "channel": str(check["channel"]),
            "slot_state": str(check["slot_state"]),
            "published_date": check.get("published_date"),
            "evidence_summary": str(check["evidence_summary"]),
            "checked_at_jst": str(check["checked_at_jst"]),
            "verification_method": str(check["verification_method"]),
        }
        for check in matching
    ]


def build_observations(
    bundle: dict[str, Any],
    items_by_category: dict[str, list[dict[str, Any]]],
    plan: dict[str, Any],
) -> list[dict[str, Any]]:
    issue_date = str(bundle["issue_date"])
    checked_at = str(bundle["checked_at_jst"])
    observations: list[dict[str, Any]] = []
    used_item_titles: set[str] = set()
    used_signal_titles: set[str] = set()
    for task in plan.get("tasks", []):
        if not isinstance(task, dict):
            continue
        category = str(task["category"])
        items = items_by_category[category]
        signals = [
            signal
            for signal in bundle["categories"][category]["signals"]
            if isinstance(signal, dict)
        ]
        source_checks = [
            check
            for check in bundle["categories"][category]["source_checks"]
            if isinstance(check, dict)
        ]
        for topic in task.get("watch_topics", []):
            topic_id = str(topic["watch_topic_id"])
            targets = source_results(task, source_checks, topic_id)
            if not targets:
                fail(f"{task.get('slot_id')} / {topic_id} has no explicit source checks")
            route_items = matching_items(
                items,
                topic_id,
                str(task["source_role"]),
                str(task["channel"]),
            )
            new_route_items = [
                item
                for item in route_items
                if item["title"] not in used_item_titles
            ]
            route_signals = matching_signals(
                signals,
                topic_id,
                str(task["source_role"]),
                str(task["channel"]),
            )
            new_route_signals = [
                signal
                for signal in route_signals
                if signal["title"] not in used_signal_titles
            ]
            if new_route_items or new_route_signals:
                primary_source_url = (
                    str(new_route_items[0]["sources"][0]["url"])
                    if new_route_items
                    else str(new_route_signals[0]["source_url"])
                )
                claim_atoms = [
                    {
                        "claim_type": str(item.get("claim_type", "announcement")),
                        "claim": str(fact),
                        "source_state": str(item.get("source_state", "confirmed_update")),
                    }
                    for item in new_route_items
                    for fact in item["confirmed_facts"]
                ]
                claim_atoms.extend(
                    {
                        "claim_type": str(
                            signal.get("claim_type", "reported_direction")
                        ),
                        "claim": str(signal["summary"]),
                        "source_state": str(
                            signal.get("source_state", "reported_update")
                        ),
                    }
                    for signal in new_route_signals
                )
                observation_url = primary_source_url
                published_date: str | None = max(
                    [
                        str(item["source_published_date"])
                        for item in new_route_items
                    ]
                    + [
                        str(signal["source_published_date"])
                        for signal in new_route_signals
                    ]
                )
                evidence_summary = " ".join(
                    [
                        str(item["summary"])
                        for item in new_route_items
                    ]
                    + [
                        str(signal["summary"])
                        for signal in new_route_signals
                    ]
                )
                used_item_titles.update(
                    str(item["title"])
                    for item in new_route_items
                )
                used_signal_titles.update(
                    str(signal["title"])
                    for signal in new_route_signals
                )
            else:
                observed_targets = [
                    target
                    for target in targets
                    if target["slot_state"] in {"observed_live", "reused_from_cache"}
                ]
                observation_url = str((observed_targets or targets)[0]["url"])
                published_date = None
                claim_atoms = []
                evidence_summary = str(
                    bundle["categories"][category]["no_change_summary"]
                )
            slot_state = (
                "observed_live"
                if any(target["slot_state"] == "observed_live" for target in targets)
                else "source_unavailable"
            )
            observations.append(
                {
                    "category": category,
                    "watch_topic_id": topic_id,
                    "source_role": str(task["source_role"]),
                    "channel": str(task["channel"]),
                    "slot_state": slot_state,
                    "url": observation_url,
                    "observed_at_jst": checked_at,
                    "published_date": published_date,
                    "evidence_summary": evidence_summary,
                    "source_target_results": targets,
                    "claim_atoms": claim_atoms,
                    "discovery_findings": [],
                }
            )
    unused = [
        item["title"]
        for items in items_by_category.values()
        for item in items
        if item["title"] not in used_item_titles
    ]
    if unused:
        fail(
            "items could not be assigned to a matching observation route: "
            + ", ".join(unused)
        )
    unused_signals = [
        signal["title"]
        for entry in bundle["categories"].values()
        for signal in entry["signals"]
        if signal["title"] not in used_signal_titles
    ]
    if unused_signals:
        fail(
            "signals could not be assigned to a matching observation route: "
            + ", ".join(unused_signals)
        )
    return observations


def build_findings(
    bundle: dict[str, Any],
    observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issue_date = str(bundle["issue_date"])
    checked_at = str(bundle["checked_at_jst"])
    reviewable: dict[tuple[str, str, str], dict[str, Any]] = {}
    for category, entry in bundle["categories"].items():
        for item in entry["items"]:
            for source in item["sources"]:
                key = (str(category), str(item["watch_topic_id"]), str(source["url"]))
                reviewable[key] = {
                    "title": str(item["title"]),
                    "url": str(source["url"]),
                    "published_date": str(item["source_published_date"]),
                    "summary": str(item["summary"]),
                    "watch_topic_ids": [str(item["watch_topic_id"])],
                    "finding_state": "fresh_update",
                }
        for signal in entry["signals"]:
            key = (
                str(category),
                str(signal["watch_topic_id"]),
                str(signal["source_url"]),
            )
            reviewable[key] = {
                "title": str(signal["title"]),
                "url": str(signal["source_url"]),
                "published_date": str(signal["source_published_date"]),
                "summary": str(signal["summary"]),
                "watch_topic_ids": [str(signal["watch_topic_id"])],
                "finding_state": "near_miss",
            }

    findings: dict[tuple[str, str, str], dict[str, Any]] = {}
    for observation in observations:
        category = str(observation["category"])
        topic_id = str(observation["watch_topic_id"])
        source_role = str(observation["source_role"])
        channel = str(observation["channel"])
        for result in observation["source_target_results"]:
            if result["slot_state"] not in {"observed_live", "reused_from_cache"}:
                continue
            url = str(result["url"])
            key = (category, topic_id, url)
            base = reviewable.get(key)
            findings[key] = {
                **(
                    base
                    or {
                        "title": f"{result['label']}の公表内容",
                        "url": url,
                        "published_date": result.get("published_date"),
                        "summary": str(result["evidence_summary"]),
                        "watch_topic_ids": [topic_id],
                        "finding_state": "background",
                    }
                ),
                "issue_date": issue_date,
                "slot_id": (
                    f"reviewed-import-{category}-{source_role}-{channel}"
                ),
                "category": category,
                "source_role": source_role,
                "channel": channel,
                "observed_at_jst": checked_at,
            }
    for key, base in reviewable.items():
        if key in findings:
            continue
        category, topic_id, _ = key
        findings[key] = {
            **base,
            "issue_date": issue_date,
            "slot_id": f"reviewed-import-{category}-additional",
            "category": category,
            "source_role": "independent_media_or_data",
            "channel": "web",
            "observed_at_jst": checked_at,
        }
    return list(findings.values())


def no_change_candidate(
    category: str,
    topic_id: str,
    issue_date: str,
    url: str,
) -> dict[str, Any]:
    readable_topic = topic_id.replace("_", " ")
    return {
        "category": category,
        "watch_topic_id": topic_id,
        "title": f"{category}、{readable_topic}に大きな更新なし",
        "source_published_date": issue_date,
        "source_urls": [url],
        "change_class": "background_only",
        "summary": f"{category}の{readable_topic}について、直近3日間に新しい決定、数値、結果は公表されていない。",
        "material_facts": [],
        "counter_evidence_checked": True,
    }


def item_candidate(category: str, item: dict[str, Any]) -> dict[str, Any]:
    title, summary = public_item_copy(category, item)
    return {
        "category": category,
        "watch_topic_id": str(item["watch_topic_id"]),
        "title": title,
        "source_published_date": str(item["source_published_date"]),
        "source_urls": [str(source["url"]) for source in item["sources"]],
        "change_class": str(item.get("change_class", "new_event")),
        "summary": summary,
        "material_facts": [
            fact
            for fact in (
                scrub_public_summary(raw_fact)
                for raw_fact in item["confirmed_facts"]
            )
            if fact and not state.public_render_copy_violations(fact, kind="summary")
        ],
        "counter_evidence_checked": True,
    }


def item_decision(category: str, item: dict[str, Any]) -> dict[str, Any]:
    title, _ = public_item_copy(category, item)
    return {
        "candidate_title": title,
        "adoption_decision": "adopt",
        "topic_value_class": topic_value_class(item["topic_value_class"]),
        "reader_delta": scrub_public_summary(item["why_it_matters"]),
        "materiality_basis": scrub_public_summary(item["what_changed"]),
        "reject_reason_class": None,
        "reject_reason": None,
    }


def rejected_decision(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_title": str(candidate["title"]),
        "adoption_decision": "reject",
        "topic_value_class": "operational_status_change",
        "reader_delta": "前号後に読者の判断を変える新しい事実はない。",
        "materiality_basis": "直接資料と補助情報で新しい決定、数値、結果がないことを確認した。",
        "reject_reason_class": "no_material_change",
        "reject_reason": "直近3日間の実質的な変化がない。",
    }


def signal_candidate(category: str, signal: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": category,
        "watch_topic_id": str(signal["watch_topic_id"]),
        "title": str(signal["title"]),
        "source_published_date": str(signal["source_published_date"]),
        "source_urls": [str(signal["source_url"])],
        "change_class": str(signal["change_class"]),
        "summary": str(signal["summary"]),
        "material_facts": [],
        "counter_evidence_checked": True,
    }


NO_CHANGE_PLACEHOLDER_PATTERNS = [
    "直近確認",
    "確定差分は不足",
    "単独記事にする確定差分",
    "公式・媒体・SNS系の証跡で確認した",
]


def no_change_placeholder_signal(signal: dict[str, Any]) -> bool:
    text = " ".join(
        str(signal.get(key, ""))
        for key in ("title", "summary", "rejection_reason", "materiality_basis")
    )
    return any(pattern in text for pattern in NO_CHANGE_PLACEHOLDER_PATTERNS)


def supporting_signal(signal: dict[str, Any]) -> bool:
    if no_change_placeholder_signal(signal):
        return False
    text = " ".join(
        str(signal.get(key, ""))
        for key in ("title", "summary", "change_class")
    )
    if str(signal.get("change_class")) in {"new_event", "material_update"}:
        return False
    return not bool(state.MATERIAL_SIGNAL_RE.search(text))


def signal_decision(signal: dict[str, Any]) -> dict[str, Any]:
    rejection_class = str(signal["rejection_reason_class"])
    signal_text = " ".join(
        str(signal.get(key, ""))
        for key in ("title", "summary", "change_class")
    )
    if (
        rejection_class in {"no_material_change", "lower_importance"}
        and (
            str(signal.get("change_class")) in {"new_event", "material_update"}
            or bool(state.MATERIAL_SIGNAL_RE.search(signal_text))
        )
    ):
        rejection_class = "duplicate_covered"
    return {
        "candidate_title": str(signal["title"]),
        "adoption_decision": "reject",
        "topic_value_class": topic_value_class(
            signal.get("topic_value_class", "operational_status_change")
        ),
        "reader_delta": str(signal["summary"]),
        "materiality_basis": str(signal["rejection_reason"]),
        "reject_reason_class": rejection_class,
        "reject_reason": str(signal["rejection_reason"]),
    }


def item_card(
    category: str,
    section_id: str,
    item: dict[str, Any],
    issue_date: str,
) -> dict[str, Any]:
    facts = []
    seen_facts: set[str] = set()
    for fact in [
        *[str(fact) for fact in item["confirmed_facts"]],
        str(item.get("summary", "")),
        str(item.get("what_changed", "")),
        str(item.get("why_it_matters", "")),
    ]:
        text = compact_text(scrub_public_summary(fact), 500)
        if (
            not text
            or text in seen_facts
            or state.public_render_copy_violations(text, kind="summary")
        ):
            continue
        seen_facts.add(text)
        facts.append(text)
        if len(facts) >= 4:
            break
    source_urls = [str(source["url"]) for source in item["sources"]]
    slug = str(item["slug"])
    slug_stem = slug[:-5] if slug.endswith(".html") else slug
    if not slug_stem.endswith(f"-{issue_date}"):
        slug_stem = f"{slug_stem}-{issue_date}"
    slug = f"{slug_stem}.html"
    card_title, card_summary = public_item_copy(category, item)
    return {
        "candidate_title": card_title,
        "title": card_title,
        "summary": card_summary,
        "section_id": section_id,
        "category": category,
        "source_published_date": str(item["source_published_date"]),
        "topic_value_class": topic_value_class(item["topic_value_class"]),
        "priority_class": str(item["priority_class"]),
        "detail": {
            "slug": slug,
            "sources": [
                {
                    "label": str(source["label"]),
                    "url": str(source["url"]),
                }
                for source in item["sources"]
            ],
            "summary": canonical_detail_summary(category, item, card_title, card_summary),
            "summary_basis": {
                "what_changed": scrub_public_summary(item["what_changed"]),
                "why_it_matters": scrub_public_summary(item["why_it_matters"]),
                "confirmed_facts": facts,
                "fact_sources": [
                    {"fact": fact, "source_urls": source_urls}
                    for fact in facts
                ],
                "limits_or_unknowns": scrub_public_summary(item["limits_or_unknowns"]),
                "source_dates": [str(item["source_published_date"])],
            },
        },
    }


def import_bundle(issue_date: str, bundle_path: Path, state_root: Path) -> dict[str, Any]:
    bundle = read_bundle(bundle_path)
    items_by_category = validate_bundle(bundle, issue_date)
    base = state_root / issue_date
    base.mkdir(parents=True, exist_ok=True)
    plan_path = base / "collection_plan.json"
    state.write_collection_plan(issue_date, state_root)
    plan = state.read_json(plan_path)
    observations = build_observations(bundle, items_by_category, plan)
    findings = build_findings(bundle, observations)
    frontier = state.build_frontier(state.read_json(state.CONFIG_PATH))
    state.validate_observation_records(observations, frontier)

    configs = category_config()
    results_by_category: dict[str, dict[str, Any]] = {}
    for category, config in configs.items():
        items = items_by_category[category]
        signals = [
            signal
            for signal in bundle["categories"][category]["signals"]
            if isinstance(signal, dict)
        ]
        candidate_signals = [
            signal
            for signal in signals
            if supporting_signal(signal)
        ]
        candidates = [item_candidate(category, item) for item in items]
        candidates.extend(signal_candidate(category, signal) for signal in candidate_signals)
        decisions = [
            *[item_decision(category, item) for item in items],
            *[signal_decision(signal) for signal in candidate_signals],
        ]
        cards = [
            item_card(
                category,
                str(config["section_id"]),
                item,
                issue_date,
            )
            for item in items
        ]
        results_by_category[category] = {
            "category": category,
            "candidates": candidates,
            "decisions": decisions,
            "cards": cards,
            "no_change_checks": [
                {
                    "topic_id": str(frontier_item["watch_topic_id"]),
                    "result": " ".join(
                        dict.fromkeys(
                            str(result["evidence_summary"])
                            for observation in observations
                            if observation["category"] == category
                            and observation["watch_topic_id"]
                            == frontier_item["watch_topic_id"]
                            for result in observation["source_target_results"]
                            if result["slot_state"]
                            in {"observed_live", "reused_from_cache"}
                        )
                    ),
                    "evidence_urls": sorted(
                        {
                            str(result["url"])
                            for observation in observations
                            if observation["category"] == category
                            and observation["watch_topic_id"]
                            == frontier_item["watch_topic_id"]
                            for result in observation["source_target_results"]
                            if result["slot_state"]
                            in {"observed_live", "reused_from_cache"}
                        }
                    ),
                }
                for frontier_item in frontier
                if frontier_item["category"] == category
            ],
        }

    candidates = [
        item
        for result in results_by_category.values()
        for item in result["candidates"]
    ]
    decisions = [
        item
        for result in results_by_category.values()
        for item in result["decisions"]
    ]
    cards = [
        item
        for result in results_by_category.values()
        for item in result["cards"]
    ]
    manifest = synthesize.minimal_manifest(
        issue_date,
        results_by_category,
        observations=observations,
        collection_mode=str(
            bundle.get("collection_mode", "reviewed_live_web")
        ),
        collection_completed_at_jst=str(bundle["checked_at_jst"]),
    )
    manifest["last_checked_jst"] = str(bundle["checked_at_jst"])
    manifest["note"] = "Explicit reviewed live-Web checks imported through the canonical state contract."

    write_jsonl(base / "observations.jsonl", observations)
    write_jsonl(base / "findings.jsonl", findings)
    write_jsonl(base / "candidates.jsonl", candidates)
    write_jsonl(base / "decisions.jsonl", decisions)
    write_jsonl(base / "cards.jsonl", cards)
    (base / "coverage_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    result = state.assemble_issue_state(issue_date, state_root)
    return {
        **result,
        "research_bundle": str(bundle_path),
        "categories": len(results_by_category),
    }


def self_test() -> None:
    summary = canonical_detail_summary(
        "Honda",
        {
            "summary": "HondaがQuantumScapeと全固体電池の共同開発で合意した。",
            "detail_summary": (
                "変更点: HondaがQuantumScapeと共同開発で合意した。 "
                "重要性: Hondaの変化を広めに把握するため、重要更新として一覧に残す。"
            ),
            "what_changed": "HondaがQuantumScapeと全固体リチウム金属電池の複数年共同開発で合意した。",
            "why_it_matters": "EV戦略の見直しが続く中で、次世代電池の技術選択と量産可能性を確認する材料になる。",
            "confirmed_facts": [
                "QuantumScapeとHondaが全固体電池の複数年共同開発で合意した。",
                "QuantumScape株は発表後に上昇した。",
                "共同開発の追加条件や量産時期はまだ確認対象として残る。",
            ],
            "limits_or_unknowns": "追加条件、影響範囲、続報の有無は今後の確認対象。",
        },
        "Honda、QuantumScapeと全固体電池の共同開発で合意",
        "EV戦略の見直しが続く中で、次世代電池の技術選択と量産可能性を確認する材料になる。",
    )
    if SUMMARY_LABEL_RE.search(summary) or GENERIC_IMPORTANCE_RE.search(summary):
        fail("canonical detail summary kept label-heavy or internal copy")
    if no_change_candidate("OpenAI", "product_release", "2099-01-01", "https://openai.com/")["change_class"] != "background_only":
        fail("no-change candidate generation failed")
    if supporting_signal(
        {
            "title": "OpenAIがCodex Securityのアップデートを発表",
            "summary": "Codex Securityの更新が確認された。",
            "change_class": "material_update",
            "rejection_reason": "上位カードと重なるため一覧候補に留める。",
        }
    ):
        fail("reviewed import must not keep rejected material signals as candidates")
    if not supporting_signal(
        {
            "title": "OpenAI APIの確認",
            "summary": "直近の補助情報として確認した。",
            "change_class": "duplicate_followup",
            "rejection_reason": "上位カードと重なるため一覧候補に留める。",
        }
    ):
        fail("reviewed import must keep non-material supporting signals as candidates")
    material_reject = signal_decision(
        {
            "title": "OpenAIがCodex Securityのアップデートを発表",
            "summary": "Codex Securityの更新が確認された。",
            "change_class": "material_update",
            "rejection_reason_class": "no_material_change",
            "rejection_reason": "上位カードと重なるため一覧候補に留める。",
            "topic_value_class": "operational_status_change",
        }
    )
    if material_reject["reject_reason_class"] == "no_material_change":
        fail("reviewed import must not reject material signals as no-change")
    numeric_material_reject = signal_decision(
        {
            "title": "VWが経営不振で最大10万人削減、4工場閉鎖も視野",
            "summary": "人員削減と工場閉鎖の可能性が報じられた。",
            "change_class": "operational_status_change",
            "rejection_reason_class": "no_material_change",
            "rejection_reason": "上位カードと重なるため一覧候補に留める。",
            "topic_value_class": "operational_status_change",
        }
    )
    if numeric_material_reject["reject_reason_class"] == "no_material_change":
        fail("reviewed import must not reject numeric material signals as no-change")
    cleaned_title = public_card_title(
        {
            "title": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用 - ｄメニューニュース",
            "summary": "OpenAIがサイバー防衛の更新を公表した。",
        }
    )
    if cleaned_title != "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用":
        fail("reviewed import must strip publisher suffixes from public card titles")
    aligned_item = {
        "title": "ソフトバンクG株が約2年ぶり大幅安、米OpenAIのIPO先送りと報道 - Bloomberg.com",
        "watch_topic_id": "openai_financing",
        "source_published_date": "2099-01-01",
        "sources": [
            {"label": "Bloomberg", "url": "https://www.bloomberg.com/example"}
        ],
        "change_class": "material_update",
        "summary": "IPO延期報道を受け、ソフトバンクG株の下落が確認された。",
        "confirmed_facts": [
            "IPO延期報道を受け、ソフトバンクG株の下落が確認された。",
            "AI関連投資の評価に対する市場反応が確認された。",
            "追加条件や会社側の正式確認は引き続き確認対象になる。",
        ],
        "topic_value_class": "market_or_financial_impact",
        "what_changed": "IPO延期報道を受け、ソフトバンクG株の下落が確認された。",
        "why_it_matters": "AI関連投資の評価に対する市場反応を確認する材料になる。",
        "limits_or_unknowns": "会社側の正式確認や追加条件は引き続き確認対象になる。",
        "priority_class": "important",
        "slug": "softbank-openai-ipo.html",
    }
    if item_card("OpenAI", "openai", aligned_item, "2099-01-01")["candidate_title"] != item_decision("OpenAI", aligned_item)["candidate_title"]:
        fail("reviewed import card candidate titles must match adopted decisions")
    malformed_item = {
        "title": "OpenAIがClaude Mythos 5超えのセキュリティー特化AI「」のアップデートを発表＆セキュリティー特化Codexプラグイン「Codex Security」もアップデート",
        "watch_topic_id": "openai_security",
        "source_published_date": "2099-01-01",
        "sources": [
            {"label": "OpenAI", "url": "https://openai.com/example"}
        ],
        "change_class": "material_update",
        "summary": "OpenAIがClaude Mythos 5超えのセキュリティー特化AI「」のアップデートを発表＆セキュリティー特化Codexプラグイン「Codex Security」もアップデート",
        "confirmed_facts": [
            "Codex Securityの更新が確認された。",
            "セキュリティー特化AIの更新が確認対象になった。",
            "対象範囲や追加条件は引き続き確認が必要になる。",
        ],
        "topic_value_class": "technical_or_product_shift",
        "what_changed": "OpenAIがセキュリティー特化AIとCodex Securityの更新を公表した。",
        "why_it_matters": "企業向けAI利用で安全対策と運用改善を読む材料になる。",
        "limits_or_unknowns": "提供範囲、性能条件、追加条件は引き続き確認が必要。",
        "priority_class": "important",
        "slug": "openai-security-codex.html",
    }
    malformed_card = item_card("OpenAI", "openai", malformed_item, "2099-01-01")
    if "「」" in malformed_card["title"]:
        fail("reviewed import must remove empty Japanese quotes from public titles")
    if not summary_is_reader_facing(malformed_card["title"], malformed_card["summary"]):
        fail("reviewed import must not emit title-only card summaries")
    state.validate_decisions_and_cards(
        {"decisions": [item_decision("OpenAI", malformed_item)]},
        [item_candidate("OpenAI", malformed_item)],
        [malformed_card],
    )
    contaminated_item = {
        **malformed_item,
        "confirmed_facts": [
            *malformed_item["confirmed_facts"],
            "収集方法と掲載判断は内部の確認対象として処理した。",
        ],
    }
    contaminated_card = item_card(
        "OpenAI", "openai", contaminated_item, "2099-01-01"
    )
    if "収集方法" in contaminated_card["detail"]["summary"]:
        fail("reviewed import must omit invalid optional facts during authoring")
    state.validate_decisions_and_cards(
        {"decisions": [item_decision("OpenAI", contaminated_item)]},
        [item_candidate("OpenAI", contaminated_item)],
        [contaminated_card],
    )
    domain_cleaned_title = public_card_title(
        {
            "title": "OpenAI example.com、Daybreak更新",
            "summary": "OpenAIがDaybreakの防御機能を更新し、修正パッチの適用状況を公表した。",
            "what_changed": "OpenAIがDaybreakの防御機能更新と修正パッチ適用を公表した。",
            "why_it_matters": "サイバー防衛の実運用で修正まで進んだ点を確認できる。",
            "confirmed_facts": [],
        }
    )
    if state.public_render_copy_violations(domain_cleaned_title, kind="title"):
        fail("reviewed import must strip domain leaks from public card titles")
    cleaned_summary = public_card_summary(
        {
            "summary": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。",
            "what_changed": "OpenAIがDaybreakの防御機能を更新し、修正パッチの適用状況を公表した。",
            "why_it_matters": "サイバー防衛の実運用で、検知だけでなく修正まで進んだ点を確認できる。",
            "confirmed_facts": [
                "OpenAIはDaybreakの防御機能更新と修正パッチ適用を公表した。",
                "対象範囲や残る制約は追加確認が必要とされる。",
            ],
        },
        "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
        "OpenAI",
    )
    if not summary_is_reader_facing(
        "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
        cleaned_summary,
    ):
        fail("reviewed import must rewrite title-repetition card summaries")
    domain_cleaned_summary = public_card_summary(
        {
            "summary": "OpenAI example.comがDaybreakの防御機能を更新し、修正パッチの適用状況を公表した。",
            "what_changed": "OpenAI example.comがDaybreakの防御機能更新を公表した。",
            "why_it_matters": "サイバー防衛の実運用で、検知だけでなく修正まで進んだ点を確認できる。",
            "confirmed_facts": [
                "OpenAI example.comはDaybreakの防御機能更新と修正パッチ適用を公表した。",
                "対象範囲や残る制約は追加確認が必要とされる。",
            ],
        },
        "OpenAI、Daybreak更新",
        "OpenAI",
    )
    if state.public_render_copy_violations(domain_cleaned_summary, kind="summary"):
        fail("reviewed import must strip domain leaks from public card summaries")
    detail_summary = canonical_detail_summary(
        "OpenAI",
        {
            "summary": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。",
            "detail_summary": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。",
            "what_changed": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
            "why_it_matters": "サイバー防衛の実運用で、検知だけでなく修正まで進んだ点を確認できる。",
            "confirmed_facts": [
                "OpenAIはDaybreakの防御機能更新と修正パッチ適用を公表した。",
                "対象範囲や残る制約は追加確認が必要とされる。",
                "防御機能の更新は運用面の確認材料になる。",
            ],
            "limits_or_unknowns": "対象範囲や残る制約は追加確認が必要。",
        },
        "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
        cleaned_summary,
    )
    if not summary_is_reader_facing(
        "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
        detail_summary,
    ):
        fail("reviewed import must rewrite title-repetition detail summaries")
    bound_card_summary = (
        "Codex Securityの更新は、サイバー防衛の実運用で修正と検証まで進んだ点を示す。"
        "企業向けAI利用の安全対策を読む材料になる。"
    )
    rebound_detail_summary = canonical_detail_summary(
        "OpenAI",
        {
            "summary": bound_card_summary,
            "detail_summary": (
                "OpenAIはAPI料金体系と開発者向け利用条件の整理を進めている。"
                "導入企業のコスト管理や契約条件の見直しに関係する可能性がある。"
                "一方で、セキュリティー更新とは別の論点であり、今回のカード本文としては焦点がずれている。"
                "詳細条件、対象範囲、続報の有無は引き続き確認が必要になる。"
            ),
            "what_changed": "OpenAIがCodex Securityの更新を公表し、サイバー防衛の修正状況を確認できるようにした。",
            "why_it_matters": "企業向けAI利用で安全対策と運用改善を読む材料になる。",
            "confirmed_facts": [
                "Codex Securityの更新が確認された。",
                "サイバー防衛の実運用で修正状況が確認対象になる。",
                "対象範囲や追加条件は引き続き確認が必要になる。",
            ],
            "limits_or_unknowns": "対象範囲や追加条件は引き続き確認が必要。",
        },
        "OpenAI、Codex Securityを更新",
        bound_card_summary,
    )
    if state.text_overlap(bound_card_summary, rebound_detail_summary) < 2:
        fail("reviewed import detail summaries must stay bound to card summaries")
    generic_detail_summary = canonical_detail_summary(
        "OpenAI",
        {
            "summary": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。",
            "detail_summary": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。",
            "what_changed": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
            "why_it_matters": "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
            "confirmed_facts": [
                "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
                "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
                "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
            ],
            "limits_or_unknowns": "影響範囲、追加条件、続報の有無は引き続き確認が必要。",
        },
        "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
        "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用。",
    )
    if not summary_is_reader_facing(
        "OpenAI、サイバー防衛「Daybreak」強化 修正パッチを適用",
        generic_detail_summary,
    ):
        fail("reviewed import must fall back from unrecoverable repeated detail summaries")
    if not no_change_placeholder_signal(
        {
            "title": "OpenAI、product_releaseの直近確認",
            "summary": "公式・媒体・SNS系の証跡で確認したが、単独記事にする確定差分は不足した。",
        }
    ):
        fail("reviewed import must keep no-change placeholders out of candidates")
    task = {
        "slot_id": "openai-primary-web",
        "source_role": "primary_or_official",
        "channel": "web",
        "source_targets": [
            {"label": "OpenAI", "url": "https://openai.com/", "channel": "web"}
        ],
    }
    try:
        source_results(task, [], "product_release")
    except SystemExit:
        pass
    else:
        fail("reviewed import must reject seed targets without explicit checks")
    print("NIGHT SIGNAL RESEARCH IMPORT SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument(
        "--bundle",
        type=Path,
        help="defaults to state/YYYY-MM-DD/research_bundle.json",
    )
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    bundle = args.bundle or args.state_root / args.issue_date / "research_bundle.json"
    print(
        json.dumps(
            import_bundle(args.issue_date, bundle, args.state_root),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
