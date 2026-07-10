#!/usr/bin/env python3
"""Edit collected Evidence into the canonical NIGHT SIGNAL Issue."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any

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
        for item in category_payload.get("evidence", [])
        if isinstance(item, dict)
    ]
    for item in evidence:
        title = str(item.get("title", ""))
        body = str(item.get("body", ""))
        sentence_count = len([part for part in re.split(r"(?<=[。！？.!?])", body) if part.strip()])
        if (
            state.analysis_headline(title)
            or len(body) >= 1200
            or sentence_count >= 6
            or bool(re.search(r"(?:\|\s*-{3,}\s*\||表\s*[:：]|グラフ|チャート|図\s*[:：]|chart|table|graph)", body, re.I))
            or len(re.findall(r"\d+(?:\.\d+)?", body)) >= 12
        ):
            return True
    return False


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
            support_quotes = [
                {
                    "evidence_id": str(value.get("evidence_id", "")),
                    "quote": compact_text(value.get("quote", ""), 320),
                }
                for value in raw_point.get("support_quotes", [])
                if isinstance(value, dict)
                and isinstance(value.get("evidence_id"), str)
                and value.get("evidence_id")
                and compact_text(value.get("quote", ""), 320)
            ]
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
                        "support_quotes": support_quotes,
                    }
                )
            else:
                duplicate["evidence_ids"] = list(
                    dict.fromkeys([*duplicate.get("evidence_ids", []), *evidence_ids])
                )
                duplicate["support_quotes"] = list(
                    {
                        (str(value.get("evidence_id")), str(value.get("quote"))): value
                        for value in [
                            *duplicate.get("support_quotes", []),
                            *support_quotes,
                        ]
                        if isinstance(value, dict)
                    }.values()
                )
        sanitized["items"].append({**raw_item, "summary_points": points})
    return sanitized


def publication_record_chunks(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
    *,
    max_records: int = 12,
) -> list[list[dict[str, Any]]]:
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
                if any(
                    core.same_material_event(
                        title,
                        core.record_public_title(existing),
                    )
                    for existing in candidate
                )
            ),
            None,
        )
        if group is None:
            event_groups.append([record])
        else:
            group.append(record)
    chunks: list[list[dict[str, Any]]] = []
    bounded_groups = [
        group[index : index + max_records]
        for group in event_groups
        for index in range(0, len(group), max_records)
    ]
    for group in bounded_groups:
        if not chunks or len(chunks[-1]) + len(group) > max_records:
            chunks.append([])
        chunks[-1].extend(group)
    return [chunk for chunk in chunks if chunk]


def fit_model_payload(
    payload: dict[str, Any],
    *,
    max_bytes: int = 140_000,
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
    degraded_models: set[str] = set()
    degraded_models_lock = threading.Lock()

    def cards_from_raw(
        raw: dict[str, Any],
        category: dict[str, Any],
        label: str,
        records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, bool, dict[str, Any]]:
        raw = sanitize_model_result(raw)
        normalized = core.normalize_result(raw, category, issue_date, records)
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
        accepted = bool(normalized["coverage_complete"]) and failed == 0
        if not accepted:
            print(
                json.dumps(
                    {
                        "phase": "editor_result_rejected",
                        "category": label,
                        "missing_evidence_ids": normalized["missing_evidence_ids"],
                        "unpublishable_items": failed,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        feedback = {
            "missing_evidence_ids": normalized["missing_evidence_ids"],
            "conflicting_evidence_ids": normalized["conflicting_evidence_ids"],
            "unknown_excluded_ids": normalized["unknown_excluded_ids"],
            "unpublishable_items": failed,
        }
        return cards, failed, accepted, feedback

    def review_category(category: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        label = str(category["label"])
        entry = categories[label]
        if not isinstance(entry, dict) or not isinstance(entry.get("records"), list):
            fail(f"Evidence records are missing: {label}")
        records = [record for record in entry["records"] if isinstance(record, dict)]
        chunks = publication_record_chunks(category, issue_date, records)
        category_cards: list[dict[str, Any]] = []
        for chunk_index, chunk_records in enumerate(chunks, start=1):
            category_payload = fit_model_payload(
                core.category_prompt(category, issue_date, chunk_records)
            )
            quality_required = quality_model_required(category_payload)
            model_chain = models.routed_models(quality_required=quality_required)
            messages = [
                {"role": "system", "content": models.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        category_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ]
            selected_result: tuple[
                list[dict[str, Any]], int, bool, dict[str, Any]
            ] | None = None
            quality_model_name = str(
                models.load_config().get("extraction", {}).get("quality_model", "")
            )
            for model_name in model_chain:
                with degraded_models_lock:
                    if model_name in degraded_models:
                        continue
                attempt_messages = messages
                max_editorial_attempts = 2 if model_name == quality_model_name else 1
                for editorial_attempt in range(1, max_editorial_attempts + 1):
                    try:
                        raw = models.request(
                            token,
                            attempt_messages,
                            model_name=model_name,
                            retry_wait_cap=90,
                            request_label=f"{label} {chunk_index}/{len(chunks)}",
                        )
                    except models.ModelRequestError as exc:
                        if exc.rate_limited or model_name != model_chain[-1]:
                            with degraded_models_lock:
                                degraded_models.add(model_name)
                            break
                        raise
                    raw = sanitize_model_result(raw)
                    result = cards_from_raw(
                        raw,
                        category,
                        label,
                        chunk_records,
                    )
                    print(
                        json.dumps(
                            {
                                "phase": "model_route",
                                "category": label,
                                "model": model_name,
                                "route": "quality" if quality_required else "routine",
                                "chunk": chunk_index,
                                "chunks": len(chunks),
                                "attempt": editorial_attempt,
                                "cards": len(result[0]),
                                "rejected_items": result[1],
                                "accepted": result[2],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    if result[2]:
                        selected_result = result
                        break
                    attempt_messages = [
                        *messages,
                        {
                            "role": "assistant",
                            "content": json.dumps(
                                raw,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "The previous JSON failed deterministic evidence, repetition, "
                                "or completeness checks. Return the entire corrected JSON. "
                                "Keep every fact close to its cited source wording and exact "
                                "numbers; do not add unsupported names or synthesis. Do not "
                                "repeat the title. Evidence with no additional supported fact "
                                "must be excluded as no_material_update. Validation feedback: "
                                + json.dumps(
                                    result[3],
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                )
                            ),
                        },
                    ]
                if selected_result is not None:
                    break
            if selected_result is None:
                fail(
                    "Editor could not produce complete summaries for every evidence item: "
                    f"{label} chunk {chunk_index}/{len(chunks)}"
                )
            category_cards.extend(selected_result[0])
        return label, merge_repeated_cards(category_cards)

    cards_by_category: dict[str, list[dict[str, Any]]] = {}
    workers = max(1, int(os.getenv("NIGHT_SIGNAL_MODEL_CONCURRENCY", "1")))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(review_category, category) for category in contracts]
        for future in concurrent.futures.as_completed(futures):
            label, cards = future.result()
            cards_by_category[label] = cards
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
        evidence_sha256=evidence_store.bundle_sha256(evidence_path),
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
            "excluded_evidence": [],
        }
    )
    sanitized_points = sanitized["items"][0]["summary_points"]
    if len(sanitized_points) != 1 or sanitized_points[0]["evidence_ids"] != [
        "e001",
        "e002",
    ]:
        fail("Editor did not merge repeated model points and their evidence ids")
    oversized_payload = {
        "category": "Test",
        "watch_topics": [],
        "evidence": [
            {"id": f"e{index:03d}", "title": f"題名{index}", "body": "詳しい本文。" * 2000}
            for index in range(1, 4)
        ],
    }
    fitted_payload = fit_model_payload(oversized_payload)
    fitted_bytes = len(
        json.dumps(
            fitted_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if fitted_bytes > 140_000 or {
        item["id"] for item in fitted_payload["evidence"]
    } != {"e001", "e002", "e003"}:
        fail("Editor payload fitting dropped evidence or exceeded the request bound")
    if fitted_payload != oversized_payload:
        fail("Editor payload fitting altered source bodies")
    too_large = {
        **oversized_payload,
        "evidence": [
            {"id": "e999", "title": "題名", "body": "詳しい本文。" * 30000}
        ],
    }
    try:
        fit_model_payload(too_large)
    except ValueError:
        pass
    else:
        fail("Editor accepted a payload only by silently shortening its source body")
    if quality_model_required(
        {"evidence": [{"title": "企業が新製品を発売", "body": "企業は新製品を7月に発売した。"}]}
    ):
        fail("Editor routed a routine factual extraction to the quality model")
    if not quality_model_required(
        {"evidence": [{"title": "【分析】市場構造を検証", "body": "複数の数値から市場構造を分析した。"}]}
    ):
        fail("Editor did not route analysis work to the quality model")
    if quality_model_required(
        {"evidence": [{"title": "Product update", "body": "The company released a major product update with new enterprise controls."}]}
    ):
        fail("Editor routed a short factual translation to the quality model")
    if not quality_model_required(
        {"evidence": [{"title": "詳細発表", "body": "具体的な変更内容。" * 100}]}
    ):
        fail("Editor did not route body-rich synthesis to the quality model")
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
