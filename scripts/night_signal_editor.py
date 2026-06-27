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
    text = INLINE_PUBLISHER_RE.sub("", text)
    sentences = []
    for sentence in re.split(r"(?<=[。！？!?])", text):
        cleaned = state.PUBLISHER_SUFFIX_RE.sub("", sentence)
        cleaned = state.DOMAIN_RE.sub("", cleaned)
        cleaned = EMPTY_JA_QUOTE_RE.sub("", cleaned)
        cleaned = TRAILING_MEDIA_CREDIT_RE.sub("", cleaned)
        cleaned = TRAILING_DOMAIN_RE.sub("", cleaned).strip(" -–—|｜")
        if cleaned and not ORPHAN_SOURCE_SENTENCE_RE.fullmatch(cleaned):
            sentences.append(cleaned)
    return compact_text(" ".join(sentences), 2600)


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
    return compact_text(text, 2600)


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
    value_class = topic_value_class(item.get("topic_value_class", "operational_status_change"))
    return state.topic_context_sentence(value_class, category)


def public_card_summary(item: dict[str, Any], title: str, category: str) -> str:
    original = compact_text(scrub_item_source_labels(item, item.get("summary", "")), 900)
    if original and summary_is_reader_facing(title, original):
        return original

    facts = state.normalize_material_facts(
        title,
        [
            compact_text(scrub_item_source_labels(item, fact), 320)
            for fact in item.get("confirmed_facts", [])
            if useful_fact(fact, category)
        ],
        limit=4,
    )
    what_changed = compact_text(scrub_item_source_labels(item, item.get("what_changed", "")), 500)
    limits = compact_text(scrub_item_source_labels(item, item.get("limits_or_unknowns", "")), 500)
    importance = item_importance(item, category, title)
    if state.analysis_headline(title):
        what_changed = state.analysis_scope_sentence(title)
        importance = state.analysis_conclusion(
            [item.get("why_it_matters", ""), *facts]
        )
        if not importance:
            fail(f"analysis item lacks an evidence-backed conclusion: {title}")
    event_parts = [part for part in (what_changed, *facts, original) if part]
    lead = event_parts[0] if event_parts else public_focus_phrase(title, category)
    summary = reader_summary_from_parts(
        title,
        [lead, *event_parts[1:], importance, limits],
        limit=900,
    )
    if summary:
        return summary

    summary = reader_summary_from_parts(
        title,
        [public_focus_phrase(title, category), importance, limits],
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
    existing = scrub_item_source_labels(item, item.get("detail_summary", ""))
    if (
        len(existing) >= 280
        and not SUMMARY_LABEL_RE.search(existing)
        and not state.GENERIC_CONTEXT_RE.search(existing)
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
    optional_parts.append(item_importance(item, category, title))
    optional_parts.append(scrub_public_summary(item.get("limits_or_unknowns", "")))

    seen: set[str] = set()
    sentences: list[str] = []
    for part in re.split(r"(?<=[。！？!?])", card_summary):
        sentence = sentence_from(scrub_item_source_labels(item, part), 700)
        key = state.copy_signature(sentence)
        if not sentence or not key or key in seen:
            continue
        seen.add(key)
        sentences.append(sentence)

    for part in optional_parts:
        sentence = sentence_from(scrub_item_source_labels(item, part), 700)
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
            compact_text(scrub_item_source_labels(item, fact), 500)
            for fact in item["confirmed_facts"]
        ],
        limit=4,
    )
    if not facts:
        fail(f"item lost material facts during card construction: {item.get('title', '')}")
    source_urls = [str(source["url"]) for source in item["sources"]]
    slug = str(item["slug"])
    slug_stem = slug[:-5] if slug.endswith(".html") else slug
    if not slug_stem.endswith(f"-{issue_date}"):
        slug_stem = f"{slug_stem}-{issue_date}"
    slug = f"{slug_stem}.html"
    card_title, card_summary = public_item_copy(category, item)
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
    model_chain = models.extraction_models()
    model_rate_limited = threading.Event()

    def review_category(category: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        label = str(category["label"])
        entry = categories[label]
        if not isinstance(entry, dict) or not isinstance(entry.get("records"), list):
            fail(f"Evidence records are missing: {label}")
        records = [record for record in entry["records"] if isinstance(record, dict)]
        raw: dict[str, Any] | None = None
        model_errors: list[str] = []
        if not model_rate_limited.is_set():
            messages = [
                {"role": "system", "content": core.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        core.category_prompt(category, issue_date, records),
                        ensure_ascii=False,
                    ),
                },
            ]
            rate_limited_models = 0
            for model_name in model_chain:
                try:
                    raw = core.model_request(
                        token,
                        messages,
                        model_name=model_name,
                        retry_wait_cap=90,
                    )
                    break
                except core.ModelRequestError as exc:
                    model_errors.append(f"{model_name}: {exc}")
                    if not exc.rate_limited:
                        break
                    rate_limited_models += 1
            if raw is None and rate_limited_models == len(model_chain):
                model_rate_limited.set()
        if raw is None:
            raw = {
                "items": [],
                "signals": [],
                "no_change_summary": " ".join(model_errors) or "model extraction unavailable",
            }
        normalized = core.normalize_result(raw, category, issue_date, records)
        core.backfill_items_from_evidence(
            normalized, category, issue_date, records
        )
        core.backfill_signals_from_evidence(
            normalized, category, issue_date, records
        )
        return label, [
            item_card(
                label,
                str(configs[label]["section_id"]),
                item,
                issue_date,
            )
            for item in normalized["items"]
        ]

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
    if SUMMARY_LABEL_RE.search(card["detail"]["summary"]):
        fail("Editor kept label-heavy detail copy")
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
