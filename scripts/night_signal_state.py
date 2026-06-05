#!/usr/bin/env python3
"""Schema-first operating state for NIGHT SIGNAL.

This is not another publication gate. It is the small core that the nightly
system should optimize around: discovery frontier -> observations -> candidates
-> decisions -> publication plan. OpenAI-backed runs can produce the same JSON
shape with Responses API Structured Outputs; local and CI runs can still inspect
the state deterministically.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from render_detail import FORBIDDEN_TEXT as DETAIL_FORBIDDEN_TEXT
from render_detail import render as render_detail_html


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "night_signal_coverage.json"
SOURCES_PATH = ROOT / "config" / "night_signal_sources.json"
MARKER_PATH = ROOT / ".night-signal-issue-date"
DEFAULT_STATE_ROOT = ROOT / "state"

STATE_NAMES = [
    "frontier_built",
    "observations_collected",
    "candidates_normalized",
    "topic_value_decided",
    "issue_rendered",
    "publication_ready",
]

PUBLIC_COPY_FORBIDDEN_TERMS = sorted(
    set(
        DETAIL_FORBIDDEN_TEXT
        + [
            "一次で固定",
            "一次資料",
            "一次更新",
            "数字を固定",
            "完了扱い",
            "補助線",
            "採用は一次",
            "採用前",
            "保留に落と",
            "直検索",
            "カバレッジ",
            "今夜やること",
            "今夜のチェックリスト",
            "今夜の運用ルール",
            "機械的",
            "復旧版",
            "当日版が未生成",
            "前日コピー",
            "主軸に切り替え",
            "本線に更新",
            "修正しました",
            "再公開",
            "公式/主要報道",
            "確認として",
            "採用判断",
            "掲載判断",
            "公開判断",
            "調査方法",
            "探索経路",
            "監視対象",
            "収集方針",
            "候補は本文化水準に届かず",
        ]
    )
)

PUBLIC_SUMMARY_PROCESS_PATTERNS = [
    (r"(?:採用|掲載|公開)(?:判断|基準|可否|候補)", "selection/publication procedure"),
    (r"(?:調査|探索|監視|収集)(?:方法|経路|方針|対象|チャネル|チャンネル)", "research procedure"),
    (r"(?:見る|追う|確認する|収集する)必要がある", "reader/research instruction"),
    (r"(?:原文確認先|参照経路|参照先).{0,24}(?:併記|揃え|区別)", "source-handling commentary"),
    (r"(?:本項目|本記事).{0,24}(?:区別して掲載|掲載する)", "publication commentary"),
    (r"作業(?:指示|説明|メモ|語|上|として|を書)", "authoring work wording"),
]

TITLE_FORBIDDEN_CHARS = ["→", "“", "”"]
GENERIC_TITLE_STARTS = ["何が", "なぜ", "どう見る", "読み方", "ポイント"]
VAGUE_TITLE_PHRASES = [
    "記事まとめ",
    "最新動向",
    "関連ニュース",
    "今日の話題",
    "注目情報",
    "情報整理",
    "状況整理",
    "要点整理",
    "確認メモ",
]
SCHEDULE_ONLY_TERMS = ["開幕予定", "開催予定", "決勝予定", "予定通り"]
SCHEDULE_MATERIAL_TERMS = ["変更", "決定", "発表", "延期", "前倒し", "中止", "追加", "確定"]

SOURCE_OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "category",
        "watch_topic_id",
        "source_role",
        "channel",
        "slot_state",
        "url",
        "observed_at_jst",
        "published_date",
        "evidence_summary",
        "source_target_results",
        "claim_atoms",
    ],
    "properties": {
        "category": {"type": "string"},
        "watch_topic_id": {"type": "string"},
        "source_role": {"type": "string", "enum": ["primary_or_official", "independent_media_or_data", "social_or_video_signal"]},
        "channel": {"type": "string", "enum": ["web", "sns_x", "instagram", "facebook", "youtube", "data", "calendar"]},
        "slot_state": {"type": "string", "enum": ["observed_live", "reused_from_cache", "source_unavailable", "not_applicable"]},
        "url": {"type": "string"},
        "observed_at_jst": {"type": "string"},
        "published_date": {"type": ["string", "null"]},
        "evidence_summary": {"type": "string"},
        "source_target_results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "url", "channel", "slot_state", "published_date", "evidence_summary"],
                "properties": {
                    "label": {"type": "string"},
                    "url": {"type": "string"},
                    "channel": {"type": "string", "enum": ["web", "sns_x", "instagram", "facebook", "youtube", "data", "calendar"]},
                    "slot_state": {"type": "string", "enum": ["observed_live", "reused_from_cache", "source_unavailable", "not_applicable"]},
                    "published_date": {"type": ["string", "null"]},
                    "evidence_summary": {"type": "string"},
                },
            },
        },
        "claim_atoms": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim_type", "claim", "source_state"],
                "properties": {
                    "claim_type": {"type": "string", "enum": ["announcement", "schedule", "numeric", "result", "award", "status"]},
                    "claim": {"type": "string"},
                    "source_state": {
                        "type": "string",
                        "enum": ["confirmed_update", "scheduled", "published_value", "final_result", "confirmed_award", "confirmed_status"],
                    },
                },
            },
        },
    },
}

CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "category",
        "watch_topic_id",
        "title",
        "source_published_date",
        "source_urls",
        "change_class",
        "summary",
        "material_facts",
        "counter_evidence_checked",
    ],
    "properties": {
        "category": {"type": "string"},
        "watch_topic_id": {"type": "string"},
        "title": {"type": "string"},
        "source_published_date": {"type": "string"},
        "source_urls": {"type": "array", "items": {"type": "string"}},
        "change_class": {
            "type": "string",
            "enum": ["new_event", "material_update", "routine_recurring", "duplicate_followup", "background_only"],
        },
        "summary": {"type": "string"},
        "material_facts": {"type": "array", "items": {"type": "string"}},
        "counter_evidence_checked": {"type": "boolean"},
    },
}

TOPIC_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "candidate_title",
        "adoption_decision",
        "topic_value_class",
        "reader_delta",
        "materiality_basis",
        "reject_reason_class",
        "reject_reason",
    ],
    "properties": {
        "candidate_title": {"type": "string"},
        "adoption_decision": {"type": "string", "enum": ["adopt", "reject"]},
        "topic_value_class": {
            "type": "string",
            "enum": [
                "decision_or_policy",
                "market_or_financial_impact",
                "technical_or_product_shift",
                "operational_status_change",
                "event_result_or_outcome",
                "material_schedule_change",
                "risk_or_safety_signal",
                "cultural_or_audience_signal",
            ],
        },
        "reader_delta": {"type": "string"},
        "materiality_basis": {"type": "string"},
        "reject_reason_class": {
            "type": ["string", "null"],
            "enum": ["duplicate_covered", "lower_importance", "no_material_change", "insufficient_evidence", "insufficient_relevance", None],
        },
        "reject_reason": {"type": ["string", "null"]},
    },
}

DETAIL_SOURCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "url"],
    "properties": {
        "label": {"type": "string"},
        "url": {"type": "string"},
    },
}

SUMMARY_BASIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "what_changed",
        "why_it_matters",
        "confirmed_facts",
        "limits_or_unknowns",
        "source_dates",
    ],
    "properties": {
        "what_changed": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "confirmed_facts": {"type": "array", "items": {"type": "string"}},
        "limits_or_unknowns": {"type": "string"},
        "source_dates": {"type": "array", "items": {"type": "string"}},
    },
}

SOURCE_TARGET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["label", "url", "source_role", "channel", "source_class"],
    "properties": {
        "label": {"type": "string"},
        "url": {"type": "string"},
        "source_role": {"type": "string"},
        "channel": {"type": "string"},
        "source_class": {"type": "string"},
    },
}

DETAIL_CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["slug", "sources", "summary", "summary_basis"],
    "properties": {
        "slug": {"type": "string"},
        "sources": {"type": "array", "items": DETAIL_SOURCE_SCHEMA},
        "summary": {"type": "string"},
        "summary_basis": SUMMARY_BASIS_SCHEMA,
    },
}

CARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "candidate_title",
        "title",
        "summary",
        "section_id",
        "category",
        "source_published_date",
        "topic_value_class",
        "priority_class",
        "detail",
    ],
    "properties": {
        "candidate_title": {"type": "string"},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "section_id": {"type": "string"},
        "category": {"type": "string"},
        "source_published_date": {"type": "string"},
        "topic_value_class": {"type": "string"},
        "priority_class": {"type": "string"},
        "detail": DETAIL_CARD_SCHEMA,
    },
}

COLLECTION_TASK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "issue_date",
        "slot_id",
        "category",
        "section_id",
        "watch_topic_id",
        "source_role",
        "channel",
        "priority",
        "reuse_policy",
        "model_route",
        "batch_group",
        "prompt_cache_key",
        "source_targets",
        "search_queries",
        "acceptance",
        "output_schema",
    ],
    "properties": {
        "issue_date": {"type": "string"},
        "slot_id": {"type": "string"},
        "category": {"type": "string"},
        "section_id": {"type": "string"},
        "watch_topic_id": {"type": "string"},
        "source_role": {"type": "string"},
        "channel": {"type": "string"},
        "priority": {"type": "string"},
        "reuse_policy": {"type": "string"},
        "model_route": {"type": "string"},
        "batch_group": {"type": "string"},
        "prompt_cache_key": {"type": "string"},
        "source_targets": {"type": "array", "items": SOURCE_TARGET_SCHEMA},
        "search_queries": {"type": "array", "items": {"type": "string"}},
        "acceptance": {
            "type": "object",
            "additionalProperties": False,
            "required": ["slot_closure_states", "must_record", "must_not_publish"],
            "properties": {
                "slot_closure_states": {"type": "array", "items": {"type": "string"}},
                "must_record": {"type": "array", "items": {"type": "string"}},
                "must_not_publish": {"type": "array", "items": {"type": "string"}},
            },
        },
        "output_schema": {"type": "string"},
    },
}

COLLECTION_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issue_date", "tasks", "source_observation_schema_ref"],
    "properties": {
        "issue_date": {"type": "string"},
        "tasks": {"type": "array", "items": COLLECTION_TASK_SCHEMA},
        "source_observation_schema_ref": {"type": "string"},
    },
}

ISSUE_STATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "issue_date",
        "state",
        "frontier",
        "observations",
        "candidates",
        "decisions",
        "cards",
        "coverage_manifest",
        "blockers",
    ],
    "properties": {
        "issue_date": {"type": "string"},
        "state": {"type": "string", "enum": STATE_NAMES},
        "frontier": {"type": "array", "items": {"type": "object"}},
        "observations": {"type": "array", "items": SOURCE_OBSERVATION_SCHEMA},
        "candidates": {"type": "array", "items": CANDIDATE_SCHEMA},
        "decisions": {"type": "array", "items": TOPIC_DECISION_SCHEMA},
        "cards": {"type": "array", "items": CARD_SCHEMA},
        "coverage_manifest": {"type": "object"},
        "blockers": {"type": "array", "items": {"type": "string"}},
    },
}

SCHEMAS = {
    "source_observation": SOURCE_OBSERVATION_SCHEMA,
    "candidate": CANDIDATE_SCHEMA,
    "topic_decision": TOPIC_DECISION_SCHEMA,
    "card": CARD_SCHEMA,
    "source_target": SOURCE_TARGET_SCHEMA,
    "collection_task": COLLECTION_TASK_SCHEMA,
    "collection_plan": COLLECTION_PLAN_SCHEMA,
    "issue_state": ISSUE_STATE_SCHEMA,
}


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL STATE FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {display_path(path)}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {display_path(path)}: {exc}")
    if not isinstance(value, dict):
        fail(f"{display_path(path)} must be a JSON object")
    return value


def read_json_records(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"missing file: {display_path(path)}")
    if path.suffix == ".jsonl":
        records: list[dict[str, Any]] = []
        for index, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                fail(f"invalid JSONL in {display_path(path)}:{index}: {exc}")
            if not isinstance(value, dict):
                fail(f"{display_path(path)}:{index} must be a JSON object")
            records.append(value)
        return records

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {display_path(path)}: {exc}")
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return value
    if isinstance(value, dict):
        for key in (path.stem, "items", "records"):
            records = value.get(key)
            if isinstance(records, list) and all(isinstance(item, dict) for item in records):
                return records
    fail(f"{display_path(path)} must be a JSON array of objects or JSONL objects")


def records_path(state_dir: Path, stem: str) -> Path:
    for suffix in (".jsonl", ".json"):
        path = state_dir / f"{stem}{suffix}"
        if path.exists():
            return path
    fail(f"missing file: {display_path(state_dir)}/{stem}.jsonl or {stem}.json")


def jst_today() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def category_required_channels(contract: dict[str, Any], category: dict[str, Any]) -> list[str]:
    channels = category.get("required_watch_topic_channels", contract.get("required_watch_topic_channels", ["web", "sns_x", "youtube"]))
    if not isinstance(channels, list) or any(not isinstance(channel, str) for channel in channels):
        fail(f"{category.get('label', '<unknown>')} has invalid required channels")
    return channels


def build_frontier(contract: dict[str, Any]) -> list[dict[str, Any]]:
    categories = contract.get("categories")
    if not isinstance(categories, list) or not categories:
        fail("coverage contract missing categories")

    frontier: list[dict[str, Any]] = []
    for category in categories:
        if not isinstance(category, dict):
            fail("coverage category must be an object")
        label = category.get("label")
        section_id = category.get("section_id")
        if not isinstance(label, str) or not isinstance(section_id, str):
            fail("coverage category missing label or section_id")
        axes = category.get("axes", [])
        topics = category.get("watch_topics", [])
        if not isinstance(axes, list) or not isinstance(topics, list):
            fail(f"{label} axes/watch_topics must be lists")
        axis_terms = sorted({term for axis in axes if isinstance(axis, dict) for term in axis.get("terms", []) if isinstance(term, str)})
        channels = category_required_channels(contract, category)
        for topic in topics:
            if not isinstance(topic, dict) or not isinstance(topic.get("id"), str):
                fail(f"{label} watch topic is invalid")
            topic_terms = [term for term in topic.get("terms", []) if isinstance(term, str)]
            frontier.append(
                {
                    "category": label,
                    "section_id": section_id,
                    "watch_topic_id": topic["id"],
                    "required_channels": channels,
                    "search_terms": sorted(set(axis_terms + topic_terms)),
                    "source_roles": ["primary_or_official", "independent_media_or_data", "social_or_video_signal"],
                }
            )
    return frontier


def selected_issue_date() -> str | None:
    if not MARKER_PATH.exists():
        return None
    return MARKER_PATH.read_text(encoding="utf-8").strip()


def records_file_exists(state_dir: Path, stem: str) -> bool:
    return any((state_dir / f"{stem}{suffix}").exists() for suffix in (".jsonl", ".json"))


def artifact_status(issue_date: str) -> dict[str, bool]:
    state_dir = DEFAULT_STATE_ROOT / issue_date
    return {
        "collection_plan": (state_dir / "collection_plan.json").exists(),
        "observations": records_file_exists(state_dir, "observations"),
        "candidates": records_file_exists(state_dir, "candidates"),
        "decisions": records_file_exists(state_dir, "decisions"),
        "cards": records_file_exists(state_dir, "cards"),
        "coverage_manifest": (state_dir / "coverage_manifest.json").exists(),
        "state_issue_json": (state_dir / "issue.json").exists(),
        "marker_is_issue_date": selected_issue_date() == issue_date,
        "sample_html": (ROOT / f"night-brief-web-sample-{issue_date}.html").exists(),
        "root_site_html": (ROOT / "site" / "index.html").exists(),
        "dated_site_html": (ROOT / "site" / issue_date / "index.html").exists(),
        "extraction_log": (ROOT / "details" / f"extraction-log-{issue_date}.html").exists(),
        "site_extraction_log": (ROOT / "site" / issue_date / "details" / f"extraction-log-{issue_date}.html").exists(),
    }


def readiness(issue_date: str) -> dict[str, Any]:
    contract = read_json(CONFIG_PATH)
    artifacts = artifact_status(issue_date)
    blockers = [name for name, ok in artifacts.items() if not ok]
    frontier = build_frontier(contract)
    if artifacts["state_issue_json"] and not blockers:
        source_state = "publication_ready"
    elif artifacts["cards"] and artifacts["coverage_manifest"]:
        source_state = "publication_plan_ready"
    elif artifacts["candidates"] and artifacts["decisions"]:
        source_state = "topic_value_decided"
    elif artifacts["observations"]:
        source_state = "observations_collected"
    else:
        source_state = "frontier_built"
    return {
        "issue_date": issue_date,
        "state": "publication_ready" if not blockers else source_state,
        "frontier_count": len(frontier),
        "artifacts": artifacts,
        "blockers": blockers,
        "purpose_invariants": {
            "closed_collection_before_synthesis": artifacts["observations"],
            "candidate_decision_card_chain_present": artifacts["candidates"] and artifacts["decisions"] and artifacts["cards"],
            "coverage_manifest_present": artifacts["coverage_manifest"],
            "publication_artifacts_present": artifacts["state_issue_json"] and artifacts["sample_html"] and artifacts["dated_site_html"],
        },
        "design": {
            "generation_owner": "night_signal_state.py --generate-issue",
            "generation_source_state": source_state,
            "collection_owner": "night_signal_collect.py",
            "synthesis_owner": "night_signal_synthesize.py",
            "publication_rule": "publish only selected JST-current issue artifacts",
            "ai_contract": "Responses API Structured Outputs can fill observations/candidates/decisions; renderers consume only schema-valid records.",
        },
    }


def require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        fail(f"issue state missing required string: {key}")
    return value.strip()


def require_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        fail(f"issue state missing required list: {key}")
    return value


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def effective_on_or_after(contract: dict[str, Any], key: str, issue_date: str) -> bool:
    value = contract.get(key)
    if not isinstance(value, str):
        return False
    try:
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
        effective_dt = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return False
    return issue_dt >= effective_dt


def public_copy_violations(text: str, *, kind: str) -> list[str]:
    stripped = text.strip()
    compact = compact_text(stripped)
    violations: list[str] = []
    if not compact:
        violations.append("empty")
        return violations
    if re.search(r"<[^>]+>", stripped):
        violations.append("html markup")
    if not re.search(r"[0-9A-Za-z\u3040-\u30ff\u3400-\u9fff]", stripped):
        violations.append("no readable text")
    leaked = [term for term in PUBLIC_COPY_FORBIDDEN_TERMS if term in stripped]
    if leaked:
        violations.append("internal/process wording: " + ", ".join(leaked[:8]))
    pattern_leaks = [label for pattern, label in PUBLIC_SUMMARY_PROCESS_PATTERNS if re.search(pattern, stripped)]
    if pattern_leaks:
        violations.append("procedure wording: " + ", ".join(pattern_leaks[:4]))
    if kind == "title":
        if any(char in stripped for char in TITLE_FORBIDDEN_CHARS):
            violations.append("decorative title punctuation")
        if any(stripped.startswith(prefix) for prefix in GENERIC_TITLE_STARTS):
            violations.append("generic explanatory title")
        if any(phrase in stripped for phrase in VAGUE_TITLE_PHRASES):
            violations.append("vague title phrase")
    return violations


def reject_public_copy(label: str, text: str, *, kind: str) -> None:
    violations = public_copy_violations(text, kind=kind)
    if violations:
        fail(f"{label} is not reader-facing public copy: " + "; ".join(violations))


def validate_detail_sources(detail: dict[str, Any], card_index: int) -> None:
    sources = detail.get("sources")
    if not isinstance(sources, list) or not sources:
        fail(f"cards[{card_index}] detail.sources must be a non-empty list")
    for source_index, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            fail(f"cards[{card_index}] detail.sources[{source_index}] must be an object")
        label = require_str(source, "label")
        url = require_str(source, "url")
        reject_public_copy(f"cards[{card_index}] detail.sources[{source_index}].label", label, kind="summary")
        if not url.startswith(("http://", "https://")):
            fail(f"cards[{card_index}] detail.sources[{source_index}].url must be absolute http(s): {url}")


def validate_summary_basis(detail: dict[str, Any], *, issue_date: str, source_date: str, card_index: int) -> None:
    contract = read_json(CONFIG_PATH)
    if not effective_on_or_after(contract, "detail_information_contract_effective_date", issue_date):
        return
    basis = detail.get("summary_basis")
    if not isinstance(basis, dict):
        fail(f"cards[{card_index}].detail.summary_basis is required for information-complete detail pages")

    for key in ("what_changed", "why_it_matters", "limits_or_unknowns"):
        value = require_str(basis, key)
        reject_public_copy(f"cards[{card_index}].detail.summary_basis.{key}", value, kind="summary")

    facts = basis.get("confirmed_facts")
    min_facts = int(contract.get("minimum_material_facts_per_published_item", 2))
    if not isinstance(facts, list) or len([fact for fact in facts if isinstance(fact, str) and fact.strip()]) < min_facts:
        fail(f"cards[{card_index}].detail.summary_basis.confirmed_facts must contain confirmed material facts")
    for fact_index, fact in enumerate(facts, start=1):
        if not isinstance(fact, str) or not fact.strip():
            fail(f"cards[{card_index}].detail.summary_basis.confirmed_facts[{fact_index}] must be a non-empty string")
        reject_public_copy(
            f"cards[{card_index}].detail.summary_basis.confirmed_facts[{fact_index}]",
            fact,
            kind="summary",
        )

    source_dates = basis.get("source_dates")
    if not isinstance(source_dates, list) or not source_dates:
        fail(f"cards[{card_index}].detail.summary_basis.source_dates must contain source dates")
    normalized_dates = [str(value).strip() for value in source_dates if str(value).strip()]
    if source_date not in normalized_dates:
        fail(f"cards[{card_index}].detail.summary_basis.source_dates must include card source date {source_date}")


def validate_public_card_copy(raw: dict[str, Any], detail: dict[str, Any], *, issue_date: str, card_index: int) -> None:
    title = require_str(raw, "title")
    summary = require_str(raw, "summary")
    source_date = require_str(raw, "source_published_date")
    detail_summary = require_str(detail, "summary")

    reject_public_copy(f"cards[{card_index}].title", title, kind="title")
    reject_public_copy(f"cards[{card_index}].summary", summary, kind="summary")
    reject_public_copy(f"cards[{card_index}].detail.summary", detail_summary, kind="summary")

    if any(term in title for term in SCHEDULE_ONLY_TERMS) and not any(term in title + summary for term in SCHEDULE_MATERIAL_TERMS):
        fail(f"cards[{card_index}] looks schedule-only; routine dates must stay out of published topics")

    validate_detail_sources(detail, card_index)
    validate_summary_basis(detail, issue_date=issue_date, source_date=source_date, card_index=card_index)


def relative_day_label(issue_date: str, source_date: str) -> str:
    try:
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
        source_dt = datetime.strptime(source_date, "%Y-%m-%d").date()
    except ValueError:
        fail(f"invalid issue/source date: {issue_date} / {source_date}")
    delta = (issue_dt - source_dt).days
    return {0: "今日", 1: "昨日", 2: "一昨日"}.get(delta, "")


def normalized_cards(issue: dict[str, Any]) -> list[dict[str, Any]]:
    issue_date = require_str(issue, "issue_date")
    cards = require_list(issue, "cards")
    if not cards:
        fail("issue state must contain at least one card")
    normalized: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for index, raw in enumerate(cards, start=1):
        if not isinstance(raw, dict):
            fail(f"cards[{index}] must be an object")
        candidate_title = require_str(raw, "candidate_title")
        title = require_str(raw, "title")
        summary = require_str(raw, "summary")
        section_id = require_str(raw, "section_id")
        category = require_str(raw, "category")
        source_date = require_str(raw, "source_published_date")
        detail = raw.get("detail")
        if not isinstance(detail, dict):
            fail(f"cards[{index}] missing detail object")
        slug = require_str(detail, "slug")
        validate_public_card_copy(raw, detail, issue_date=issue_date, card_index=index)
        if not slug.endswith(f"-{issue_date}.html"):
            fail(f"detail slug must end with -{issue_date}.html: {slug}")
        if slug in seen_slugs:
            fail(f"duplicate detail slug: {slug}")
        seen_slugs.add(slug)
        normalized.append(
            {
                **raw,
                "candidate_title": candidate_title,
                "title": title,
                "summary": summary,
                "section_id": section_id,
                "category": category,
                "source_published_date": source_date,
                "detail": detail,
                "slug": slug,
                "freshness_label": relative_day_label(issue_date, source_date),
            }
        )
    return normalized


def render_card(card: dict[str, Any], *, root: bool) -> str:
    title = html.escape(str(card["title"]))
    summary = html.escape(str(card["summary"]))
    section_id = html.escape(str(card["section_id"]), quote=True)
    source_date = html.escape(str(card["source_published_date"]))
    label = str(card.get("freshness_label") or "")
    label_text = f"{html.escape(label)} " if label else ""
    topic_class = html.escape(str(card.get("priority_class", "signal")))
    href_prefix = f"{html.escape(str(card['issue_date']), quote=True)}/" if root else ""
    slug = html.escape(str(card["slug"]), quote=True)
    return f"""        <article class="card {topic_class}">
          <div class="meta"><span class="pill">{label_text}{source_date}</span><span class="pill">{html.escape(str(card.get("category", "")))}</span></div>
          <h3>{title}</h3>
          <p>{summary}</p>
          <a class="link" href="{href_prefix}details/{slug}">詳細へ</a>
        </article>"""


def render_priority_card(index: int, card: dict[str, Any]) -> str:
    title = html.escape(str(card["title"]))
    summary = html.escape(str(card["summary"]))
    section_id = html.escape(str(card["section_id"]), quote=True)
    priority_class = html.escape(str(card.get("priority_class", "signal")))
    return f"""        <article class="priority-card {priority_class}"><span class="rank">{index}</span><h3>{title}</h3><p>{summary}</p><a class="tag" href="#{section_id}">詳細へ</a></article>"""


def signal_board_items(issue: dict[str, Any], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_date = require_str(issue, "issue_date")
    contract = read_json(CONFIG_PATH)
    category_rank = {
        str(category.get("label")): index
        for index, category in enumerate(contract.get("categories", []))
        if isinstance(category, dict)
    }
    candidates = [candidate for candidate in issue.get("candidates", []) if isinstance(candidate, dict)]
    decisions = {
        str(decision.get("candidate_title")): decision
        for decision in issue.get("decisions", [])
        if isinstance(decision, dict)
    }
    card_by_candidate = {str(card.get("candidate_title")): card for card in cards}
    allowed_dates = {issue_date}
    date_rank = {issue_date: 0}
    try:
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
        latest_dates = [
            issue_dt.isoformat(),
            datetime.fromordinal(issue_dt.toordinal() - 1).date().isoformat(),
            datetime.fromordinal(issue_dt.toordinal() - 2).date().isoformat(),
        ]
        allowed_dates = set(latest_dates)
        date_rank = {date: index for index, date in enumerate(latest_dates)}
    except ValueError:
        pass
    items = []
    for candidate in candidates:
        title = str(candidate.get("title", "")).strip()
        source_date = str(candidate.get("source_published_date", "")).strip()
        if not title or source_date not in allowed_dates:
            continue
        decision = decisions.get(title, {})
        card = card_by_candidate.get(title)
        items.append(
            {
                "title": title,
                "summary": str(candidate.get("summary", "")).strip(),
                "category": str(candidate.get("category", "")).strip(),
                "category_rank": category_rank.get(str(candidate.get("category", "")).strip(), 999),
                "source_published_date": source_date,
                "source_date_rank": date_rank.get(source_date, 99),
                "freshness_label": relative_day_label(issue_date, source_date),
                "adoption_decision": str(decision.get("adoption_decision", "reject")),
                "detail_slug": card.get("slug") if isinstance(card, dict) else "",
            }
        )
    items.sort(
        key=lambda item: (
            item["category_rank"],
            item["adoption_decision"] != "adopt",
            item["source_date_rank"],
            item["title"],
        )
    )
    return items


def render_signal_item(item: dict[str, Any], *, issue_date: str, root: bool) -> str:
    label = str(item.get("freshness_label") or "")
    label_text = f"{html.escape(label)} " if label else ""
    title = html.escape(str(item.get("title", "")))
    summary = html.escape(str(item.get("summary", "")))
    category = html.escape(str(item.get("category", "")))
    source_date = html.escape(str(item.get("source_published_date", "")))
    status = "詳細あり" if item.get("detail_slug") else "一覧のみ"
    href_prefix = f"{html.escape(issue_date, quote=True)}/" if root else ""
    detail = ""
    if item.get("detail_slug"):
        detail = (
            "\n"
            f'          <a class="category-update-link" href="{href_prefix}details/'
            f'{html.escape(str(item["detail_slug"]), quote=True)}">詳細へ</a>'
        )
    return f"""        <article class="category-update-item">
          <div class="category-update-meta"><span>{category}</span><span>{label_text}{source_date}</span><span>{html.escape(status)}</span></div>
          <strong>{title}</strong>
          <p>{summary}</p>{detail}
        </article>"""


def render_issue_html(issue: dict[str, Any], cards: list[dict[str, Any]], *, root: bool = False) -> str:
    issue_date = require_str(issue, "issue_date")
    display_date = issue_date.replace("-", ".")
    title = f"NIGHT SIGNAL | {issue_date}"
    hero_copy = html.escape(
        str(
            issue.get(
                "hero_copy",
                "眠りにつく前に、世界の輪郭を整える。次の朝に見落としたくない変化だけを、出典と日付を残して読む。",
            )
        )
    )
    nav_links = ['<a href="#priority">Priority</a>', '<a href="#category_updates">カテゴリ別新着</a>']
    contract = read_json(CONFIG_PATH)
    section_labels = {
        category["section_id"]: category["label"]
        for category in contract.get("categories", [])
        if isinstance(category, dict) and isinstance(category.get("section_id"), str)
    }
    for section_id, label in section_labels.items():
        nav_links.append(f'<a href="#{html.escape(section_id, quote=True)}">{html.escape(label)}</a>')
    nav_links.append('<a href="details/policy.html">方針</a>')
    nav_links.append(f'<a href="details/extraction-log-{html.escape(issue_date, quote=True)}.html">抽出ログ</a>')

    priority = "\n".join(render_priority_card(index, card) for index, card in enumerate(cards[:4], start=1))
    signals = signal_board_items(issue, cards)
    rendered_signals = "\n".join(render_signal_item(item, issue_date=issue_date, root=root) for item in signals)
    sections = []
    for section_id, label in section_labels.items():
        section_cards = [card for card in cards if card["section_id"] == section_id]
        rendered_cards = "\n".join(render_card({**card, "issue_date": issue_date}, root=root) for card in section_cards)
        sections.append(
            f"""    <section class="section" id="{html.escape(section_id, quote=True)}">
      <div class="section-head"><h2>{html.escape(label)}</h2><p>{len(section_cards)} updates</p></div>
      <div class="cards">
{rendered_cards}
      </div>
    </section>"""
        )

    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ --bg:#eef1f4; --ink:#0b1118; --muted:#687386; --panel:#fff; --line:#d8dee7; --blue:#1f5eff; --red:#b7352d; --teal:#087b73; --amber:#a86a17; --night:#071019; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--ink); font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Yu Gothic","Segoe UI",sans-serif; line-height:1.55; }}
    a {{ color:var(--blue); text-decoration:none; font-weight:800; }} a:hover {{ text-decoration:underline; }}
    header {{ position:sticky; top:0; z-index:10; background:rgba(238,241,244,.86); border-bottom:1px solid var(--line); backdrop-filter:blur(14px); }}
    .bar, main {{ max-width:1180px; margin:0 auto; }} .bar {{ padding:14px 22px; display:flex; justify-content:space-between; gap:18px; align-items:center; }}
    .brand strong {{ display:block; font-size:16px; letter-spacing:.18em; }} .brand span, .date, .edition {{ color:var(--muted); font-size:11px; font-weight:800; letter-spacing:.12em; text-transform:uppercase; }}
    nav {{ display:flex; flex-wrap:wrap; justify-content:flex-end; gap:6px; }} nav a {{ color:#334155; padding:7px 10px; border-radius:999px; font-size:12px; }}
    main {{ padding:26px 22px 58px; }} .hero {{ min-height:330px; background:var(--night); color:#fff; border-radius:12px; padding:34px; display:grid; align-content:space-between; }}
    .hero-top, .section-head {{ display:flex; align-items:end; justify-content:space-between; gap:16px; }} h1 {{ margin:24px 0 16px; font-size:clamp(42px,6vw,76px); line-height:.98; letter-spacing:0; }}
    .hero p {{ max-width:760px; color:#dce5ef; font-size:15px; }} .hero-meta {{ display:flex; flex-wrap:wrap; gap:9px; margin-top:26px; }}
    .hero-chip, .pill {{ border:1px solid var(--line); border-radius:5px; padding:7px 10px; font-size:11px; font-weight:900; }}
    .hero-chip {{ border-color:rgba(255,255,255,.18); color:#dce5ef; }} .section {{ margin-top:32px; }} .section-head {{ margin-bottom:12px; padding-top:14px; border-top:1px solid #9aa7b8; }}
    h2 {{ margin:0; font-size:23px; }} .priority, .cards, .category-update-list {{ display:grid; gap:14px; }} .priority {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .cards {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} .category-update-list {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    .priority-card, .card {{ background:var(--panel); border:1px solid var(--line); border-top:4px solid var(--blue); border-radius:10px; padding:18px; }}
    .category-update-item {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; }} .category-update-item strong {{ display:block; font-size:15px; line-height:1.35; margin-bottom:6px; }} .category-update-item p {{ font-size:13px; color:#334155; }} .category-update-meta {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; color:var(--muted); font-size:11px; font-weight:800; }} .category-update-link {{ font-size:12px; }}
    .priority-card.hot, .card.hot {{ border-top-color:var(--red); }} .priority-card.signal, .card.signal {{ border-top-color:var(--teal); }} .priority-card.macro, .card.macro {{ border-top-color:var(--amber); }}
    .rank {{ display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; margin-bottom:10px; border-radius:6px; background:var(--night); color:white; font-size:12px; font-weight:900; }}
    h3 {{ margin:0 0 8px; font-size:18px; line-height:1.32; }} p {{ margin:0 0 12px; }} .meta {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; color:var(--muted); }}
    @media (max-width:860px) {{ .priority, .cards, .category-update-list {{ grid-template-columns:1fr; }} .bar {{ align-items:flex-start; flex-direction:column; }} }}
  </style>
</head>
<body>
  <header><div class="bar"><div class="brand"><strong>NIGHT SIGNAL</strong><span>Daily Intelligence</span></div><nav>{''.join(nav_links)}</nav></div></header>
  <main>
    <section class="hero">
      <div class="hero-top"><div class="edition">Night Signal</div><div class="date">{html.escape(display_date)}</div></div>
      <div><h1>NIGHT SIGNAL</h1><p>{hero_copy}</p><div class="hero-meta"><span class="hero-chip">Web</span><span class="hero-chip">SNS/X</span><span class="hero-chip">Instagram</span><span class="hero-chip">Facebook</span><span class="hero-chip">YouTube</span><span class="hero-chip">Data</span></div></div>
    </section>
    <section class="section" id="priority">
      <div class="section-head"><h2>Priority</h2><p>{len(cards)} updates</p></div>
      <div class="priority">
{priority}
      </div>
    </section>
    <section class="section" id="category_updates">
      <div class="section-head"><h2>カテゴリ別新着</h2><p>新着{len(signals)}件</p></div>
      <div class="category-update-list">
{rendered_signals}
      </div>
    </section>
{chr(10).join(sections)}
  </main>
</body>
</html>
"""


