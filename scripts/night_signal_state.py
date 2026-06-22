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
LIVE_EVIDENCE_CONTRACT_DATE = "2026-06-13"

STATE_NAMES = [
    "frontier_built",
    "observations_collected",
    "candidates_normalized",
    "topic_value_decided",
    "issue_rendered",
    "publication_ready",
]

MATERIAL_SIGNAL_RE = re.compile(
    r"("
    r"\d+(?:\.\d+)?\s*(?:%|％|億|兆|万|ドル|円|bps|bp)|"
    r"bond|bonds|社債|債券|debt|loan|bridge loan|借り換え|資金調達|"
    r"rating|ratings|格付|投資適格|investment grade|Baa|BBB|"
    r"market share|シェア|share falls|50%|50％|"
    r"target price|price target|目標株価|buy rating|sell rating|"
    r"IPO|上場|Nasdaq|時価総額|valuation|"
    r"merger|合併|統合|tie-up|acquisition|買収|M&A|"
    r"hire|hiring|joins|leaves|departing|移籍|獲得|退社|人材|"
    r"契約|受注|提携|partnership|contract|"
    r"launch result|打ち上げ結果|docking|ドッキング|"
    r"policy|regulation|規制|安全|recall|リコール"
    r")",
    re.I,
)

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
CANDIDATE_PLACEHOLDER_PATTERNS = [
    r"直近確認",
    r"確定差分は不足",
    r"単独記事にする確定差分",
    r"公式・媒体・SNS系の証跡で確認した",
]

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
        "discovery_findings",
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
                "required": [
                    "label",
                    "url",
                    "channel",
                    "slot_state",
                    "published_date",
                    "evidence_summary",
                    "checked_at_jst",
                    "verification_method",
                ],
                "properties": {
                    "label": {"type": "string"},
                    "url": {"type": "string"},
                    "channel": {"type": "string", "enum": ["web", "sns_x", "instagram", "facebook", "youtube", "data", "calendar"]},
                    "slot_state": {"type": "string", "enum": ["observed_live", "reused_from_cache", "source_unavailable", "not_applicable"]},
                    "published_date": {"type": ["string", "null"]},
                    "evidence_summary": {"type": "string"},
                    "checked_at_jst": {"type": "string"},
                    "verification_method": {
                        "type": "string",
                        "enum": [
                            "responses_web_search",
                            "reviewed_live_web",
                            "direct_fetch",
                            "cached_result",
                            "unavailable",
                        ],
                    },
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
        "discovery_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "summary", "source_url", "published_date", "suggested_watch_topic_id"],
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "source_url": {"type": "string"},
                    "published_date": {"type": ["string", "null"]},
                    "suggested_watch_topic_id": {"type": "string"},
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
        "fact_sources",
        "limits_or_unknowns",
        "source_dates",
    ],
    "properties": {
        "what_changed": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "confirmed_facts": {"type": "array", "items": {"type": "string"}},
        "fact_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["fact", "source_urls"],
                "properties": {
                    "fact": {"type": "string"},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
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
        "watch_topics",
        "source_role",
        "channel",
        "priority",
        "reuse_policy",
        "model_route",
        "batch_group",
        "prompt_cache_key",
        "hypotheses",
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
        "watch_topics": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["watch_topic_id", "search_terms", "required_channels"],
                "properties": {
                    "watch_topic_id": {"type": "string"},
                    "search_terms": {"type": "array", "items": {"type": "string"}},
                    "required_channels": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "source_role": {"type": "string"},
        "channel": {"type": "string"},
        "priority": {"type": "string"},
        "reuse_policy": {"type": "string"},
        "model_route": {"type": "string"},
        "batch_group": {"type": "string"},
        "prompt_cache_key": {"type": "string"},
        "hypotheses": {"type": "array", "items": {"type": "string"}},
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
        axis_terms = [term for axis in axes if isinstance(axis, dict) for term in axis.get("terms", []) if isinstance(term, str)]
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
                    "search_terms": compact_terms(topic_terms + axis_terms, limit=24),
                    "event_classes": sorted(
                        {
                            value
                            for value in topic.get("event_classes", [])
                            if isinstance(value, str)
                        }
                    ),
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
    issue_path = state_dir / "issue.json"
    issue: dict[str, Any] = {}
    if issue_path.exists():
        try:
            loaded = json.loads(issue_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                issue = loaded
        except json.JSONDecodeError:
            issue = {}
    return {
        "collection_plan": (state_dir / "collection_plan.json").exists(),
        "observations": records_file_exists(state_dir, "observations") or isinstance(issue.get("observations"), list),
        "candidates": records_file_exists(state_dir, "candidates") or isinstance(issue.get("candidates"), list),
        "decisions": records_file_exists(state_dir, "decisions") or isinstance(issue.get("decisions"), list),
        "cards": records_file_exists(state_dir, "cards") or isinstance(issue.get("cards"), list),
        "coverage_manifest": (state_dir / "coverage_manifest.json").exists() or isinstance(issue.get("coverage_manifest"), dict),
        "state_issue_json": issue_path.exists(),
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


def expected_contract_version(contract: dict[str, Any], issue_date: str) -> str | None:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    for legacy in contract.get("legacy_contract_versions", []):
        if not isinstance(legacy, dict):
            continue
        try:
            through = datetime.strptime(str(legacy.get("through_date")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if issue_dt <= through:
            return str(legacy.get("version"))
    value = contract.get("contract_version")
    return str(value) if value is not None else None


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
    if effective_on_or_after(contract, "detail_depth_effective_date", issue_date):
        min_facts = int(contract.get("minimum_current_material_facts_per_published_item", 3))
    else:
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

    if effective_on_or_after(contract, "claim_source_linkage_effective_date", issue_date):
        fact_sources = basis.get("fact_sources")
        if not isinstance(fact_sources, list) or len(fact_sources) != len(facts):
            fail(f"cards[{card_index}].detail.summary_basis.fact_sources must cover every confirmed fact")
        detail_source_urls = {
            str(source.get("url"))
            for source in detail.get("sources", [])
            if isinstance(source, dict)
        }
        mapped_facts: set[str] = set()
        for mapping_index, mapping in enumerate(fact_sources, start=1):
            if not isinstance(mapping, dict):
                fail(f"cards[{card_index}].detail.summary_basis.fact_sources[{mapping_index}] must be an object")
            fact = require_str(mapping, "fact")
            source_urls = mapping.get("source_urls")
            if fact not in facts or fact in mapped_facts:
                fail(f"cards[{card_index}].detail.summary_basis.fact_sources[{mapping_index}] must map one unique confirmed fact")
            if (
                not isinstance(source_urls, list)
                or not source_urls
                or any(not isinstance(url, str) or url not in detail_source_urls for url in source_urls)
            ):
                fail(f"cards[{card_index}].detail.summary_basis.fact_sources[{mapping_index}] must use detail source URLs")
            mapped_facts.add(fact)

    source_dates = basis.get("source_dates")
    if not isinstance(source_dates, list) or not source_dates:
        fail(f"cards[{card_index}].detail.summary_basis.source_dates must contain source dates")
    normalized_dates = [str(value).strip() for value in source_dates if str(value).strip()]
    if source_date not in normalized_dates:
        fail(f"cards[{card_index}].detail.summary_basis.source_dates must include card source date {source_date}")


def content_terms(text: str) -> set[str]:
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9.+-]{2,}|\d+(?:\.\d+)?|[一-龯ァ-ヶー]{2,}", text))
    return {
        term.lower()
        for term in terms
        if term
        and term not in {
            "する",
            "した",
            "いる",
            "ある",
            "なる",
            "できる",
            "確認",
            "発表",
            "公開",
            "更新",
            "情報",
            "詳細",
            "背景",
        }
    }


def text_overlap(left: str, right: str) -> int:
    return len(content_terms(left) & content_terms(right))


def validate_card_candidate_binding(raw: dict[str, Any], candidate: dict[str, Any], *, card_index: int) -> None:
    candidate_title = require_str(raw, "candidate_title")
    card_title = require_str(raw, "title")
    card_summary = require_str(raw, "summary")
    detail = raw.get("detail")
    if not isinstance(detail, dict):
        fail(f"cards[{card_index}] missing detail object")
    detail_summary = require_str(detail, "summary")
    basis = detail.get("summary_basis")
    basis_text = ""
    if isinstance(basis, dict):
        basis_values: list[str] = []
        for key in ("what_changed", "why_it_matters", "limits_or_unknowns"):
            value = basis.get(key)
            if isinstance(value, str):
                basis_values.append(value)
        facts = basis.get("confirmed_facts")
        if isinstance(facts, list):
            basis_values.extend(str(fact) for fact in facts if isinstance(fact, str))
        basis_text = " ".join(basis_values)

    candidate_text = " ".join(
        str(candidate.get(key, ""))
        for key in ("title", "summary", "change_class", "source_published_date")
    )
    public_text = " ".join([card_summary, detail_summary, basis_text])
    if text_overlap(public_text, candidate_text) < 2:
        fail(f"cards[{card_index}] public copy is not bound to its candidate facts: {candidate_title}")
    if text_overlap(card_summary, detail_summary) < 2 and text_overlap(card_summary, basis_text) < 2:
        fail(f"cards[{card_index}] summary and detail describe different facts: {card_title}")


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


def normalize_public_summary(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text).strip())
    text = re.sub(r"[。．.]{2,}", "。", text)
    text = re.sub(r"([！？!?]){2,}", r"\1", text)
    parts = [part.strip() for part in re.split(r"(?<=[。！？!?])", text) if part.strip()]
    seen: set[str] = set()
    kept: list[str] = []
    for part in parts:
        key = re.sub(r"[、。．.!！?？\s「」『』（）()]", "", part).lower()
        if key and key in seen:
            continue
        seen.add(key)
        kept.append(part)
    return " ".join(kept) if kept else text


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
        summary = normalize_public_summary(require_str(raw, "summary"))
        section_id = require_str(raw, "section_id")
        category = require_str(raw, "category")
        source_date = require_str(raw, "source_published_date")
        detail = raw.get("detail")
        if not isinstance(detail, dict):
            fail(f"cards[{index}] missing detail object")
        slug = require_str(detail, "slug")
        detail = {**detail, "summary": normalize_public_summary(require_str(detail, "summary"))}
        raw_for_validation = {**raw, "summary": summary, "detail": detail}
        validate_public_card_copy(raw_for_validation, detail, issue_date=issue_date, card_index=index)
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
    issue_date = str(card["issue_date"])
    detail_issue_date = str(card.get("detail_issue_date") or issue_date)
    if root:
        href_prefix = f"{html.escape(detail_issue_date, quote=True)}/"
    elif detail_issue_date != issue_date:
        href_prefix = f"../{html.escape(detail_issue_date, quote=True)}/"
    else:
        href_prefix = ""
    slug = html.escape(str(card["slug"]), quote=True)
    retained_class = " retained" if card.get("retained_from_issue_date") else ""
    return f"""        <article class="card{retained_class} {topic_class}">
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


def latest_three_dates(issue_date: str) -> set[str]:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    return {
        issue_dt.isoformat(),
        issue_dt.fromordinal(issue_dt.toordinal() - 1).isoformat(),
        issue_dt.fromordinal(issue_dt.toordinal() - 2).isoformat(),
    }


def rolling_display_cards(issue_path: Path, issue: dict[str, Any], current_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_date = require_str(issue, "issue_date")
    allowed_source_dates = latest_three_dates(issue_date)
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    state_root = issue_path.parent.parent if issue_path.parent.parent.exists() else DEFAULT_STATE_ROOT
    display_cards: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_card(card: dict[str, Any], *, detail_issue_date: str, retained_from_issue_date: str | None = None) -> None:
        source_date = str(card.get("source_published_date", ""))
        if source_date not in allowed_source_dates:
            return
        key = (
            re.sub(r"\s+", " ", str(card.get("title", "")).strip()).lower(),
            str(card.get("category", "")),
            source_date,
        )
        if key in seen:
            return
        seen.add(key)
        display_cards.append(
            {
                **card,
                "issue_date": issue_date,
                "detail_issue_date": detail_issue_date,
                "freshness_label": relative_day_label(issue_date, source_date),
                **({"retained_from_issue_date": retained_from_issue_date} if retained_from_issue_date else {}),
            }
        )

    for card in current_cards:
        add_card(card, detail_issue_date=issue_date)

    issue_files: list[tuple[datetime.date, Path]] = []
    for candidate in state_root.glob("20??-??-??/issue.json"):
        try:
            candidate_dt = datetime.strptime(candidate.parent.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if candidate_dt >= issue_dt or (issue_dt - candidate_dt).days > 7:
            continue
        issue_files.append((candidate_dt, candidate))

    for candidate_dt, candidate_path in sorted(issue_files, reverse=True):
        previous_issue = read_json(candidate_path)
        for card in normalized_cards(previous_issue):
            add_card(card, detail_issue_date=candidate_dt.isoformat(), retained_from_issue_date=candidate_dt.isoformat())

    return display_cards


def observed_evidence_urls(observations: list[dict[str, Any]]) -> set[str]:
    urls: set[str] = set()
    for observation in observations:
        if observation.get("slot_state") in {"observed_live", "reused_from_cache"}:
            url = observation.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                urls.add(url)
        for result in observation.get("source_target_results", []):
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            if (
                result.get("slot_state") in {"observed_live", "reused_from_cache"}
                and isinstance(url, str)
                and url.startswith(("http://", "https://"))
            ):
                urls.add(url)
        for finding in observation.get("discovery_findings", []):
            if not isinstance(finding, dict):
                continue
            url = finding.get("source_url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                urls.add(url)
    return urls


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
    nav_links = ['<a href="#priority">Priority</a>']
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
    sections = []
    for section_id, label in section_labels.items():
        section_cards = [card for card in cards if card["section_id"] == section_id]
        rendered_cards = "\n".join(render_card({**card, "issue_date": issue_date}, root=root) for card in section_cards)
        sections.append(
            f"""    <section class="section" id="{html.escape(section_id, quote=True)}">
      <div class="section-head"><h2>{html.escape(label)}</h2><p>重要更新 {len(section_cards)}件</p></div>
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
    h2 {{ margin:0; font-size:23px; }} .priority, .cards {{ display:grid; gap:14px; }} .priority {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .cards {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
    .priority-card, .card {{ background:var(--panel); border:1px solid var(--line); border-top:4px solid var(--blue); border-radius:10px; padding:18px; }}
    .priority-card.hot, .card.hot {{ border-top-color:var(--red); }} .priority-card.signal, .card.signal {{ border-top-color:var(--teal); }} .priority-card.macro, .card.macro {{ border-top-color:var(--amber); }}
    .rank {{ display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; margin-bottom:10px; border-radius:6px; background:var(--night); color:white; font-size:12px; font-weight:900; }}
    h3 {{ margin:0 0 8px; font-size:18px; line-height:1.32; }} p {{ margin:0 0 12px; }} .meta {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; color:var(--muted); }}
    @media (max-width:860px) {{ .priority, .cards {{ grid-template-columns:1fr; }} .bar {{ align-items:flex-start; flex-direction:column; }} }}
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
    frontier = require_list(issue, "frontier")
    issue_date = require_str(issue, "issue_date")
    if issue_date < LIVE_EVIDENCE_CONTRACT_DATE:
        if not frontier or any(not isinstance(item, dict) for item in frontier):
            fail("legacy issue frontier must contain objects")
        return frontier
    expected = build_frontier(read_json(CONFIG_PATH))
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


def validate_observation_records(
    observations: list[Any],
    frontier: list[dict[str, Any]],
    *,
    issue_date: str | None = None,
    source_registry: dict[str, list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    closed_states = {"observed_live", "reused_from_cache", "source_unavailable", "not_applicable"}
    allowed_roles = {"primary_or_official", "independent_media_or_data", "social_or_video_signal"}
    allowed_channels = {"web", "sns_x", "instagram", "facebook", "youtube", "data", "calendar"}
    if source_registry is None:
        source_registry = (
            load_source_registry_for_issue(issue_date)
            if issue_date
            else load_source_registry()
        )
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
        verified_target_count = 0
        live_target_count = 0
        strict_live_evidence = (
            issue_date or observation["observed_at_jst"][:10]
        ) >= LIVE_EVIDENCE_CONTRACT_DATE
        for result_index, result in enumerate(target_results, start=1):
            if not isinstance(result, dict):
                fail(f"observations[{index}] source_target_results[{result_index}] must be an object")
            required_result_keys = [
                "label",
                "url",
                "channel",
                "slot_state",
                "evidence_summary",
            ]
            if strict_live_evidence:
                required_result_keys.extend(("checked_at_jst", "verification_method"))
            for key in required_result_keys:
                if not isinstance(result.get(key), str) or not result[key].strip():
                    fail(f"observations[{index}] source_target_results[{result_index}] missing required string: {key}")
            if result["channel"] not in allowed_channels:
                fail(f"observations[{index}] source_target_results[{result_index}] invalid channel: {result['channel']}")
            if result["slot_state"] not in closed_states:
                fail(f"observations[{index}] source_target_results[{result_index}] invalid slot_state: {result['slot_state']}")
            if not result["url"].startswith(("http://", "https://")):
                fail(f"observations[{index}] source_target_results[{result_index}] url must be absolute")
            if strict_live_evidence:
                try:
                    checked_at = datetime.fromisoformat(result["checked_at_jst"])
                except ValueError:
                    fail(f"observations[{index}] source_target_results[{result_index}] checked_at_jst must be ISO-8601")
                if checked_at.strftime("%Y-%m-%d") != observation["observed_at_jst"][:10]:
                    fail(f"observations[{index}] source_target_results[{result_index}] checked_at_jst date mismatch")
                allowed_methods = {
                    "responses_web_search",
                    "reviewed_live_web",
                    "direct_fetch",
                    "cached_result",
                    "unavailable",
                }
                if result["verification_method"] not in allowed_methods:
                    fail(f"observations[{index}] source_target_results[{result_index}] invalid verification_method")
                if result["slot_state"] == "source_unavailable" and result["verification_method"] != "unavailable":
                    fail(f"observations[{index}] source_target_results[{result_index}] unavailable source needs unavailable method")
                if result["slot_state"] in {"observed_live", "reused_from_cache"} and result["verification_method"] == "unavailable":
                    fail(f"observations[{index}] source_target_results[{result_index}] observed source cannot use unavailable method")
            if result["slot_state"] in {"observed_live", "reused_from_cache"}:
                verified_target_count += 1
            if result["slot_state"] == "observed_live":
                live_target_count += 1
            if strict_live_evidence and re.search(r"時点の更新有無を確認した[。.]?$", result["evidence_summary"]):
                fail(f"observations[{index}] source_target_results[{result_index}] evidence summary is generic, not source-specific")
            result_urls.add(result["url"])
        unavailable_slot = observation["slot_state"] == "source_unavailable"
        if verified_target_count == 0 and not unavailable_slot:
            fail(f"observations[{index}] has no verified source result")
        if strict_live_evidence and live_target_count == 0 and not unavailable_slot:
            fail(f"observations[{index}] has no live source result for the current daily contract")
        if strict_live_evidence:
            expected_targets = source_targets_for_slot(source_registry, observation)
            missing_targets = [target["url"] for target in expected_targets if target["url"] not in result_urls]
            if missing_targets:
                fail(f"observations[{index}] missing source target results: " + ", ".join(missing_targets[:6]))
        claim_atoms = observation.get("claim_atoms")
        if not isinstance(claim_atoms, list):
            fail(f"observations[{index}] claim_atoms must be a list")

    state = coverage_state(observations, frontier=frontier)
    if state["missing_slots"]:
        first = state["missing_slots"][0]
        fail(
            "collection state has unclosed observation slots; first missing "
            f"{first['category']} / {first['watch_topic_id']} / {first['source_role']} / {first['channel']}"
        )
    return state


def validate_observations(
    issue: dict[str, Any],
    frontier: list[dict[str, Any]],
    issue_path: Path | None = None,
) -> list[dict[str, Any]]:
    observations = require_list(issue, "observations")
    issue_date = require_str(issue, "issue_date")
    plan_path = issue_path.parent / "collection_plan.json" if issue_path else None
    validate_observation_records(
        observations,
        frontier,
        issue_date=issue_date,
        source_registry=load_source_registry_for_issue(
            issue_date,
            plan_path=plan_path,
        ),
    )
    return observations


def validate_candidates(issue: dict[str, Any], frontier: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issue_date = require_str(issue, "issue_date")
    contract = read_json(CONFIG_PATH)
    candidates = require_list(issue, "candidates")
    watch_keys = {(item["category"], item["watch_topic_id"]) for item in frontier}
    allowed_change = {"new_event", "material_update", "routine_recurring", "duplicate_followup", "background_only"}
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            fail(f"candidates[{index}] must be an object")
        category = require_str(candidate, "category")
        topic = require_str(candidate, "watch_topic_id")
        key = (category, topic)
        if key not in watch_keys:
            fail(f"candidates[{index}] is outside coverage contract: {category}/{topic}")
        title = require_str(candidate, "title")
        require_str(candidate, "source_published_date")
        summary = require_str(candidate, "summary")
        if effective_on_or_after(contract, "public_copy_contract_effective_date", issue_date):
            reject_public_copy(f"candidates[{index}].title", title, kind="title")
            reject_public_copy(f"candidates[{index}].summary", summary, kind="summary")
        if effective_on_or_after(contract, "candidate_placeholder_ban_effective_date", issue_date):
            placeholder_hits = [
                pattern
                for pattern in CANDIDATE_PLACEHOLDER_PATTERNS
                if re.search(pattern, title) or re.search(pattern, summary)
            ]
            if placeholder_hits:
                fail(
                    f"candidates[{index}] is a no-change placeholder, not a candidate: "
                    + ", ".join(placeholder_hits)
                )
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
    return candidates


def observed_claim_source_urls(issue_date: str, observations: list[dict[str, Any]]) -> set[str]:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    allowed_dates = {
        issue_dt.isoformat(),
        issue_dt.fromordinal(issue_dt.toordinal() - 1).isoformat(),
        issue_dt.fromordinal(issue_dt.toordinal() - 2).isoformat(),
    }
    urls: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        if observation.get("slot_state") != "observed_live" or observation.get("published_date") not in allowed_dates:
            continue
        claim_atoms = observation.get("claim_atoms")
        if not isinstance(claim_atoms, list) or not claim_atoms:
            continue
        url = observation.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.add(url)
        for result in observation.get("source_target_results", []):
            if not isinstance(result, dict):
                continue
            result_url = result.get("url")
            if (
                isinstance(result_url, str)
                and result_url.startswith(("http://", "https://"))
                and result.get("slot_state") == "observed_live"
                and result.get("published_date") in allowed_dates
            ):
                urls.add(result_url)
    return urls


def validate_claim_source_linkage(issue: dict[str, Any], observations: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> None:
    issue_date = require_str(issue, "issue_date")
    contract = read_json(CONFIG_PATH)
    if not effective_on_or_after(contract, "claim_source_linkage_effective_date", issue_date):
        return
    claim_urls = observed_claim_source_urls(issue_date, observations)
    for index, candidate in enumerate(candidates, start=1):
        if candidate.get("change_class") not in {"new_event", "material_update"}:
            continue
        source_urls = candidate.get("source_urls")
        if not isinstance(source_urls, list) or not any(url in claim_urls for url in source_urls):
            fail(f"candidates[{index}] material item lacks claim/source linkage")


def validate_decisions_and_cards(issue: dict[str, Any], candidates: list[dict[str, Any]], cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = require_list(issue, "decisions")
    candidate_by_title = {str(candidate.get("title")): candidate for candidate in candidates}
    candidate_titles = set(candidate_by_title)
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
        candidate = candidate_by_title[title]
        if rejects_material_signal(decision, candidate):
            fail(f"decisions[{index}] rejects material signal as no-change: {title}")
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
    for card_index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            fail(f"cards[{card_index}] must be an object")
        candidate_title = require_str(card, "candidate_title")
        validate_card_candidate_binding(card, candidate_by_title[candidate_title], card_index=card_index)
    return decisions


def rejects_material_signal(decision: dict[str, Any], candidate: dict[str, Any]) -> bool:
    candidate_text = " ".join(
        str(candidate.get(key, ""))
        for key in ("title", "summary", "change_class")
    )
    return (
        decision.get("adoption_decision") == "reject"
        and decision.get("reject_reason_class") in {"no_material_change", "lower_importance"}
        and candidate.get("change_class") in {"new_event", "material_update"}
        and bool(MATERIAL_SIGNAL_RE.search(candidate_text))
    )


def validate_manifest_alignment(issue: dict[str, Any], cards: list[dict[str, Any]]) -> None:
    manifest = issue.get("coverage_manifest")
    if not isinstance(manifest, dict):
        fail("issue state missing coverage_manifest object")
    categories = manifest.get("categories")
    if not isinstance(categories, dict):
        fail("coverage_manifest missing categories object")
    contract = read_json(CONFIG_PATH)
    issue_date = require_str(issue, "issue_date")
    strict_live_evidence = issue_date >= LIVE_EVIDENCE_CONTRACT_DATE
    if strict_live_evidence:
        completed_at = manifest.get("collection_completed_at_jst")
        if not isinstance(completed_at, str):
            fail("coverage_manifest missing collection_completed_at_jst")
        try:
            completed = datetime.fromisoformat(completed_at)
        except ValueError:
            fail("coverage_manifest collection_completed_at_jst must be ISO-8601")
        if completed.strftime("%Y-%m-%d") != issue_date:
            fail("coverage_manifest collection_completed_at_jst date mismatch")
        if manifest.get("collection_mode") not in {
            "responses_web_search",
            "reviewed_live_web",
            "github_models_unattended",
        }:
            fail("coverage_manifest collection_mode must describe a live research path")
    if effective_on_or_after(contract, "detail_information_contract_effective_date", issue_date):
        expected_version = expected_contract_version(contract, issue_date)
        if manifest.get("contract_version") != expected_version:
            fail(f"coverage_manifest contract_version must be {expected_version}")
    cards_by_section: dict[str, list[str]] = {}
    candidate_topics_by_category: dict[str, set[str]] = {}
    for candidate in issue.get("candidates", []):
        if isinstance(candidate, dict):
            candidate_topics_by_category.setdefault(
                str(candidate.get("category")), set()
            ).add(str(candidate.get("watch_topic_id")))
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
        required_lists = [
            "new_or_changed_items",
            "no_change_checks",
            "latest_candidates",
        ]
        for key in required_lists:
            if not isinstance(entry.get(key), list):
                fail(f"{label} coverage_manifest missing list: {key}")
        if not strict_live_evidence:
            continue
        observed_urls = observed_evidence_urls(
            [
                observation
                for observation in issue.get("observations", [])
                if isinstance(observation, dict)
                and observation.get("category") == label
            ]
        )
        checked_topics: set[str] = set()
        for index, check in enumerate(entry["no_change_checks"], start=1):
            if not isinstance(check, dict):
                fail(f"{label} no_change_checks[{index}] must be an object")
            topic_id = check.get("topic_id")
            result = check.get("result")
            evidence_urls = check.get("evidence_urls")
            if not isinstance(topic_id, str) or not topic_id:
                fail(f"{label} no_change_checks[{index}] missing topic_id")
            if not isinstance(result, str) or len(compact_text(result)) < 20:
                fail(f"{label} no_change_checks[{index}] result is too weak")
            if (
                not isinstance(evidence_urls, list)
                or not evidence_urls
                or any(url not in observed_urls for url in evidence_urls)
            ):
                fail(f"{label} no_change_checks[{index}] needs verified evidence URLs")
            checked_topics.add(topic_id)
        required_topics = {
            str(topic.get("id"))
            for topic in category.get("watch_topics", [])
            if isinstance(topic, dict)
        }
        covered_topics = candidate_topics_by_category.get(label, set()) | checked_topics
        if covered_topics < required_topics:
            fail(
                f"{label} topic review is incomplete: "
                + ", ".join(sorted(required_topics - covered_topics))
            )


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
    observations = validate_observations(issue, frontier, issue_path)
    candidates = validate_candidates(issue, frontier)
    validate_claim_source_linkage(issue, observations, candidates)
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
    display_cards = rolling_display_cards(issue_path, issue, cards)
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
        render_issue_html(issue, display_cards, root=False),
        encoding="utf-8",
    )
    (details_dir / f"extraction-log-{issue_date}.html").write_text(render_extraction_log(issue), encoding="utf-8")
    if write_marker:
        (output_root / ".night-signal-issue-date").write_text(issue_date + "\n", encoding="utf-8")
    return {
        "issue_date": issue_date,
        "cards": len(cards),
        "display_cards": len(display_cards),
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


def material_signal_terms(category: str) -> list[str]:
    common = [
        "major announcement",
        "breaking",
        "decision",
        "policy",
        "partnership",
        "investment",
        "acquisition",
        "funding",
        "market reaction",
        "recall",
        "safety",
        "leadership",
        "talent",
        "contract",
        "infrastructure",
        "results",
        "guidance",
        "outlook",
        "regulation",
        "lawsuit",
        "日本",
        "発表",
        "買収",
        "提携",
        "出資",
        "政策",
        "人事",
        "広告",
        "販売",
        "市場反応",
        "リコール",
        "安全",
        "決算",
        "見通し",
    ]
    by_category = {
        "Honda": [
            "QuantumScape",
            "solid-state battery",
            "全固体電池",
            "battery partnership",
            "EV strategy",
            "HEV",
            "China sales",
            "North America sales",
            "production",
            "tariff",
            "Honda stock",
        ],
        "F1": [
            "Honda",
            "HRC",
            "Aston Martin",
            "power unit",
            "PU",
            "ERS",
            "battery",
            "reliability",
            "retirement",
            "technical directive",
            "FIA",
            "race result",
            "driver comments",
        ],
        "日本経済": [
            "BOJ",
            "Ueda",
            "CPI",
            "wages",
            "JGB",
            "yen",
            "stock market",
            "ETF",
            "fund flows",
            "GDP",
            "industrial production",
            "retail sales",
            "trade",
            "tariff",
            "government package",
        ],
        "OpenAI": [
            "Noam Shazeer",
            "Character.AI",
            "Japan advertising",
            "SB OpenAI Japan",
            "model release",
            "API",
            "enterprise",
            "safety",
        ],
        "SpaceX": [
            "Cursor",
            "Anysphere",
            "xAI",
            "Starship",
            "Starlink",
            "launch failure",
            "contract",
            "IPO",
            "valuation",
        ],
        "宇都宮ブレックス": [
            "アリーナ",
            "新アリーナ",
            "宇都宮市",
            "B.PREMIER",
            "Bプレミア",
            "ロスター",
            "契約",
            "移籍",
        ],
    }
    return compact_terms(by_category.get(category, []) + common, limit=28)


def collection_hypotheses(frontier_item: dict[str, Any], slot: dict[str, str]) -> list[str]:
    category = slot["category"]
    topic = slot["watch_topic_id"]
    role = slot["source_role"]
    channel = slot["channel"]
    return [
        f"{category}/{topic}に前回状態から読者理解を変える新規または実質更新がある可能性。",
        f"{category}/{topic}は定例、重複、背景、または変化なしで公開候補にしない可能性。",
        f"{role}/{channel}で一次根拠、独立確認、または反証が見つかる可能性。",
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


def validate_strategic_signal_contract(
    contract: dict[str, Any],
    registry: dict[str, list[dict[str, str]]],
    plan: dict[str, Any],
) -> None:
    required_topics = {
        "OpenAI": {
            "topic": "strategic_talent_japan_gtm",
            "terms": {"Noam Shazeer", "Character.AI", "Gemini", "日本", "広告", "SB OpenAI Japan"},
            "sources": {"axios.com", "apnews.com"},
            "plan_markers": {"Noam Shazeer", "日本", "広告"},
        },
        "SpaceX": {
            "topic": "ai_mna_compute",
            "terms": {"Cursor", "Anysphere", "AI coding", "acquisition", "買収", "xAI"},
            "sources": {"businessinsider.com", "theguardian.com", "marketwatch.com"},
            "plan_markers": {"Cursor", "Anysphere", "買収"},
        },
        "宇都宮ブレックス": {
            "topic": "arena_regional_admin",
            "terms": {"アリーナ", "新アリーナ", "建設", "宇都宮市", "地域行政", "B.PREMIER"},
            "sources": {"city.utsunomiya.lg.jp", "bleague.jp/new-bleague", "shimotsuke.co.jp"},
            "plan_markers": {"アリーナ", "建設", "宇都宮市"},
        },
    }

    categories = contract.get("categories")
    if not isinstance(categories, list):
        fail("coverage contract missing categories")
    by_label = {
        category.get("label"): category
        for category in categories
        if isinstance(category, dict) and isinstance(category.get("label"), str)
    }
    for category, requirement in required_topics.items():
        config = by_label.get(category)
        if not isinstance(config, dict):
            fail(f"{category} strategic signal category missing")
        topics = config.get("watch_topics")
        topic = next(
            (
                item
                for item in topics
                if isinstance(item, dict) and item.get("id") == requirement["topic"]
            ),
            None,
        ) if isinstance(topics, list) else None
        if not isinstance(topic, dict):
            fail(f"{category} missing strategic watch topic: {requirement['topic']}")
        terms = {term for term in topic.get("terms", []) if isinstance(term, str)}
        missing_terms = sorted(requirement["terms"] - terms)
        if missing_terms:
            fail(f"{category} strategic watch topic missing terms: " + ", ".join(missing_terms))

        source_text = " ".join(
            f"{target.get('label', '')} {target.get('url', '')}"
            for target in registry.get(category, [])
        )
        for marker in sorted(requirement["sources"]):
            if marker not in source_text:
                fail(f"{category} strategic source target missing: {marker}")

        plan_text = " ".join(
            " ".join(str(term) for term in topic.get("search_terms", []) if isinstance(term, str))
            for task in plan.get("tasks", [])
            if isinstance(task, dict) and task.get("category") == category
            for topic in task.get("watch_topics", [])
            if isinstance(topic, dict) and topic.get("watch_topic_id") == requirement["topic"]
        )
        for marker in sorted(requirement["plan_markers"]):
            if marker not in plan_text:
                fail(f"{category} strategic collection plan missing: {marker}")

    for category in by_label:
        terms = material_signal_terms(str(category))
        if len(terms) < 10:
            fail(f"{category} must have broad material signal terms")
        category_tasks = [
            task
            for task in plan.get("tasks", [])
            if isinstance(task, dict) and task.get("category") == category
        ]
        query_text = " ".join(
            query
            for task in category_tasks
            for query in task.get("search_queries", [])
            if isinstance(query, str)
        )
        missing_terms = [term for term in terms[:3] if term not in query_text]
        if missing_terms:
            fail(f"{category} material signal terms missing from collection queries: " + ", ".join(missing_terms))


def load_source_registry_for_issue(
    issue_date: str,
    *,
    plan_path: Path | None = None,
) -> dict[str, list[dict[str, str]]]:
    plan_path = plan_path or DEFAULT_STATE_ROOT / issue_date / "collection_plan.json"
    if not plan_path.exists():
        return load_source_registry()

    plan = read_json(plan_path)
    if plan.get("issue_date") != issue_date or not isinstance(plan.get("tasks"), list):
        fail(f"collection plan snapshot is invalid: {plan_path}")

    registry: dict[str, list[dict[str, str]]] = {}
    seen_urls: dict[str, set[str]] = {}
    for task_index, task in enumerate(plan["tasks"], start=1):
        if not isinstance(task, dict):
            fail(f"collection plan task[{task_index}] must be an object")
        category = task.get("category")
        targets = task.get("source_targets")
        if not isinstance(category, str) or not category.strip():
            fail(f"collection plan task[{task_index}] missing category")
        if not isinstance(targets, list) or not targets:
            fail(f"collection plan task[{task_index}] missing source_targets")
        category_targets = registry.setdefault(category, [])
        category_urls = seen_urls.setdefault(category, set())
        for target_index, target in enumerate(targets, start=1):
            if not isinstance(target, dict):
                fail(
                    f"collection plan task[{task_index}] "
                    f"source_targets[{target_index}] must be an object"
                )
            normalized: dict[str, str] = {}
            for key in ("label", "url", "source_role", "channel", "source_class"):
                value = target.get(key)
                if not isinstance(value, str) or not value.strip():
                    fail(
                        f"collection plan task[{task_index}] "
                        f"source_targets[{target_index}] missing {key}"
                    )
                normalized[key] = value.strip()
            if not normalized["url"].startswith(("https://", "http://")):
                fail(
                    f"collection plan task[{task_index}] "
                    f"source_targets[{target_index}] url must be absolute"
                )
            if normalized["url"] not in category_urls:
                category_targets.append(normalized)
                category_urls.add(normalized["url"])
    if not registry:
        fail(f"collection plan snapshot has no source targets: {plan_path}")
    return registry


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
    slots = required_observation_slots(frontier)
    grouped_slots: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for slot in slots:
        key = (slot["category"], slot["source_role"], slot["channel"])
        grouped_slots.setdefault(key, []).append(slot)
    frontier_by_category: dict[str, list[dict[str, Any]]] = {}
    for item in frontier:
        frontier_by_category.setdefault(str(item["category"]), []).append(item)

    tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    priority_rank = {"normal": 0, "high": 1}
    route_rank = {
        "small_structured_extractor": 0,
        "small_structured_extractor_then_frontier_reasoning_if_ambiguous": 1,
        "frontier_reasoning_model": 2,
    }
    for (category, source_role, channel), group in grouped_slots.items():
        representative = max(group, key=lambda item: (priority_rank.get(item["priority"], 0), route_rank.get(item["model_route"], 0)))
        category_topics = frontier_by_category[category]
        sweep_slot = {
            **representative,
            "watch_topic_id": "category_sweep",
            "category": category,
            "source_role": source_role,
            "channel": channel,
        }
        sweep_id = "-".join(
            [
                slug_text(category),
                slug_text(source_role),
                slug_text(channel),
            ]
        )
        topic_payload = [
            {
                "watch_topic_id": str(item["watch_topic_id"]),
                "search_terms": compact_terms(
                    [str(term) for term in item.get("search_terms", []) if isinstance(term, str)],
                    limit=12,
                ),
                "required_channels": [str(value) for value in item.get("required_channels", [])],
                "event_classes": [
                    str(value) for value in item.get("event_classes", [])
                ],
            }
            for item in category_topics
        ]
        topic_ids = [item["watch_topic_id"] for item in topic_payload]
        role_terms = " ".join(role_query_terms(source_role, channel))
        event_classes = sorted(
            {
                value
                for topic in topic_payload
                for value in topic.get("event_classes", [])
            }
        )
        material_terms = material_signal_terms(category)
        material_query = " ".join(material_terms[:14])
        discovery_lenses = [
            "official announcement release decision",
            "numbers results dates status change",
            "major media independent verification",
            "market reaction risk counter evidence",
            "social video interview schedule correction",
        ]
        task = {
            "issue_date": issue_date,
            "slot_id": sweep_id,
            "category": category,
            "section_id": str(category_topics[0]["section_id"]),
            "watch_topics": topic_payload,
            "source_role": source_role,
            "channel": channel,
            "priority": representative["priority"],
            "reuse_policy": representative["reuse_policy"],
            "model_route": representative["model_route"],
            "batch_group": batch_group(sweep_slot),
            "prompt_cache_key": prompt_cache_key(sweep_slot),
            "hypotheses": [
                f"{category}の既知トピック（{', '.join(topic_ids)}）に当日または直近3日間の実質更新がある可能性。",
                f"{category}に既存watch_topic_idだけでは表現できない重要変化がある可能性。",
                f"{category}の重大変化語（{', '.join(material_terms[:10])}）に該当する題目候補が出ている可能性。",
                f"{source_role}/{channel}で一次根拠、独立確認、反証、または変化なしを判定できる可能性。",
            ],
            "discovery_lenses": discovery_lenses,
            "source_targets": source_targets_for_slot(source_registry, sweep_slot),
            "search_queries": [
                f"{category} latest important developments {role_terms} {channel} {issue_date}",
                f"{category} breaking announcement change result data {role_terms} {issue_date}",
                f"{category} {' '.join(event_classes)} {role_terms} latest {issue_date}",
                f"{category} {' '.join(discovery_lenses)} {issue_date}",
                f"{category} {material_query} {role_terms} {issue_date}",
                f"{category} overlooked update correction contradiction {issue_date}",
            ],
            "acceptance": task_acceptance(sweep_slot),
            "output_schema": "collection_sweep",
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


def coverage_state(
    observations: list[dict[str, Any]] | None = None,
    *,
    frontier: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    frontier = frontier or build_frontier(read_json(CONFIG_PATH))
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
    registry = load_source_registry()
    categories = contract.get("categories", [])
    topic_count = sum(len(category.get("watch_topics", [])) for category in categories if isinstance(category, dict))
    if len(frontier) != topic_count:
        fail(f"frontier count mismatch: {len(frontier)} != {topic_count}")
    for name, schema in SCHEMAS.items():
        if schema.get("type") != "object" or not schema.get("required"):
            fail(f"{name} schema is not strict enough")
    coverage = coverage_state([])
    plan = collection_plan("2099-01-01")
    validate_strategic_signal_contract(contract, registry, plan)
    if coverage["required_observation_slots"] <= len(frontier):
        fail("observation slots must expand source roles/channels beyond watch topics")
    if len(plan["tasks"]) >= coverage["required_observation_slots"]:
        fail("collection plan must consolidate observation slots into fewer category sweeps")
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
    if any(len(task.get("discovery_lenses", [])) < 5 for task in plan["tasks"]):
        fail("collection plan tasks must include generic discovery lenses")
    planned_topic_slots = {
        (task["category"], topic["watch_topic_id"], task["source_role"], task["channel"])
        for task in plan["tasks"]
        for topic in task["watch_topics"]
    }
    required_topic_slots = {
        (slot["category"], slot["watch_topic_id"], slot["source_role"], slot["channel"])
        for slot in required_observation_slots(frontier)
    }
    if planned_topic_slots != required_topic_slots:
        fail("collection sweeps must preserve every required observation slot")
    target_references = [
        target["url"]
        for task in plan["tasks"]
        for target in task["source_targets"]
    ]
    if len(target_references) != len(set(target_references)):
        fail("collection sweeps must inspect each seed target only once")
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
    placeholder_failures: list[str] = []
    original_fail = fail

    def capture_placeholder_failure(message: str) -> None:
        placeholder_failures.append(message)
        raise RuntimeError(message)

    globals()["fail"] = capture_placeholder_failure
    try:
        try:
            validate_candidates(
                {
                    "issue_date": "2099-01-01",
                    "candidates": [
                        {
                            "category": "OpenAI",
                            "watch_topic_id": "product_release",
                            "title": "OpenAI、product_releaseの直近確認",
                            "source_published_date": "2099-01-01",
                            "source_urls": ["https://openai.com/"],
                            "change_class": "background_only",
                            "summary": "OpenAIのproduct_releaseを公式・媒体・SNS系の証跡で確認したが、単独記事にする確定差分は不足した。",
                            "material_facts": [],
                            "counter_evidence_checked": True,
                        }
                    ],
                },
                frontier,
            )
        except RuntimeError:
            pass
    finally:
        globals()["fail"] = original_fail
    if not placeholder_failures or "no-change placeholder" not in placeholder_failures[0]:
        fail("candidate validation must reject no-change placeholders")

    def self_test_card(candidate_title: str, title: str, summary: str) -> dict[str, Any]:
        return {
            "candidate_title": candidate_title,
            "title": title,
            "summary": summary,
            "detail": {
                "summary": summary,
                "summary_basis": {
                    "what_changed": summary,
                    "why_it_matters": summary,
                    "confirmed_facts": [summary],
                    "limits_or_unknowns": "未確定点は公表範囲に限られる。",
                },
            },
        }

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
        [
            {
                "title": "OpenAI Codex sharing candidate",
                "summary": "OpenAI Codex sharing candidateとして、Codexの共有機能が追加された。",
                "change_class": "material_update",
                "source_published_date": "2099-01-01",
            }
        ],
        [
            self_test_card(
                "OpenAI Codex sharing candidate",
                "OpenAI、Codexに共有機能を追加",
                "OpenAI Codex sharing candidateとして、Codexの共有機能が追加された。",
            )
        ],
    )
    if not rejects_material_signal(
        {
            "candidate_title": "SpaceX、200億ドル社債を検討",
            "adoption_decision": "reject",
            "topic_value_class": "market_or_financial_impact",
            "reader_delta": "SpaceXが200億ドル規模の社債を検討している。",
            "materiality_basis": "資金調達と投資判断に関わる。",
            "reject_reason_class": "no_material_change",
            "reject_reason": "単独記事にする差分が不足した。",
        },
        {
            "title": "SpaceX、200億ドル社債を検討",
            "summary": "SpaceXが200億ドル規模の社債を検討している。",
            "change_class": "material_update",
        },
    ):
        fail("material candidate rejection guard must reject no-change decisions")
    if rejects_material_signal(
        {
            "candidate_title": "OpenAI、IPOの直近確認",
            "adoption_decision": "reject",
            "topic_value_class": "market_or_financial_impact",
            "reader_delta": "直近確認では確定差分が不足した。",
            "materiality_basis": "監視対象を確認した。",
            "reject_reason_class": "no_material_change",
            "reject_reason": "単独記事にする差分が不足した。",
        },
        {
            "title": "OpenAI、IPOの直近確認",
            "summary": "確定差分は不足した。",
            "change_class": "background_only",
        },
    ):
        fail("material candidate guard must allow background watch-topic checks")
    validate_decisions_and_cards(
        {
            "decisions": [
                {
                    "candidate_title": "SpaceX、200億ドル社債を検討",
                    "adoption_decision": "adopt",
                    "topic_value_class": "market_or_financial_impact",
                    "reader_delta": "SpaceXが200億ドル規模の社債を検討している。",
                    "materiality_basis": "資金調達と投資判断に関わる。",
                    "reject_reason_class": None,
                    "reject_reason": None,
                }
            ]
        },
        [
            {
                "title": "SpaceX、200億ドル社債を検討",
                "summary": "SpaceXが200億ドル規模の社債を検討している。",
                "change_class": "material_update",
            }
        ],
        [
            self_test_card(
                "SpaceX、200億ドル社債を検討",
                "SpaceX、200億ドル社債を検討",
                "SpaceXが200億ドル規模の社債を検討している。",
            )
        ],
    )
    try:
        validate_decisions_and_cards(
            {
                "decisions": [
                    {
                        "candidate_title": "ChatGPT安全更新",
                        "adoption_decision": "adopt",
                        "topic_value_class": "technical_or_product_shift",
                        "reader_delta": "安全更新により応答制御が変わる。",
                        "materiality_basis": "公式発表で新しい安全更新を確認できる。",
                        "reject_reason_class": None,
                        "reject_reason": None,
                    }
                ]
            },
            [
                {
                    "title": "ChatGPT安全更新",
                    "summary": "ChatGPTが会話の流れからリスク兆候を拾い、応答を調整する安全更新を発表した。",
                    "change_class": "material_update",
                    "source_published_date": "2099-01-01",
                }
            ],
            [
                {
                    "candidate_title": "ChatGPT安全更新",
                    "title": "ChatGPT安全更新",
                    "summary": "ChatGPTに家計管理プレビューが加わり、口座連携を始めた。",
                    "detail": {
                        "summary": "家計管理プレビューでは口座連携とダッシュボードを提供する。",
                        "summary_basis": {
                            "what_changed": "家計管理プレビューが始まった。",
                            "why_it_matters": "金融データ連携に関係する。",
                            "confirmed_facts": ["口座連携が提供される。"],
                            "limits_or_unknowns": "対象地域は限定される。",
                        },
                    },
                }
            ],
        )
    except SystemExit:
        pass
    else:
        fail("card/candidate binding must reject mismatched title and summary facts")
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
                "fact_sources": [
                    {
                        "fact": "OpenAIがCodexの共有機能を発表した。",
                        "source_urls": ["https://openai.com/"],
                    },
                    {
                        "fact": "共有対象はCodexの記録内容で、チーム利用を想定している。",
                        "source_urls": ["https://openai.com/"],
                    },
                ],
                "limits_or_unknowns": "提供範囲や利用条件は公式発表の範囲で確認済みの内容に限る。",
                "source_dates": ["2099-01-01"],
            },
            "sources": [{"label": "OpenAI公式", "url": "https://openai.com/"}],
        }
    )
    if "30秒概要" in rendered or "要点と背景" not in rendered or "確認した事実" not in rendered or "未確定点" not in rendered:
        fail("detail renderer must use the current information-complete structure")
    render_issue = {
        "issue_date": "2099-01-03",
        "observations": [
            {
                "category": "Honda",
                "slot_state": "observed_live",
                "url": "https://global.honda/",
                "source_target_results": [
                    {
                        "url": "https://global.honda/",
                        "slot_state": "observed_live",
                    }
                ],
                "discovery_findings": [],
            }
        ],
        "candidates": [
            {
                "category": "OpenAI",
                "title": "OpenAI、Codexに共有機能を追加",
                "source_published_date": "2099-01-03",
                "summary": "OpenAIがCodexの共有機能を追加し、チーム内で記録内容を共有しやすくした。",
            },
            {
                "category": "Honda",
                "watch_topic_id": "market_price_reaction",
                "title": "Honda、中国販売の月次減少を確認",
                "source_published_date": "2099-01-02",
                "summary": "Hondaの中国販売に月次で大きな減少があり、市場環境と日本勢の苦戦を読む材料になる。",
                "source_urls": ["https://global.honda/"],
                "change_class": "routine_recurring",
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
    render_cards = [
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
    render_html = render_issue_html(render_issue, render_cards, root=False)
    banned_public_labels = ["カテゴリ別" + "新着", "一覧" + "のみ"]
    if any(label in render_html for label in banned_public_labels):
        fail("issue renderer must avoid legacy list-only labels")
    if "OpenAI、Codexに共有機能を追加" not in render_html:
        fail("issue renderer must keep adopted detail cards visible in their category section")
    if "確認情報" in render_html or "参照元" in render_html:
        fail("issue renderer must not expose compact confirmation items")
    if ("候補" + "題目") in render_html:
        fail("issue renderer must not expose a separate candidate-topic section")
    if "重要更新 1件" not in render_html:
        fail("issue renderer must keep the traditional important-updates section format")
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
