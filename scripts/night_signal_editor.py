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
GENERIC_IMPORTANCE_RE = re.compile(
    r"重要更新として一覧に残す|変化を広めに把握|関連テーマは|出典日付は"
)
TRAILING_DOMAIN_RE = re.compile(r"\s*[-–—|｜]\s*[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?:/[^\s。、]*)?\s*$")
EMPTY_JA_QUOTE_RE = re.compile(r"[「『]\s*[」』]")
INLINE_PUBLISHER_RE = re.compile(
    r"\s[-–—]\s*(?:"
    r"Yahoo![^。！？]{0,40}|MSN|"
    r"[A-Za-z0-9][A-Za-z0-9 .&!|｜・-]*(?:\.[A-Za-z]{2,})?|"
    r"[ぁ-んァ-ヶ一-龯]+(?:新聞|ニュース|ファイナンス|通信|テレビ)[^。！？]{0,30}"
    r")(?=[。！？]|$)"
)
TRAILING_MEDIA_CREDIT_RE = re.compile(
    r"\s*[（(](?:フィスコ|音楽ナタリー|BASKET COUNT|共同通信|時事通信|Reuters|ロイター)[）)]$",
    re.I,
)
ORPHAN_SOURCE_SENTENCE_RE = re.compile(
    r"^(?:ニュース|ファイナンス|MSN|web|オンライン)[。．.!！?？]*$",
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


def useful_fact(fact: Any, category: str) -> bool:
    text = compact_text(fact, 500)
    if GENERIC_IMPORTANCE_RE.search(text) or state.material_fact_violations(text):
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
    title = state.EMPTY_GROUP_RE.sub("", title)
    for _ in range(3):
        cleaned = state.PUBLISHER_SUFFIX_RE.sub("", title)
        cleaned = TRAILING_DOMAIN_RE.sub("", cleaned)
        cleaned = EMPTY_JA_QUOTE_RE.sub("", cleaned)
        cleaned = state.EMPTY_GROUP_RE.sub("", cleaned)
        cleaned = cleaned.strip(" -–—|｜")
        if cleaned == title:
            break
        title = cleaned
    return compact_text(title.strip())


def scrub_public_summary(value: Any) -> str:
    text = compact_text(value, 2600)
    text = re.sub(r"https?://\S+", "", text)
    text = INLINE_PUBLISHER_RE.sub("", text)
    sentences = []
    for sentence in re.split(r"(?<=[。！？!?])", text):
        cleaned = state.PUBLISHER_SUFFIX_RE.sub("", sentence)
        cleaned = state.DOMAIN_RE.sub("", cleaned)
        cleaned = EMPTY_JA_QUOTE_RE.sub("", cleaned)
        cleaned = TRAILING_MEDIA_CREDIT_RE.sub("", cleaned)
        cleaned = TRAILING_DOMAIN_RE.sub("", cleaned).strip(" -–—|｜")
        if (
            cleaned
            and not ORPHAN_SOURCE_SENTENCE_RE.fullmatch(cleaned)
            and not state.ORPHAN_LEADING_PARTICLE_RE.search(cleaned)
        ):
            sentences.append(cleaned)
    text = compact_text(" ".join(sentences), 2600)
    text = re.sub(r"([。．.!！？?])\s+(?=[。．.!！？?])", r"\1", text)
    text = re.sub(r"[。．.]{2,}", "。", text)
    text = re.sub(r"[！？!?]{2,}", lambda match: match.group(0)[0], text)
    return text


def scrub_item_source_labels(item: dict[str, Any], value: Any) -> str:
    text = scrub_public_summary(value)
    for source in item.get("sources", []):
        if not isinstance(source, dict):
            continue
        label = compact_text(source.get("label", ""), 120)
        if len(label) < 3:
            continue
        text = re.sub(
            rf"\s*(?:[-–—]\s*)?{re.escape(label)}(?=[。！？!?]|$)",
            "",
            text,
            flags=re.I,
        )
    return scrub_public_summary(text)


def public_card_title(item: dict[str, Any]) -> str:
    candidates = [
        item.get("title", ""),
        re.split(r"(?<=[。！？!?])", compact_text(item.get("summary", ""), 180))[0],
        item.get("what_changed", ""),
        *[
            fact
            for fact in item.get("confirmed_facts", [])
            if useful_fact(fact, str(item.get("category", "")))
        ],
    ]
    first_cleaned = ""
    for candidate in candidates:
        cleaned = scrub_public_title(scrub_item_source_labels(item, candidate))
        cleaned = TRAILING_MEDIA_CREDIT_RE.sub("", cleaned).strip()
        if cleaned and not first_cleaned:
            first_cleaned = cleaned
        if cleaned and not state.public_render_copy_violations(cleaned, kind="title"):
            return cleaned
    return first_cleaned


def summary_is_reader_facing(title: str, summary: str) -> bool:
    if state.public_render_copy_violations(summary, kind="summary"):
        return False
    if state.GENERIC_CONTEXT_RE.search(summary):
        return False
    if not state.analysis_summary_complete(title, summary):
        return False
    return not state.reader_summary_violations(title, summary)


def public_focus_phrase(title: str, category: str) -> str:
    focus = scrub_public_title(title)
    if category:
        focus = re.sub(rf"^{re.escape(category)}[、,:：\s]+", "", focus).strip()
    return focus.strip("、。 ") or category or "この更新"


def sentence_from(value: Any) -> str:
    text = scrub_public_summary(value).rstrip("。")
    if not text:
        return ""
    return f"{text}。"


def reader_summary_from_parts(title: str, parts: list[Any]) -> str:
    kept: list[str] = []
    for part in parts:
        for raw_sentence in re.split(r"(?<=[。！？!?])\s*", str(part)):
            sentence = sentence_from(raw_sentence)
            if not sentence:
                continue
            duplicate_index = next(
                (
                    index
                    for index, existing in enumerate(kept)
                    if state.materially_same_fact(sentence, existing)
                ),
                None,
            )
            if duplicate_index is not None:
                if state.fact_specificity(sentence) > state.fact_specificity(
                    kept[duplicate_index]
                ):
                    kept[duplicate_index] = sentence
                continue
            kept.append(sentence)
    informative = [
        sentence for sentence in kept if state.fact_adds_information(title, sentence)
    ]
    if informative:
        kept = informative
    candidate = " ".join(kept)
    if candidate and summary_is_reader_facing(title, candidate):
        return candidate
    return ""


def item_importance(
    item: dict[str, Any],
    category: str,
    title: str = "",
) -> str:
    importance = scrub_public_summary(item.get("why_it_matters", ""))
    if (
        useful_importance(importance)
        and not state.public_render_copy_violations(importance, kind="summary")
        and (not title or state.title_repetition_score(title, importance) < 0.82)
    ):
        return importance
    return ""


def public_card_summary(item: dict[str, Any], title: str, category: str) -> str:
    facts = state.normalize_material_facts(
        title,
        [
            scrub_item_source_labels(item, fact)
            for fact in item.get("confirmed_facts", [])
            if useful_fact(fact, category)
        ],
    )
    what_changed = scrub_item_source_labels(item, item.get("what_changed", ""))
    limits = scrub_item_source_labels(item, item.get("limits_or_unknowns", ""))
    importance = (
        item_importance(item, category, title)
        if state.analysis_headline(title)
        else ""
    )
    if state.analysis_headline(title):
        what_changed = state.analysis_scope_sentence(title)
        importance = state.analysis_conclusion(
            [item.get("why_it_matters", ""), *facts]
        )
        if not importance:
            fail(f"analysis item lacks an evidence-backed conclusion: {title}")
    event_parts = [part for part in (what_changed, *facts) if part]
    lead = event_parts[0] if event_parts else public_focus_phrase(title, category)
    summary = reader_summary_from_parts(
        title,
        [lead, *event_parts[1:], importance, limits],
    )
    if summary:
        return summary

    summary = reader_summary_from_parts(
        title,
        [public_focus_phrase(title, category), importance, limits],
    )
    if summary:
        return summary
    raise UnpublishableItem(f"unable to construct a reader-facing card summary: {title}")


def canonical_detail_summary(
    category: str,
    item: dict[str, Any],
    title: str,
    card_summary: str,
) -> str:
    optional_parts: list[Any] = [
        fact
        for fact in item.get("confirmed_facts", [])
        if useful_fact(fact, category)
        and state.title_repetition_score(title, scrub_public_summary(fact)) < 0.82
    ]
    if state.analysis_headline(title):
        optional_parts.append(item_importance(item, category, title))
    limits = scrub_public_summary(item.get("limits_or_unknowns", ""))
    if limits:
        optional_parts.append(limits)

    composed = reader_summary_from_parts(
        title,
        [
            card_summary,
            *[scrub_item_source_labels(item, part) for part in optional_parts],
        ],
    )
    if (
        composed
        and summary_is_reader_facing(title, composed)
        and state.text_overlap(card_summary, composed) >= 2
    ):
        return composed
    raise UnpublishableItem(f"unable to construct a card-bound detail summary: {title}")


def public_item_copy(category: str, item: dict[str, Any]) -> tuple[str, str]:
    title = public_card_title(item)
    summary = public_card_summary(item, title, category)
    return title, summary


def quality_model_required(category_payload: dict[str, Any]) -> bool:
    evidence = [
        item
        for item in category_payload.get("evidence", [])
        if isinstance(item, dict)
    ]
    cluster_counts: dict[str, int] = {}
    for item in evidence:
        cluster = str(item.get("cluster_key", ""))
        if cluster:
            cluster_counts[cluster] = cluster_counts.get(cluster, 0) + 1
        title = str(item.get("title", ""))
        excerpt = str(item.get("excerpt", ""))
        japanese = len(re.findall(r"[ぁ-んァ-ヶ一-龯]", excerpt))
        latin = len(re.findall(r"[A-Za-z]", excerpt))
        if state.analysis_headline(title) or (latin >= 24 and japanese < 6):
            return True
    return any(count > 1 for count in cluster_counts.values())


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
    facts = state.normalize_material_facts(
        public_card_title(item),
        [
            scrub_item_source_labels(item, fact)
            for fact in item["confirmed_facts"]
        ],
    )
    if not facts:
        raise UnpublishableItem(
            f"item lost material facts during card construction: {item.get('title', '')}"
        )
    source_urls = [str(source["url"]) for source in item["sources"]]
    limits = scrub_public_summary(item.get("limits_or_unknowns", ""))
    slug = str(item["slug"])
    slug_stem = slug[:-5] if slug.endswith(".html") else slug
    if not slug_stem.endswith(f"-{issue_date}"):
        slug_stem = f"{slug_stem}-{issue_date}"
    slug = f"{slug_stem}.html"
    card_title, card_summary = public_item_copy(category, item)
    why_it_matters = scrub_public_summary(item.get("why_it_matters", ""))
    return {
        "watch_topic_id": str(item["watch_topic_id"]),
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
                **({"why_it_matters": why_it_matters} if why_it_matters else {}),
                "confirmed_facts": facts,
                "fact_sources": [
                    {"fact": fact, "source_urls": source_urls}
                    for fact in facts
                ],
                **({"limits_or_unknowns": limits} if limits else {}),
                "source_dates": [str(item["source_published_date"])],
            },
        },
    }