def render_extraction_log(issue: dict[str, Any]) -> str:
    issue_date = require_str(issue, "issue_date")
    checked = issue.get("last_checked_jst") or datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")
    manifest = issue.get("coverage_manifest")
    if not isinstance(manifest, dict):
        fail("issue state missing coverage_manifest object")
    manifest = dict(manifest)
    manifest["date"] = issue_date
    manifest.setdefault("last_checked_jst", checked)
    contract = read_json(CONFIG_PATH)
    categories = [
        category["label"]
        for category in contract.get("categories", [])
        if isinstance(category, dict) and isinstance(category.get("label"), str)
    ]
    category_text = "、".join(categories)
    manifest.setdefault("contract_version", contract.get("contract_version"))
    manifest_json = json.dumps(manifest, ensure_ascii=False, indent=2)
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    heading = f"{issue_dt.year}年{issue_dt.month}月{issue_dt.day}日版の抽出ログ"
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>抽出ログ {html.escape(issue_date)} | NIGHT SIGNAL</title><link rel="stylesheet" href="_style.css"></head>
<body><main><a class="back" href="../index.html">一覧へ戻る</a><article class="article"><div class="kicker">Coverage Log</div><h1>{heading}</h1>
<p>Web、SNS/X、Instagram、Facebook、YouTubeをカテゴリ別・探索軸別に横断し、公式、主要報道、専門媒体、データ、予定、反証をカテゴリごとに記録した。対象カテゴリ: {html.escape(category_text)}。</p>
<h2>分類</h2><ul><li>公式 / 主要報道 / 専門媒体 / SNS/X / Instagram / Facebook / YouTube / データ / 予定 / 反証 を各カテゴリで記録。</li><li>採用 / 保留 / 除外 / 未確認 はcoverage-manifestに保存した。</li><li>new_or_changed_items と no_change_checks はカテゴリごとに記録し、掲載項目のURLは詳細ページの原文確認と重ねた。</li></ul>
<script type="application/json" id="coverage-manifest">{manifest_json}</script></article></main></body></html>
"""


def validate_frontier(issue: dict[str, Any]) -> list[dict[str, Any]]:
    expected = build_frontier(read_json(CONFIG_PATH))
    frontier = require_list(issue, "frontier")
    if len(frontier) != len(expected):
        fail(f"frontier count mismatch in issue state: {len(frontier)} != {len(expected)}")
    expected_keys = {(item["category"], item["watch_topic_id"]) for item in expected}
    actual_keys = {
        (str(item.get("category")), str(item.get("watch_topic_id")))
        for item in frontier
        if isinstance(item, dict)
    }
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        fail(f"frontier does not match coverage contract: missing={missing[:5]}, extra={extra[:5]}")
    return expected


def validate_observation_records(observations: list[Any], frontier: list[dict[str, Any]]) -> dict[str, Any]:
    closed_states = {"observed_live", "reused_from_cache", "source_unavailable", "not_applicable"}
    allowed_roles = {"primary_or_official", "independent_media_or_data", "social_or_video_signal"}
    allowed_channels = {"web", "sns_x", "instagram", "facebook", "youtube", "data", "calendar"}
    source_registry = load_source_registry()
    for index, observation in enumerate(observations, start=1):
        if not isinstance(observation, dict):
            fail(f"observations[{index}] must be an object")
        for key in ("category", "watch_topic_id", "source_role", "channel", "slot_state", "url", "observed_at_jst", "evidence_summary"):
            if not isinstance(observation.get(key), str) or not observation[key].strip():
                fail(f"observations[{index}] missing required string: {key}")
        if observation["source_role"] not in allowed_roles:
            fail(f"observations[{index}] invalid source_role: {observation['source_role']}")
        if observation["channel"] not in allowed_channels:
            fail(f"observations[{index}] invalid channel: {observation['channel']}")
        if observation["slot_state"] not in closed_states:
            fail(f"observations[{index}] invalid slot_state: {observation['slot_state']}")
        target_results = observation.get("source_target_results")
        if not isinstance(target_results, list) or not target_results:
            fail(f"observations[{index}] source_target_results must be a non-empty list")
        result_urls: set[str] = set()
        for result_index, result in enumerate(target_results, start=1):
            if not isinstance(result, dict):
                fail(f"observations[{index}] source_target_results[{result_index}] must be an object")
            for key in ("label", "url", "channel", "slot_state", "evidence_summary"):
                if not isinstance(result.get(key), str) or not result[key].strip():
                    fail(f"observations[{index}] source_target_results[{result_index}] missing required string: {key}")
            if result["channel"] not in allowed_channels:
                fail(f"observations[{index}] source_target_results[{result_index}] invalid channel: {result['channel']}")
            if result["slot_state"] not in closed_states:
                fail(f"observations[{index}] source_target_results[{result_index}] invalid slot_state: {result['slot_state']}")
            if not result["url"].startswith(("http://", "https://")):
                fail(f"observations[{index}] source_target_results[{result_index}] url must be absolute")
            result_urls.add(result["url"])
        expected_targets = source_targets_for_slot(source_registry, observation)
        missing_targets = [target["url"] for target in expected_targets if target["url"] not in result_urls]
        if missing_targets:
            fail(f"observations[{index}] missing source target results: " + ", ".join(missing_targets[:6]))
        claim_atoms = observation.get("claim_atoms")
        if not isinstance(claim_atoms, list):
            fail(f"observations[{index}] claim_atoms must be a list")

    state = coverage_state(observations)
    if state["missing_slots"]:
        first = state["missing_slots"][0]
        fail(
            "collection state has unclosed observation slots; first missing "
            f"{first['category']} / {first['watch_topic_id']} / {first['source_role']} / {first['channel']}"
        )
    return state


def validate_observations(issue: dict[str, Any], frontier: list[dict[str, Any]]) -> list[dict[str, Any]]:
    observations = require_list(issue, "observations")
    validate_observation_records(observations, frontier)
    return observations


def validate_candidates(issue: dict[str, Any], frontier: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_date = require_str(issue, "issue_date")
    contract = read_json(CONFIG_PATH)
    candidates = require_list(issue, "candidates")
    watch_keys = {(item["category"], item["watch_topic_id"]) for item in frontier}
    seen_by_topic = {key: 0 for key in watch_keys}
    allowed_change = {"new_event", "material_update", "routine_recurring", "duplicate_followup", "background_only"}
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            fail(f"candidates[{index}] must be an object")
        category = require_str(candidate, "category")
        topic = require_str(candidate, "watch_topic_id")
        key = (category, topic)
        if key not in watch_keys:
            fail(f"candidates[{index}] is outside coverage contract: {category}/{topic}")
        seen_by_topic[key] += 1
        title = require_str(candidate, "title")
        require_str(candidate, "source_published_date")
        summary = require_str(candidate, "summary")
        if effective_on_or_after(contract, "public_copy_contract_effective_date", issue_date):
            reject_public_copy(f"candidates[{index}].title", title, kind="title")
            reject_public_copy(f"candidates[{index}].summary", summary, kind="summary")
        if candidate.get("change_class") not in allowed_change:
            fail(f"candidates[{index}] invalid change_class")
        source_urls = candidate.get("source_urls")
        if not isinstance(source_urls, list) or not source_urls or any(not isinstance(url, str) or not url.startswith(("http://", "https://")) for url in source_urls):
            fail(f"candidates[{index}] source_urls must contain absolute URLs")
        facts = candidate.get("material_facts")
        if not isinstance(facts, list):
            fail(f"candidates[{index}] material_facts must be a list")
        if not isinstance(candidate.get("counter_evidence_checked"), bool):
            fail(f"candidates[{index}] counter_evidence_checked must be boolean")
    missing = [f"{category}/{topic}" for (category, topic), count in sorted(seen_by_topic.items()) if count == 0]
    if missing:
        fail("candidates missing watch topics: " + ", ".join(missing[:10]))
    return candidates


def validate_decisions_and_cards(issue: dict[str, Any], candidates: list[dict[str, Any]], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = require_list(issue, "decisions")
    candidate_titles = {str(candidate.get("title")) for candidate in candidates}
    adopted_titles: list[str] = []
    allowed_values = set(TOPIC_DECISION_SCHEMA["properties"]["topic_value_class"]["enum"])
    for index, decision in enumerate(decisions, start=1):
        if not isinstance(decision, dict):
            fail(f"decisions[{index}] must be an object")
        title = require_str(decision, "candidate_title")
        if title not in candidate_titles:
            fail(f"decisions[{index}] references unknown candidate: {title}")
        adoption = decision.get("adoption_decision")
        if adoption not in {"adopt", "reject"}:
            fail(f"decisions[{index}] invalid adoption_decision")
        if decision.get("topic_value_class") not in allowed_values:
            fail(f"decisions[{index}] invalid topic_value_class")
        require_str(decision, "reader_delta")
        require_str(decision, "materiality_basis")
        if adoption == "adopt":
            adopted_titles.append(title)
        elif not decision.get("reject_reason_class") or not decision.get("reject_reason"):
            fail(f"decisions[{index}] rejected item needs reject reason")

    card_candidate_titles = [str(card.get("candidate_title")) for card in cards]
    if sorted(card_candidate_titles) != sorted(adopted_titles):
        fail(f"cards must reference adopted decisions: cards={card_candidate_titles}, adopted={adopted_titles}")
    public_titles = [str(card.get("title")) for card in cards]
    if len(public_titles) != len(set(public_titles)):
        fail("cards must have unique public titles")
    return decisions


def validate_manifest_alignment(issue: dict[str, Any], cards: list[dict[str, Any]]) -> None:
    manifest = issue.get("coverage_manifest")
    if not isinstance(manifest, dict):
        fail("issue state missing coverage_manifest object")
    categories = manifest.get("categories")
    if not isinstance(categories, dict):
        fail("coverage_manifest missing categories object")
    contract = read_json(CONFIG_PATH)
    issue_date = require_str(issue, "issue_date")
    if effective_on_or_after(contract, "detail_information_contract_effective_date", issue_date):
        expected_version = contract.get("contract_version")
        if manifest.get("contract_version") != expected_version:
            fail(f"coverage_manifest contract_version must be {expected_version}")
    cards_by_section: dict[str, list[str]] = {}
    for card in cards:
        cards_by_section.setdefault(str(card.get("section_id")), []).append(str(card.get("title")))
    for category in contract.get("categories", []):
        if not isinstance(category, dict):
            continue
        label = str(category.get("label"))
        section_id = str(category.get("section_id"))
        entry = categories.get(label)
        if not isinstance(entry, dict):
            fail(f"coverage_manifest missing category: {label}")
        published = entry.get("published_card_titles")
        if published != cards_by_section.get(section_id, []):
            fail(f"{label} published_card_titles must match adopted cards")
        for key in ("new_or_changed_items", "no_change_checks", "latest_candidates"):
            if not isinstance(entry.get(key), list):
                fail(f"{label} coverage_manifest missing list: {key}")


def validate_issue_state(issue: dict[str, Any], issue_path: Path | None = None) -> None:
    issue_date = require_str(issue, "issue_date")
    if issue_path and issue_path.parent.name.startswith("20") and issue_path.parent.name != issue_date:
        fail(f"issue_date does not match state directory: {issue_date} != {issue_path.parent.name}")
    if issue.get("state") not in STATE_NAMES:
        fail("issue state has invalid state name")
    blockers = require_list(issue, "blockers")
    if blockers:
        fail("issue state still has blockers: " + "; ".join(str(item) for item in blockers))
    frontier = validate_frontier(issue)
    validate_observations(issue, frontier)
    candidates = validate_candidates(issue, frontier)
    cards = normalized_cards(issue)
    validate_decisions_and_cards(issue, candidates, cards)
    validate_manifest_alignment(issue, cards)


def assemble_issue_state(issue_date: str, state_root: Path, output_path: Path | None = None) -> dict[str, Any]:
    state_dir = state_root / issue_date
    if not state_dir.exists():
        fail(f"missing state directory: {display_path(state_dir)}")
    observations = read_json_records(records_path(state_dir, "observations"))
    candidates = read_json_records(records_path(state_dir, "candidates"))
    decisions = read_json_records(records_path(state_dir, "decisions"))
    cards = read_json_records(records_path(state_dir, "cards"))
    manifest = read_json(state_dir / "coverage_manifest.json")
    issue = {
        "issue_date": issue_date,
        "state": "publication_ready",
        "frontier": build_frontier(read_json(CONFIG_PATH)),
        "observations": observations,
        "candidates": candidates,
        "decisions": decisions,
        "cards": cards,
        "coverage_manifest": manifest,
        "blockers": [],
    }
    validate_issue_state(issue, state_dir / "issue.json")
    output = output_path or (state_dir / "issue.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(issue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"issue_date": issue_date, "issue_state": str(output), "cards": len(cards), "observations": len(observations)}


def generate_issue(issue_path: Path, output_root: Path, *, write_marker: bool) -> dict[str, Any]:
    issue = read_json(issue_path)
    validate_issue_state(issue, issue_path)
    issue_date = require_str(issue, "issue_date")
    cards = normalized_cards(issue)
    details_dir = output_root / "details"
    details_dir.mkdir(parents=True, exist_ok=True)

    for card in cards:
        detail = dict(card["detail"])
        detail.setdefault("issue_date", issue_date)
        detail.setdefault("section_id", card["section_id"])
        detail.setdefault("kicker", card["category"])
        detail.setdefault("title", card["title"])
        detail.setdefault("h1", card["title"])
        detail.setdefault("summary", card["summary"])
        (details_dir / card["slug"]).write_text(render_detail_html(detail), encoding="utf-8")

    (output_root / f"night-brief-web-sample-{issue_date}.html").write_text(
        render_issue_html(issue, cards, root=False),
        encoding="utf-8",
    )
    (details_dir / f"extraction-log-{issue_date}.html").write_text(render_extraction_log(issue), encoding="utf-8")
    if write_marker:
        (output_root / ".night-signal-issue-date").write_text(issue_date + "\n", encoding="utf-8")
    return {
        "issue_date": issue_date,
        "cards": len(cards),
        "sample_html": str(output_root / f"night-brief-web-sample-{issue_date}.html"),
        "extraction_log": str(details_dir / f"extraction-log-{issue_date}.html"),
        "marker_written": write_marker,
    }


def required_observation_slots(frontier: list[dict[str, Any]]) -> list[dict[str, str]]:
    slots: list[dict[str, str]] = []
    for item in frontier:
        category = str(item["category"])
        watch_topic_id = str(item["watch_topic_id"])
        channels = item.get("required_channels", [])
        if not isinstance(channels, list):
            fail(f"{category} {watch_topic_id} required_channels must be a list")
        slots.append(
            efficient_slot(
                category=category,
                watch_topic_id=watch_topic_id,
                source_role="primary_or_official",
                channel="web",
            )
        )
        slots.append(
            efficient_slot(
                category=category,
                watch_topic_id=watch_topic_id,
                source_role="independent_media_or_data",
                channel="web",
            )
        )
        for channel in channels:
            if channel in {"sns_x", "instagram", "facebook", "youtube"}:
                slots.append(
                    efficient_slot(
                        category=category,
                        watch_topic_id=watch_topic_id,
                        source_role="social_or_video_signal",
                        channel=channel,
                    )
                )
    return slots


def slug_text(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "-", value.lower()).strip("-")
    if normalized:
        return normalized
    return "u" + hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def slot_id(slot: dict[str, str]) -> str:
    return "-".join(
        [
            slug_text(slot["category"]),
            slug_text(slot["watch_topic_id"]),
            slug_text(slot["source_role"]),
            slug_text(slot["channel"]),
        ]
    )


def compact_terms(terms: list[str], limit: int = 10) -> list[str]:
    seen: list[str] = []
    for term in terms:
        normalized = term.strip()
        if len(normalized) < 2 or normalized.lower() in {item.lower() for item in seen}:
            continue
        seen.append(normalized)
        if len(seen) >= limit:
            break
    return seen


def role_query_terms(source_role: str, channel: str) -> list[str]:
    if source_role == "primary_or_official":
        return ["official", "IR", "newsroom", "release"]
    if source_role == "independent_media_or_data":
        return ["Reuters", "Bloomberg", "Nikkei", "specialist media", "data"]
    if channel == "sns_x":
        return ["site:x.com", "official x", "latest"]
    if channel == "instagram":
        return ["site:instagram.com", "official instagram", "latest"]
    if channel == "facebook":
        return ["site:facebook.com", "official facebook", "latest"]
    if channel == "youtube":
        return ["site:youtube.com", "official channel", "latest video"]
    return ["social", "official account", "latest"]


def build_search_queries(issue_date: str, frontier_item: dict[str, Any], slot: dict[str, str]) -> list[str]:
    terms = compact_terms([str(item) for item in frontier_item.get("search_terms", []) if isinstance(item, str)])
    base = " ".join([slot["category"], slot["watch_topic_id"], *terms[:6]])
    role_terms = " ".join(role_query_terms(slot["source_role"], slot["channel"]))
    channel = slot["channel"]
    return [
        f"{base} {role_terms} {channel} {issue_date}",
        f"{slot['category']} {slot['watch_topic_id']} latest update {role_terms} {issue_date}",
    ]


def load_source_registry() -> dict[str, list[dict[str, str]]]:
    registry = read_json(SOURCES_PATH)
    categories = registry.get("categories")
    if not isinstance(categories, dict):
        fail("source registry missing categories")
    normalized: dict[str, list[dict[str, str]]] = {}
    for category, targets in categories.items():
        if not isinstance(category, str) or not isinstance(targets, list):
            fail("source registry categories must map labels to target lists")
        normalized_targets: list[dict[str, str]] = []
        for index, target in enumerate(targets, start=1):
            if not isinstance(target, dict):
                fail(f"source registry {category}[{index}] must be an object")
            normalized_target = {}
            for key in ("label", "url", "source_role", "channel", "source_class"):
                value = target.get(key)
                if not isinstance(value, str) or not value.strip():
                    fail(f"source registry {category}[{index}] missing {key}")
                normalized_target[key] = value.strip()
            if not normalized_target["url"].startswith(("https://", "http://")):
                fail(f"source registry {category}[{index}] url must be absolute")
            normalized_targets.append(normalized_target)
        normalized[category] = normalized_targets
    return normalized


def target_matches_slot(target: dict[str, str], slot: dict[str, str]) -> bool:
    if target["source_role"] != slot["source_role"]:
        return False
    if slot["source_role"] == "social_or_video_signal":
        # One social slot keeps collection efficient; source_target_results then
        # proves X, Instagram, and Facebook were each closed at URL level.
        if slot["channel"] == "sns_x":
            return target["channel"] in {"sns_x", "instagram", "facebook"}
        return target["channel"] == slot["channel"]
    return target["channel"] == slot["channel"]


def source_targets_for_slot(registry: dict[str, list[dict[str, str]]], slot: dict[str, str]) -> list[dict[str, str]]:
    targets = [target for target in registry.get(slot["category"], []) if target_matches_slot(target, slot)]
    if not targets:
        fail(
            "collection task has no seed sources: "
            f"{slot['category']} / {slot['watch_topic_id']} / {slot['source_role']} / {slot['channel']}"
        )
    return targets


def task_acceptance(slot: dict[str, str]) -> dict[str, list[str]]:
    must_record = [
        "url_or_stable_source_id",
        "observed_at_jst",
        "published_date_or_null",
        "evidence_summary",
        "source_target_results_for_every_seed_target",
        "claim_atoms",
    ]
    if slot["source_role"] == "primary_or_official":
        must_record.append("official_or_primary_authority")
    if slot["source_role"] == "independent_media_or_data":
        must_record.append("independent_confirmation_or_data_basis")
    if slot["channel"] in {"sns_x", "instagram", "facebook", "youtube"}:
        must_record.append("social_or_video_post_context")
    return {
        "slot_closure_states": ["observed_live", "reused_from_cache", "source_unavailable", "not_applicable"],
        "must_record": must_record,
        "must_not_publish": [
            "rumor_without_primary_or_major_confirmation",
            "search_result_page_as_source",
            "schedule_only_without_material_change",
            "old_background_as_fresh_news",
        ],
    }


def batch_group(slot: dict[str, str]) -> str:
    return "-".join([slug_text(slot["model_route"]), slug_text(slot["priority"]), slug_text(slot["reuse_policy"])])


def prompt_cache_key(slot: dict[str, str]) -> str:
    return "-".join(["night-signal", "source-observation", slug_text(slot["model_route"]), slug_text(slot["source_role"]), slug_text(slot["channel"])])


def collection_plan(issue_date: str) -> dict[str, Any]:
    frontier = build_frontier(read_json(CONFIG_PATH))
    source_registry = load_source_registry()
    frontier_by_key = {(item["category"], item["watch_topic_id"]): item for item in frontier}
    tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for slot in required_observation_slots(frontier):
        frontier_item = frontier_by_key[(slot["category"], slot["watch_topic_id"])]
        task = {
            "issue_date": issue_date,
            "slot_id": slot_id(slot),
            "category": slot["category"],
            "section_id": str(frontier_item["section_id"]),
            "watch_topic_id": slot["watch_topic_id"],
            "source_role": slot["source_role"],
            "channel": slot["channel"],
            "priority": slot["priority"],
            "reuse_policy": slot["reuse_policy"],
            "model_route": slot["model_route"],
            "batch_group": batch_group(slot),
            "prompt_cache_key": prompt_cache_key(slot),
            "source_targets": source_targets_for_slot(source_registry, slot),
            "search_queries": build_search_queries(issue_date, frontier_item, slot),
            "acceptance": task_acceptance(slot),
            "output_schema": "source_observation",
        }
        if task["slot_id"] in seen_ids:
            fail(f"duplicate collection task slot_id: {task['slot_id']}")
        seen_ids.add(task["slot_id"])
        tasks.append(task)
    return {
        "issue_date": issue_date,
        "tasks": tasks,
        "source_observation_schema_ref": "source_observation",
    }


def write_collection_plan(issue_date: str, state_root: Path, output_path: Path | None = None) -> dict[str, Any]:
    plan = collection_plan(issue_date)
    output = output_path or (state_root / issue_date / "collection_plan.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    batch_counts = count_by(plan["tasks"], "batch_group")
    route_counts = count_by(plan["tasks"], "model_route")
    reuse_counts = count_by(plan["tasks"], "reuse_policy")
    priority_counts = count_by(plan["tasks"], "priority")
    return {
        "issue_date": issue_date,
        "collection_plan": str(output),
        "tasks": len(plan["tasks"]),
        "batch_group_counts": batch_counts,
        "model_route_counts": route_counts,
        "priority_counts": priority_counts,
        "reuse_policy_counts": reuse_counts,
    }


def efficient_slot(category: str, watch_topic_id: str, source_role: str, channel: str) -> dict[str, str]:
    high_velocity_categories = {"OpenAI", "SpaceX", "F1", "YOASOBI / 幾田りら", "宇都宮ブレックス"}
    market_topics = {"market_price_nav", "market_price_reaction", "us_markets_fund_flows_rates"}
    official_topics = {"prices_wages_boj", "official_launch_manifest", "product_release", "race_schedule_results"}

    priority = "normal"
    if category in high_velocity_categories and channel in {"sns_x", "youtube"}:
        priority = "high"
    if watch_topic_id in market_topics or watch_topic_id in official_topics:
        priority = "high"
    if source_role == "independent_media_or_data" and category in {"日本経済", "アジア経済", "北米経済"}:
        priority = "high"

    reuse_policy = "daily_fetch"
    if channel == "youtube" and priority != "high":
        reuse_policy = "reuse_24h_unless_primary_changed"
    if source_role == "independent_media_or_data" and priority == "normal":
        reuse_policy = "reuse_12h_unless_candidate_changed"

    model_route = "small_structured_extractor"
    if priority == "high" and source_role == "primary_or_official":
        model_route = "frontier_reasoning_model"
    if priority == "high" and source_role == "social_or_video_signal":
        model_route = "small_structured_extractor_then_frontier_reasoning_if_ambiguous"

    return {
        "category": category,
        "watch_topic_id": watch_topic_id,
        "source_role": source_role,
        "channel": channel,
        "priority": priority,
        "reuse_policy": reuse_policy,
        "model_route": model_route,
    }


def observation_key(observation: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(observation.get("category", "")),
        str(observation.get("watch_topic_id", "")),
        str(observation.get("source_role", "")),
        str(observation.get("channel", "")),
    )


def coverage_state(observations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    frontier = build_frontier(read_json(CONFIG_PATH))
    slots = required_observation_slots(frontier)
    observations = observations or []
    closed_states = {"observed_live", "reused_from_cache", "source_unavailable", "not_applicable"}
    observed = {
        observation_key(item)
        for item in observations
        if isinstance(item, dict) and item.get("slot_state") in closed_states
    }
    missing = [
        slot
        for slot in slots
        if (
            slot["category"],
            slot["watch_topic_id"],
            slot["source_role"],
            slot["channel"],
        )
        not in observed
    ]
    priority_counts = count_by(slots, "priority")
    reuse_counts = count_by(slots, "reuse_policy")
    model_route_counts = count_by(slots, "model_route")
    return {
        "frontier_count": len(frontier),
        "required_observation_slots": len(slots),
        "observed_slots": len(slots) - len(missing),
        "priority_counts": priority_counts,
        "reuse_policy_counts": reuse_counts,
        "model_route_counts": model_route_counts,
        "missing_slots": missing,
        "collection_complete": not missing,
    }


def count_by(items: list[dict[str, str]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = item.get(key, "unknown")
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def print_coverage_summary(value: dict[str, Any]) -> None:
    categories: dict[str, int] = {}
    for slot in value["missing_slots"]:
        categories[slot["category"]] = categories.get(slot["category"], 0) + 1
    print(
        json.dumps(
            {
                "collection_complete": value["collection_complete"],
                "frontier_count": value["frontier_count"],
                "required_observation_slots": value["required_observation_slots"],
                "observed_slots": value["observed_slots"],
                "missing_slots": len(value["missing_slots"]),
                "missing_slots_by_category": dict(sorted(categories.items())),
                "model_route_counts": value["model_route_counts"],
                "priority_counts": value["priority_counts"],
                "reuse_policy_counts": value["reuse_policy_counts"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def collection_plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    tasks = plan["tasks"]
    return {
        "issue_date": plan["issue_date"],
        "tasks": len(tasks),
        "batch_group_counts": count_by(tasks, "batch_group"),
        "model_route_counts": count_by(tasks, "model_route"),
        "priority_counts": count_by(tasks, "priority"),
        "reuse_policy_counts": count_by(tasks, "reuse_policy"),
    }


def self_test() -> None:
    contract = read_json(CONFIG_PATH)
    frontier = build_frontier(contract)
    categories = contract.get("categories", [])
    topic_count = sum(len(category.get("watch_topics", [])) for category in categories if isinstance(category, dict))
    if len(frontier) != topic_count:
        fail(f"frontier count mismatch: {len(frontier)} != {topic_count}")
    for name, schema in SCHEMAS.items():
        if schema.get("type") != "object" or not schema.get("required"):
            fail(f"{name} schema is not strict enough")
    coverage = coverage_state([])
    plan = collection_plan("2099-01-01")
    if coverage["required_observation_slots"] <= len(frontier):
        fail("observation slots must expand source roles/channels beyond watch topics")
    if len(plan["tasks"]) != coverage["required_observation_slots"]:
        fail("collection plan must map one task to each required observation slot")
    if len({task["slot_id"] for task in plan["tasks"]}) != len(plan["tasks"]):
        fail("collection plan slot_id values must be unique")
    if any(not task.get("source_targets") for task in plan["tasks"]):
        fail("collection plan tasks must include seed source targets")
    social_tasks = [
        task
        for task in plan["tasks"]
        if task["source_role"] == "social_or_video_signal" and task["channel"] == "sns_x"
    ]
    if not any(any(target["channel"] == "instagram" for target in task["source_targets"]) for task in social_tasks):
        fail("social source tasks must include Instagram seed targets when configured")
    if not any(any(target["channel"] == "facebook" for target in task["source_targets"]) for task in social_tasks):
        fail("social source tasks must include Facebook seed targets when configured")
    if any("source_target_results_for_every_seed_target" not in task["acceptance"]["must_record"] for task in plan["tasks"]):
        fail("collection plan tasks must require source target result closure")
    if "source_target_results" not in SOURCE_OBSERVATION_SCHEMA["required"]:
        fail("source observations must record per-target results")
    if coverage["collection_complete"]:
        fail("empty observations must not be collection-complete")
    if coverage["priority_counts"].get("high", 0) <= 0:
        fail("coverage state must identify high-priority slots")
    if coverage["reuse_policy_counts"].get("reuse_24h_unless_primary_changed", 0) <= 0:
        fail("coverage state must identify reusable low-change slots")
    if not public_copy_violations("品質ゲートで確認して作業する", kind="summary"):
        fail("public copy guard must reject process wording")
    clean_title_violations = public_copy_violations("OpenAI、Codexの共有機能を追加", kind="title")
    if clean_title_violations:
        fail("public copy guard rejected a reader-facing title: " + "; ".join(clean_title_violations))
    validate_decisions_and_cards(
        {
            "decisions": [
                {
                    "candidate_title": "OpenAI Codex sharing candidate",
                    "adoption_decision": "adopt",
                    "topic_value_class": "technical_or_product_shift",
                    "reader_delta": "共有機能の追加により、開発チームで記録内容を確認しやすくなる。",
                    "materiality_basis": "公式発表で新しい機能追加を確認できる。",
                    "reject_reason_class": None,
                    "reject_reason": None,
                }
            ]
        },
        [{"title": "OpenAI Codex sharing candidate"}],
        [{"candidate_title": "OpenAI Codex sharing candidate", "title": "OpenAI、Codexに共有機能を追加"}],
    )
    rendered = render_detail_html(
        {
            "issue_date": "2099-01-01",
            "section_id": "openai",
            "kicker": "OpenAI",
            "title": "OpenAI、Codexの共有機能を追加",
            "h1": "OpenAI、Codexの共有機能を追加",
            "summary": "OpenAIがCodexの共有機能を追加し、チーム内で記録内容を共有しやすくした。",
            "summary_basis": {
                "what_changed": "OpenAIがCodexの共有機能を追加した。",
                "why_it_matters": "開発チームが記録内容を同じ画面で共有しやすくなる。",
                "confirmed_facts": [
                    "OpenAIがCodexの共有機能を発表した。",
                    "共有対象はCodexの記録内容で、チーム利用を想定している。",
                ],
                "limits_or_unknowns": "提供範囲や利用条件は公式発表の範囲で確認済みの内容に限る。",
                "source_dates": ["2099-01-01"],
            },
            "sources": [{"label": "OpenAI公式", "url": "https://openai.com/"}],
        }
    )
    if "30秒概要" in rendered or "要点と背景" not in rendered or "確認した事実" not in rendered or "未確定点" not in rendered:
        fail("detail renderer must use the current information-complete structure")
    signal_issue = {
        "issue_date": "2099-01-03",
        "candidates": [
            {
                "category": "OpenAI",
                "title": "OpenAI、Codexに共有機能を追加",
                "source_published_date": "2099-01-03",
                "summary": "OpenAIがCodexの共有機能を追加し、チーム内で記録内容を共有しやすくした。",
            },
            {
                "category": "Honda",
                "title": "Honda、中国販売の月次減少を確認",
                "source_published_date": "2099-01-02",
                "summary": "Hondaの中国販売に月次で大きな減少があり、市場環境と日本勢の苦戦を読む材料になる。",
            },
            {
                "category": "SpaceX",
                "title": "SpaceX、古い発射実績を背景資料に残す",
                "source_published_date": "2098-12-30",
                "summary": "3日より古い情報は公開候補ボードには出さず、背景資料に留める。",
            },
        ],
        "decisions": [
            {"candidate_title": "OpenAI、Codexに共有機能を追加", "adoption_decision": "adopt"},
            {"candidate_title": "Honda、中国販売の月次減少を確認", "adoption_decision": "reject"},
            {"candidate_title": "SpaceX、古い発射実績を背景資料に残す", "adoption_decision": "reject"},
        ],
    }
    signal_cards = [
        {
            "candidate_title": "OpenAI、Codexに共有機能を追加",
            "title": "OpenAI、Codexに共有機能を追加",
            "summary": "OpenAIがCodexの共有機能を追加し、チーム内で記録内容を共有しやすくした。",
            "section_id": "openai",
            "category": "OpenAI",
            "source_published_date": "2099-01-03",
            "topic_value_class": "technical_or_product_shift",
            "priority_class": "signal",
            "issue_date": "2099-01-03",
            "slug": "openai-codex-sharing-2099-01-03.html",
            "freshness_label": "今日",
        }
    ]
    signal_items = signal_board_items(signal_issue, signal_cards)
    signal_titles = [item["title"] for item in signal_items]
    if signal_titles != ["OpenAI、Codexに共有機能を追加", "Honda、中国販売の月次減少を確認"]:
        fail("category updates must show latest-three-day candidates in configured category order")
    signal_html = render_issue_html(signal_issue, signal_cards, root=False)
    if "カテゴリ別新着" not in signal_html or "一覧のみ" not in signal_html or "古い発射実績" in signal_html:
        fail("issue renderer must expose broad fresh candidates by configured category without stale background items")
    print("NIGHT SIGNAL STATE PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", choices=sorted(SCHEMAS))
    parser.add_argument("--frontier", action="store_true")
    parser.add_argument("--collection-plan", action="store_true")
    parser.add_argument("--coverage-state", action="store_true")
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--readiness", action="store_true")
    parser.add_argument("--date", default=jst_today())
    parser.add_argument("--allow-blocked", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write-collection-plan")
    parser.add_argument("--validate-observations", type=Path)
    parser.add_argument("--generate-issue", type=Path)
    parser.add_argument("--validate-issue", type=Path)
    parser.add_argument("--assemble-issue-state")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-marker", action="store_true")
    args = parser.parse_args()

    if args.schema:
        print_json(SCHEMAS[args.schema])
        return 0
    if args.frontier:
        print_json(build_frontier(read_json(CONFIG_PATH)))
        return 0
    if args.collection_plan:
        plan = collection_plan(args.date)
        print_json(collection_plan_summary(plan) if args.summary else plan)
        return 0
    if args.coverage_state:
        observations = read_json_records(args.observations) if args.observations else []
        state = coverage_state(observations)
        if args.summary:
            print_coverage_summary(state)
        else:
            print_json(state)
        return 0
    if args.readiness:
        state = readiness(args.date)
        print_json(state)
        if state["blockers"] and not args.allow_blocked:
            return 1
        return 0
    if args.generate_issue:
        print_json(generate_issue(args.generate_issue, args.output_root, write_marker=not args.no_marker))
        return 0
    if args.write_collection_plan:
        print_json(write_collection_plan(args.write_collection_plan, args.state_root, args.output))
        return 0
    if args.validate_observations:
        observations = read_json_records(args.validate_observations)
        state = validate_observation_records(observations, build_frontier(read_json(CONFIG_PATH)))
        print_json(
            {
                "observations": str(args.validate_observations),
                "valid": True,
                "observed_slots": state["observed_slots"],
                "required_observation_slots": state["required_observation_slots"],
            }
        )
        return 0
    if args.validate_issue:
        validate_issue_state(read_json(args.validate_issue), args.validate_issue)
        print_json({"issue_state": str(args.validate_issue), "valid": True})
        return 0
    if args.assemble_issue_state:
        print_json(assemble_issue_state(args.assemble_issue_state, args.state_root, args.output))
        return 0
    if args.self_test:
        self_test()
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