def edit_evidence(
    issue_date: str,
    evidence_path: Path,
    state_root: Path,
    token: str,
) -> dict[str, Any]:
    evidence = read_evidence(evidence_path)
    if evidence.get("issue_date") != issue_date:
        fail("Evidence date does not match the requested Issue date")
    categories = evidence.get("categories")
    configs = category_config()
    if not isinstance(categories, dict) or set(categories) != set(configs):
        fail("Evidence must cover every configured category exactly once")

    contracts = core.category_contracts()
    degraded_models: set[str] = set()
    degraded_models_lock = threading.Lock()

    def cards_from_raw(
        raw: dict[str, Any],
        category: dict[str, Any],
        label: str,
        records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int]:
        normalized = core.normalize_result(raw, category, issue_date, records)
        core.backfill_items_from_evidence(normalized, category, issue_date, records)
        normalized["items"] = core.merge_related_items(normalized["items"])
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
        return cards, failed

    def review_category(category: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        label = str(category["label"])
        entry = categories[label]
        if not isinstance(entry, dict) or not isinstance(entry.get("records"), list):
            fail(f"Evidence records are missing: {label}")
        records = [record for record in entry["records"] if isinstance(record, dict)]
        category_payload = core.category_prompt(category, issue_date, records)
        selected_result: tuple[list[dict[str, Any]], int] | None = None
        if category_payload["evidence"]:
            quality_required = quality_model_required(category_payload)
            model_chain = models.routed_models(quality_required=quality_required)
            messages = [
                {"role": "system", "content": core.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        category_payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ]
            for model_name in model_chain:
                with degraded_models_lock:
                    if model_name in degraded_models:
                        continue
                try:
                    raw = core.model_request(
                        token,
                        messages,
                        model_name=model_name,
                        retry_wait_cap=90,
                        request_label=label,
                    )
                except core.ModelRequestError as exc:
                    if exc.rate_limited:
                        with degraded_models_lock:
                            degraded_models.add(model_name)
                    continue
                result = cards_from_raw(raw, category, label, records)
                selected_result = result
                print(
                    json.dumps(
                        {
                            "phase": "model_route",
                            "category": label,
                            "model": model_name,
                            "route": "quality" if quality_required else "routine",
                            "cards": len(result[0]),
                            "rejected_items": result[1],
                            "accepted": True,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                break
        if selected_result is None:
            selected_result = cards_from_raw({"items": []}, category, label, records)
        return label, selected_result[0]

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
    if quality_model_required(
        {"evidence": [{"title": "企業が新製品を発売", "excerpt": "企業は新製品を7月に発売した。", "cluster_key": "a"}]}
    ):
        fail("Editor routed a routine factual extraction to the quality model")
    if not quality_model_required(
        {"evidence": [{"title": "【分析】市場構造を検証", "excerpt": "複数の数値から市場構造を分析した。", "cluster_key": "b"}]}
    ):
        fail("Editor did not route analysis work to the quality model")
    if not quality_model_required(
        {"evidence": [{"title": "Product update", "excerpt": "The company released a major product update with new enterprise controls.", "cluster_key": "c"}]}
    ):
        fail("Editor did not route translation-heavy work to the quality model")
    if not quality_model_required(
        {
            "evidence": [
                {"title": "発表1", "excerpt": "企業が新方針を公表した。", "cluster_key": "shared"},
                {"title": "発表2", "excerpt": "別資料が条件を示した。", "cluster_key": "shared"},
            ]
        }
    ):
        fail("Editor did not route cross-source synthesis to the quality model")
    if scrub_public_summary("更新を確認した。。影響は継続調査する！？") != (
        "更新を確認した。 影響は継続調査する！"
    ):
        fail("Editor did not normalize repeated public punctuation")
    if scrub_item_source_labels(
        {"sources": [{"label": "Moomoo"}]},
        "宇宙関連株への影響を分析。 Moomoo。",
    ) != "宇宙関連株への影響を分析。":
        fail("Editor left repeated punctuation after removing a source label")
    item = {
        "watch_topic_id": "product_release",
        "title": "OpenAIがCodex Securityの更新版を公開 - Example News",
        "summary": (
            "OpenAIはCodex Securityの更新版を公開し、脆弱性検出後の修正支援を追加した。"
            "企業のコード監査で、検出から修正までを一つの流れで扱える点が重要になる。"
        ),
        "source_published_date": "2099-01-01",
        "topic_value_class": "technical_or_product_shift",
        "priority_class": "priority",
        "slug": "openai-codex-security",
        "detail_summary": (
            "OpenAIはCodex Securityの更新版を公開し、脆弱性検出後の修正支援を追加した。"
            "企業のコード監査では、検出結果を修正作業へつなげられる。"
        ),
        "what_changed": "OpenAIがCodex Securityの更新版と修正支援機能を公開した。",
        "why_it_matters": "企業のコード監査で検出から修正までを一つの流れで扱える。",
        "confirmed_facts": [
            "OpenAIはCodex Securityの更新版を公開した。",
            "更新版には脆弱性検出後の修正支援が追加された。",
        ],
        "limits_or_unknowns": "提供範囲と利用条件の詳細は公表資料の範囲に限られる。",
        "sources": [
            {"label": "OpenAI", "url": "https://openai.com/example"}
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
        "what_changed": "ベトナム政府が初の原子力発電所建設計画を加速した。",
        "why_it_matters": "",
        "confirmed_facts": [
            "建設候補地はニントゥアン省に置かれる。",
            "第1原発はロシアの協力で建設する計画となっている。",
            "第1原発はロシアの協力で建設する計画である。",
            "第2原発は日本との協力を想定している。",
            "政府は2030年までの着工を目標に掲げた。",
            "初号機の運転開始時期は2035年を想定している。",
            "設備容量は合計4ギガワットを計画している。",
        ],
        "sources": [{"label": "Government", "url": "https://example.com/nuclear"}],
    }
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
        "what_changed": "企業が国内工場への追加投資を決定した。",
        "why_it_matters": "",
        "confirmed_facts": ["追加投資額は500億円で、2027年に新設備を稼働する。"],
        "limits_or_unknowns": "",
    }
    thin_card = item_card("日本経済", "japan-economy", thin_item, "2099-01-01")
    if thin_card["summary"] != "追加投資額は500億円で、2027年に新設備を稼働する。":
        fail("Editor padded a thin source instead of keeping its supported fact concise")
    if SUMMARY_LABEL_RE.search(card["detail"]["summary"]):
        fail("Editor kept label-heavy detail copy")
    item_without_limits = dict(item)
    item_without_limits.pop("limits_or_unknowns")
    card_without_limits = item_card(
        "OpenAI", "openai", item_without_limits, "2099-01-01"
    )
    if "limits_or_unknowns" in card_without_limits["detail"]["summary_basis"]:
        fail("Editor invented an uncertainty absent from the source item")
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
