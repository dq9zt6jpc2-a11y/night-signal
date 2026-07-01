#!/usr/bin/env python3
"""Canonical state and rendering contract for NIGHT SIGNAL."""

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
EDITOR_CONTRACT_PATHS = (
    ROOT / "scripts" / "night_signal_core.py",
    ROOT / "scripts" / "night_signal_editor.py",
    ROOT / "scripts" / "night_signal_models.py",
    ROOT / "scripts" / "night_signal_state.py",
    ROOT / "config" / "night_signal_coverage.json",
    ROOT / "config" / "night_signal_models.json",
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
PUBLISHER_SUFFIX_RE = re.compile(
    r"\s[-–—]\s*(?:"
    r"[A-Za-z0-9][A-Za-z0-9 .&!|｜・-]*|"
    r"(?:Yahoo!|MSN|Google|LINE)[^。、]{0,40}|"
    r"[Ａ-Ｚａ-ｚ０-９][^。、]{1,}|"
    r"[ぁ-んァ-ヶ一-龯]+(?:新聞|ニュース|ファイナンス|Digital|デジタル|通信|テレビ|メニュー)[^。、]*"
    r")$"
)
DOMAIN_RE = re.compile(
    r"\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s。、]*)?"
)
FACT_SOURCE_METADATA_RE = re.compile(
    r"(?:が|は)?\s*20\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?付の"
    r"(?:情報|記事|動画)?として配信|"
    r"(?:配信元|掲載元|出典日(?:付)?|確認日(?:付)?)\s*[:：]|"
    r"(?:Google News RSS|検索結果)で.{0,100}(?:確認|配信)|"
    r"(?:更新|公表|掲載|配信)日は.{0,80}(?:対象期間|期間に含ま)|"
    r"[（(](?:共同通信|時事通信|Reuters|ロイター)[）)]\s*"
    r"(?:Yahoo!|YouTube|MSN)?[。．.!！?？]*$",
    re.I,
)
SOURCE_CHANNEL_RE = re.compile(
    r"公式(?:サイト|ページ|IR|ニュースルーム)|ニュースルーム|IRページ|"
    r"記事|動画|検索結果|RSS",
    re.I,
)
NO_UPDATE_ASSERTION_RE = re.compile(
    r"(?:具体的|新たな|明確な|直接的な).{0,50}"
    r"(?:事実|変化|更新|発表|内容|導入|成果|影響)"
    r".{0,50}(?:記載|確認|公表|掲載|含ま).{0,12}"
    r"(?:されていない|できない|見当たらない|ない)|"
    r"(?:該当|関連)する.{0,50}(?:新曲|変動|更新|発表|事実)"
    r".{0,30}(?:記載されていない|確認できない|見当たらない|ない)",
    re.I,
)
NAVIGATION_MARKER_RE = re.compile(
    r"このページをスキップ|閉じる|shopping cart|もっと見る|"
    r"ニュース一覧|選手名鑑|日程結果|順位表|個人成績|公式(?:Twitter|X)|"
    r"(?:^|\s)(?:home|menu|news|charts?|books?|global|world|japan|overseas|special)"
    r"(?=\s|$)",
    re.I,
)
NAVIGATION_RUN_RE = re.compile(
    r"(?:\b[A-Z][A-Z0-9&]{1,}\b[\s＋+|｜]*){5,}"
)
ORPHAN_LEADING_PARTICLE_RE = re.compile(r"^(?:は|が|を|に|で|と|へ)(?=[^\s])")
EMPTY_GROUP_RE = re.compile(r"[（(【\[]\s*[）)】\]]")
FACT_ANALYSIS_OR_UNKNOWN_RE = re.compile(
    r"判断する材料になる|判断材料となる|"
    r"(?:今後|引き続き|追加の).{0,80}(?:確認対象|確認が必要|焦点となる)|"
    r"(?:影響|対象)範囲.{0,80}(?:確認対象|確認が必要)|"
    r"影響しうる|注目される|重要となる|"
    r"対象範囲、実施時期と継続性|"
    r"(?:未定|未確定|未公表|明らかになっていない|公表していない|"
    r"開示していない|今後決定|調整中|検討中)|"
    + NO_UPDATE_ASSERTION_RE.pattern,
    re.I,
)
FACT_MARKUP_RE = re.compile(r"<\s*/?\s*[a-z!]|\bhref\s*=|&(?:lt|gt|nbsp);", re.I)
GENERIC_CONTEXT_RE = re.compile(
    r"(?:"
    r"性能、提供範囲、既存製品との関係|"
    r"規模、条件、資金使途と市場反応|"
    r"対象範囲、対策の実効性と残る制約|"
    r"対象範囲、実施時期と関係者の役割|"
    r"今回の結果と次工程への影響|"
    r"変更された時期と前後工程への影響|"
    r"作品内容、展開時期と反応|"
    r"対象範囲、実施時期と継続性"
    r").{0,120}判断する材料になる"
)
ANALYSIS_HEADLINE_RE = re.compile(
    r"(^|[【\[])(?:解説|分析|検証|日経平均の正体)|"
    r"(?:正体|裏側|バブルの危険|なぜ|どう見る|読み解く|徹底解説)",
    re.I,
)
ANALYSIS_REASONING_RE = re.compile(
    r"要因|背景|理由|構造|比較|差がある|一方|ただし|"
    r"依存|集中|未実現|評価益|現金収支|キャッシュフロー|"
    r"リスク|割高|割安|持続性|感応度|分析(?:した|している|すると)",
    re.I,
)
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
        "confirmed_facts",
        "fact_sources",
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
        "watch_topic_id",
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
        "watch_topic_id": {"type": "string"},
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

ISSUE_STATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issue_date", "cards", "coverage_manifest"],
    "properties": {
        "issue_date": {"type": "string"},
        "cards": {"type": "array", "items": CARD_SCHEMA},
        "coverage_manifest": {"type": "object"},
    },
}

SCHEMAS = {
    "card": CARD_SCHEMA,
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


def jst_today() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def category_required_channels(contract: dict[str, Any], category: dict[str, Any]) -> list[str]:
    channels = category.get("required_watch_topic_channels", contract.get("required_watch_topic_channels", ["web", "sns_x", "youtube"]))
    if not isinstance(channels, list) or any(not isinstance(channel, str) for channel in channels):
        fail(f"{category.get('label', '<unknown>')} has invalid required channels")
    return channels


def selected_issue_date() -> str | None:
    if not MARKER_PATH.exists():
        return None
    return MARKER_PATH.read_text(encoding="utf-8").strip()


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
        "evidence": (state_dir / "evidence.json").exists(),
        "state_issue_json": issue_path.exists(),
        "marker_is_issue_date": selected_issue_date() == issue_date,
        "sample_html": (ROOT / f"night-brief-web-sample-{issue_date}.html").exists(),
        "root_site_html": (ROOT / "site" / "index.html").exists(),
        "dated_site_html": (ROOT / "site" / issue_date / "index.html").exists(),
    }


def readiness(issue_date: str) -> dict[str, Any]:
    contract = read_json(CONFIG_PATH)
    artifacts = artifact_status(issue_date)
    blockers = [name for name, ok in artifacts.items() if not ok]
    topic_count = sum(
        len(category.get("watch_topics", []))
        for category in contract.get("categories", [])
        if isinstance(category, dict)
    )
    if artifacts["state_issue_json"] and not blockers:
        source_state = "publication_ready"
    elif artifacts["state_issue_json"]:
        source_state = "issue_built"
    elif artifacts["evidence"]:
        source_state = "evidence_collected"
    else:
        source_state = "collection_pending"
    return {
        "issue_date": issue_date,
        "state": "publication_ready" if not blockers else source_state,
        "watch_topic_count": topic_count,
        "artifacts": artifacts,
        "blockers": blockers,
        "purpose_invariants": {
            "evidence_bundle_present": artifacts["evidence"],
            "single_issue_state_present": artifacts["state_issue_json"],
            "publication_artifacts_present": artifacts["state_issue_json"] and artifacts["sample_html"] and artifacts["dated_site_html"],
        },
        "design": {
            "generation_owner": "night_signal_state.py --generate-issue",
            "generation_source_state": source_state,
            "collection_owner": "night_signal_publish.py -> night_signal_collect.py",
            "story_owner": "night_signal_editor.py",
            "publication_rule": "publish only selected JST-current issue artifacts",
            "content_contract": "Evidence is edited once into public updates; validators reject and renderers only display.",
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


def display_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


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


def public_render_copy_violations(text: str, *, kind: str) -> list[str]:
    stripped = text.strip()
    violations = public_copy_violations(stripped, kind=kind)
    japanese_chars = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", stripped))
    latin_chars = len(re.findall(r"[A-Za-z]", stripped))
    if latin_chars >= 24 and japanese_chars < 6:
        violations.append("untranslated English public copy")
    if DOMAIN_RE.search(stripped):
        violations.append("publisher/domain name leaked")
    if kind == "title" and PUBLISHER_SUFFIX_RE.search(stripped):
        violations.append("publisher suffix leaked")
    if ORPHAN_LEADING_PARTICLE_RE.search(stripped):
        violations.append("sentence starts with an orphaned particle")
    if kind == "title" and EMPTY_GROUP_RE.search(stripped):
        violations.append("empty brackets left after source cleanup")
    if navigation_shell_text(stripped):
        violations.append("navigation or page-shell text leaked")
    if kind == "summary" and NO_UPDATE_ASSERTION_RE.search(stripped):
        violations.append("no-update statement exposed as an important update")
    if kind == "summary" and GENERIC_CONTEXT_RE.search(stripped):
        violations.append("generic context template exposed as article substance")
    return violations


def navigation_shell_text(text: str) -> bool:
    value = html.unescape(str(text))
    markers = {
        match.group(0).strip().lower()
        for match in NAVIGATION_MARKER_RE.finditer(value)
    }
    return len(markers) >= 4 or bool(NAVIGATION_RUN_RE.search(value))


def same_material_event(left: Any, right: Any) -> bool:
    left_signature = copy_signature(str(left))
    right_signature = copy_signature(str(right))
    left_ngrams = {
        left_signature[index : index + 3]
        for index in range(max(0, len(left_signature) - 2))
    }
    right_ngrams = {
        right_signature[index : index + 3]
        for index in range(max(0, len(right_signature) - 2))
    }
    similarity = (
        len(left_ngrams & right_ngrams) / min(len(left_ngrams), len(right_ngrams))
        if left_ngrams and right_ngrams
        else 0.0
    )
    return materially_same_fact(str(left), str(right)) or (
        text_overlap(str(left), str(right)) >= 2 and similarity >= 0.4
    )


def card_event_text(card: dict[str, Any]) -> str:
    detail = card.get("detail")
    basis = detail.get("summary_basis") if isinstance(detail, dict) else None
    facts = basis.get("confirmed_facts", []) if isinstance(basis, dict) else []
    return " ".join(
        [str(card.get("title", "")), str(card.get("summary", "")), *map(str, facts)]
    )


def source_label_leaked(card: dict[str, Any]) -> bool:
    detail = card.get("detail")
    if not isinstance(detail, dict):
        return False
    title = str(card.get("title", "")).casefold()
    basis = detail.get("summary_basis")
    facts = basis.get("confirmed_facts", []) if isinstance(basis, dict) else []
    fields = [
        str(card.get("summary", "")),
        str(detail.get("summary", "")),
        *[str(fact) for fact in facts if isinstance(fact, str)],
    ]
    for source in detail.get("sources", []):
        if not isinstance(source, dict):
            continue
        label = str(source.get("label", "")).strip()
        if len(label) >= 3 and label.casefold() not in title:
            if any(label.casefold() in field.casefold() for field in fields):
                return True
    return False


def public_card_is_reader_facing(card: dict[str, Any]) -> bool:
    detail = card.get("detail")
    if not isinstance(detail, dict):
        return False
    basis = detail.get("summary_basis")
    facts = basis.get("confirmed_facts", []) if isinstance(basis, dict) else []
    fields = [
        (str(card.get("title", "")), "title"),
        (str(card.get("summary", "")), "summary"),
        (str(detail.get("summary", "")), "summary"),
        *[(str(fact), "summary") for fact in facts if isinstance(fact, str)],
    ]
    title = str(card.get("title", ""))
    material_facts = normalize_material_facts(title, facts, limit=max(1, len(facts)))
    adds_information = any(
        fact_adds_information(title, fact) for fact in material_facts
    )
    return (
        bool(material_facts)
        and adds_information
        and
        all(
            not public_render_copy_violations(text, kind=kind)
            for text, kind in fields
        )
        and not reader_summary_violations(
            str(card.get("title", "")), str(card.get("summary", ""))
        )
        and not source_label_leaked(card)
    )


def reject_public_copy(label: str, text: str, *, kind: str) -> None:
    violations = public_copy_violations(text, kind=kind)
    if violations:
        fail(f"{label} is not reader-facing public copy: " + "; ".join(violations))


def reject_public_render_copy(label: str, text: str, *, kind: str) -> None:
    violations = public_render_copy_violations(text, kind=kind)
    if violations:
        fail(f"{label} is not reader-facing public copy: " + "; ".join(violations))


def copy_signature(text: str) -> str:
    stripped = PUBLISHER_SUFFIX_RE.sub("", str(text))
    stripped = DOMAIN_RE.sub("", stripped)
    return re.sub(r"[、。．.!！?？\s「」『』（）()【】\-–—|｜・]", "", stripped).lower()


def title_repetition_score(title: str, text: str) -> float:
    title_terms = content_terms(copy_signature(title))
    text_terms = content_terms(copy_signature(text))
    if not title_terms or not text_terms:
        return 0.0
    return len(title_terms & text_terms) / max(1, len(title_terms))


def reader_summary_violations(title: str, summary: str) -> list[str]:
    title_key = copy_signature(title)
    summary_key = copy_signature(summary)
    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?])", summary) if part.strip()]
    violations: list[str] = []
    if title_key and summary_key.count(title_key) >= 2:
        violations.append("repeats the title instead of summarizing")
    if (
        title_repetition_score(title, summary) >= 0.82
        and len(content_terms(summary)) <= len(content_terms(title)) + 2
        and (len(sentences) <= 1 or len(summary_key) < len(title_key) * 1.6)
    ):
        violations.append("is too similar to its title")
    unique = {copy_signature(sentence) for sentence in sentences if copy_signature(sentence)}
    if len(sentences) >= 2 and len(unique) <= 1:
        violations.append("repeats the same sentence")
    return violations


def material_fact_violations(text: str) -> list[str]:
    value = html.unescape(str(text)).strip()
    violations: list[str] = []
    if len(value) < 18:
        violations.append("too short to be a material fact")
    if FACT_MARKUP_RE.search(value):
        violations.append("contains markup")
    if FACT_SOURCE_METADATA_RE.search(value):
        violations.append("is source metadata, not an event fact")
    if FACT_ANALYSIS_OR_UNKNOWN_RE.search(value):
        violations.append("is analysis or an unknown, not a confirmed fact")
    if public_render_copy_violations(value, kind="summary"):
        violations.append("is not reader-facing public copy")
    return violations


def analysis_headline(text: str) -> bool:
    return bool(ANALYSIS_HEADLINE_RE.search(str(text)))


def analysis_scope_sentence(title: str) -> str:
    focus = re.sub(r"^(?:【[^】]{1,40}】|\[[^\]]{1,40}\])\s*", "", str(title)).strip()
    focus = focus.rstrip("。.!！?？")
    return f"今回の検証は、{focus}を論点としている。" if focus else ""


def analysis_conclusion(values: list[Any]) -> str:
    candidates: list[tuple[int, str]] = []
    for raw in values:
        for sentence in re.split(r"(?<=[。！？!?])\s*", str(raw)):
            text = sentence.strip()
            if (
                len(text) >= 24
                and ANALYSIS_REASONING_RE.search(text)
                and not material_fact_violations(text)
            ):
                score = 1
                if re.search(r"分析(?:した|している|すると)|結論|示唆|とみる", text):
                    score += 3
                if re.search(r"依存|集中|構造|未実現|現金収支|キャッシュフロー|リスク|持続性", text):
                    score += 2
                normalized = text if text.endswith(("。", "！", "？", "!", "?")) else f"{text}。"
                candidates.append((score, normalized))
    if not candidates:
        return ""
    score, conclusion = max(candidates, key=lambda item: item[0])
    return conclusion if score >= 3 else ""


def analysis_summary_complete(title: str, summary: str) -> bool:
    if not analysis_headline(title):
        return True
    return "今回の検証" in str(summary) and bool(ANALYSIS_REASONING_RE.search(str(summary)))


def materially_same_fact(left: str, right: str) -> bool:
    left_signature = copy_signature(left)
    right_signature = copy_signature(right)
    if not left_signature or not right_signature:
        return False
    if (
        left_signature == right_signature
        or left_signature in right_signature
        or right_signature in left_signature
    ):
        return True
    left_ngrams = {
        left_signature[index : index + 3]
        for index in range(max(0, len(left_signature) - 2))
    }
    right_ngrams = {
        right_signature[index : index + 3]
        for index in range(max(0, len(right_signature) - 2))
    }
    if not left_ngrams or not right_ngrams:
        return False
    overlap = len(left_ngrams & right_ngrams) / min(len(left_ngrams), len(right_ngrams))
    left_numbers = set(re.findall(r"\d+(?:\.\d+)?", left_signature))
    right_numbers = set(re.findall(r"\d+(?:\.\d+)?", right_signature))
    if left_numbers and left_numbers == right_numbers and overlap >= 0.52:
        return True
    return overlap >= 0.82


def fact_adds_information(title: str, fact: str) -> bool:
    if materially_same_fact(title, fact):
        return False
    if not SOURCE_CHANNEL_RE.search(fact):
        return True
    without_channel = SOURCE_CHANNEL_RE.sub("", fact)
    without_channel = re.sub(
        r"20\d{2}年\d{1,2}月\d{1,2}日(?:に|、)?",
        "",
        without_channel,
    )
    return bool(content_terms(without_channel) - content_terms(title))


def normalize_material_facts(title: str, values: list[Any], limit: int = 8) -> list[str]:
    facts: list[str] = []
    signatures: list[str] = []
    for raw in values:
        value = " ".join(html.unescape(str(raw)).split())
        for part in re.split(r"(?<=[。！？!?])\s*", value):
            fact = part.strip(" -–—|｜")
            if not fact or material_fact_violations(fact):
                continue
            signature = copy_signature(fact)
            if not signature:
                continue
            duplicate_index = next(
                (
                    index
                    for index, existing_fact in enumerate(facts)
                    if materially_same_fact(fact, existing_fact)
                ),
                None,
            )
            if duplicate_index is not None:
                existing = signatures[duplicate_index]
                if len(signature) >= len(existing) * 1.25:
                    facts[duplicate_index] = fact
                    signatures[duplicate_index] = signature
                continue
            facts.append(fact)
            signatures.append(signature)
            if len(facts) >= limit:
                return facts
    return facts


def normalize_analysis_facts(title: str, values: list[Any], limit: int = 8) -> list[str]:
    facts = normalize_material_facts(title, values, limit=max(limit * 2, 8))
    return [fact for fact in facts if not materially_same_fact(title, fact)][:limit]


def validate_reader_summary(label: str, title: str, summary: str) -> None:
    violations = reader_summary_violations(title, summary)
    if violations:
        fail(f"{label} {violations[0]}")


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


def validate_summary_basis(
    detail: dict[str, Any],
    *,
    title: str,
    issue_date: str,
    source_date: str,
    card_index: int,
) -> None:
    contract = read_json(CONFIG_PATH)
    if not effective_on_or_after(contract, "detail_information_contract_effective_date", issue_date):
        return
    basis = detail.get("summary_basis")
    if not isinstance(basis, dict):
        fail(f"cards[{card_index}].detail.summary_basis is required for information-complete detail pages")

    value = require_str(basis, "what_changed")
    reject_public_copy(
        f"cards[{card_index}].detail.summary_basis.what_changed",
        value,
        kind="summary",
    )
    why_it_matters = basis.get("why_it_matters")
    if why_it_matters is not None:
        if not isinstance(why_it_matters, str) or not why_it_matters.strip():
            fail(
                f"cards[{card_index}].detail.summary_basis.why_it_matters "
                "must be omitted or non-empty"
            )
        reject_public_copy(
            f"cards[{card_index}].detail.summary_basis.why_it_matters",
            why_it_matters,
            kind="summary",
        )
    limits = basis.get("limits_or_unknowns")
    if limits is not None:
        if not isinstance(limits, str) or not limits.strip():
            fail(f"cards[{card_index}].detail.summary_basis.limits_or_unknowns must be omitted or non-empty")
        reject_public_copy(
            f"cards[{card_index}].detail.summary_basis.limits_or_unknowns",
            limits,
            kind="summary",
        )

    facts = basis.get("confirmed_facts")
    if not isinstance(facts, list) or not any(
        isinstance(fact, str) and fact.strip() for fact in facts
    ):
        fail(f"cards[{card_index}].detail.summary_basis.confirmed_facts must contain confirmed material facts")
    for fact_index, fact in enumerate(facts, start=1):
        if not isinstance(fact, str) or not fact.strip():
            fail(f"cards[{card_index}].detail.summary_basis.confirmed_facts[{fact_index}] must be a non-empty string")
        reject_public_copy(
            f"cards[{card_index}].detail.summary_basis.confirmed_facts[{fact_index}]",
            fact,
            kind="summary",
        )
    unique_facts = {copy_signature(fact) for fact in facts if isinstance(fact, str) and copy_signature(fact)}
    if not unique_facts:
        fail(f"cards[{card_index}].detail.summary_basis.confirmed_facts are repetitive")
    if effective_on_or_after(contract, "material_fact_semantics_effective_date", issue_date):
        material_facts = normalize_material_facts("", facts, limit=len(facts))
        if not material_facts:
            fail(
                f"cards[{card_index}].detail.summary_basis.confirmed_facts "
                "must be independent event facts, not source metadata or analysis"
            )
        if not any(fact_adds_information(title, fact) for fact in material_facts):
            fail(
                f"cards[{card_index}].detail.summary_basis.confirmed_facts "
                "must add source-backed information beyond the title"
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


def validate_public_card_copy(raw: dict[str, Any], detail: dict[str, Any], *, issue_date: str, card_index: int) -> None:
    title = require_str(raw, "title")
    summary = require_str(raw, "summary")
    source_date = require_str(raw, "source_published_date")
    detail_summary = require_str(detail, "summary")

    reject_public_render_copy(f"cards[{card_index}].title", title, kind="title")
    reject_public_render_copy(f"cards[{card_index}].summary", summary, kind="summary")
    reject_public_render_copy(f"cards[{card_index}].detail.summary", detail_summary, kind="summary")
    validate_reader_summary(f"cards[{card_index}].summary", title, summary)
    validate_reader_summary(f"cards[{card_index}].detail.summary", title, detail_summary)

    contract = read_json(CONFIG_PATH)
    if (
        effective_on_or_after(contract, "material_fact_semantics_effective_date", issue_date)
        and analysis_headline(title)
    ):
        basis = detail.get("summary_basis")
        what_changed = str(basis.get("what_changed", "")) if isinstance(basis, dict) else ""
        why_it_matters = str(basis.get("why_it_matters", "")) if isinstance(basis, dict) else ""
        analysis_facts = basis.get("confirmed_facts", []) if isinstance(basis, dict) else []
        summary_key = copy_signature(summary)
        detail_key = copy_signature(detail_summary)
        summary_fact_count = sum(
            bool(copy_signature(fact)) and copy_signature(fact) in summary_key
            for fact in analysis_facts
            if isinstance(fact, str)
        )
        detail_fact_count = sum(
            bool(copy_signature(fact)) and copy_signature(fact) in detail_key
            for fact in analysis_facts
            if isinstance(fact, str)
        )
        if (
            not analysis_summary_complete(title, summary)
            or not analysis_summary_complete(title, detail_summary)
            or "今回の検証" not in what_changed
            or not ANALYSIS_REASONING_RE.search(why_it_matters)
            or summary_fact_count < 2
            or detail_fact_count < 2
        ):
            fail(
                f"cards[{card_index}] analysis summary must explain the question, "
                "supporting evidence, and conclusion"
            )

    if any(term in title for term in SCHEDULE_ONLY_TERMS) and not any(term in title + summary for term in SCHEDULE_MATERIAL_TERMS):
        fail(f"cards[{card_index}] looks schedule-only; routine dates must stay out of published topics")

    validate_detail_sources(detail, card_index)
    validate_summary_basis(
        detail,
        title=title,
        issue_date=issue_date,
        source_date=source_date,
        card_index=card_index,
    )


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
        title = require_str(raw, "title")
        watch_topic_id = str(raw.get("watch_topic_id", "")).strip()
        summary = require_str(raw, "summary")
        section_id = require_str(raw, "section_id")
        category = require_str(raw, "category")
        source_date = require_str(raw, "source_published_date")
        detail = raw.get("detail")
        if not isinstance(detail, dict):
            fail(f"cards[{index}] missing detail object")
        slug = require_str(detail, "slug")
        detail = {**detail, "summary": require_str(detail, "summary")}
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
                "watch_topic_id": watch_topic_id,
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
        issue_dt.fromordinal(issue_dt.toordinal() - offset).isoformat()
        for offset in range(3)
    }


def display_cluster_key(card: dict[str, Any]) -> tuple[str, str]:
    text = str(card.get("title") or "")
    text = re.sub(r"\s+執筆(?:\s+[-–—].*)?$", " ", text)
    text = re.sub(r"\s+[-–—]\s+[^。]{1,120}$", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b", " ", text)
    text = re.sub(r"[^\w一-龥ぁ-んァ-ンー%％$]+", " ", text.lower())
    tokens = [
        token
        for token in text.split()
        if token
        and token
        not in {
            "news",
            "latest",
            "update",
            "updates",
            "発表",
            "速報",
            "ニュース",
            "最新",
            "確認",
        }
    ]
    return (str(card.get("category", "")), " ".join(tokens[:14]))


def display_cluster_seen(
    seen: set[tuple[str, str]],
    key: tuple[str, str],
) -> bool:
    category, text = key
    if not text:
        return False
    return any(
        category == seen_category
        and (
            text == seen_text
            or (len(text) >= 12 and seen_text.startswith(text))
            or (len(seen_text) >= 12 and text.startswith(seen_text))
        )
        for seen_category, seen_text in seen
    )


def rolling_display_cards(
    issue_path: Path,
    issue: dict[str, Any],
    current_cards: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issue_date = require_str(issue, "issue_date")
    allowed_source_dates = latest_three_dates(issue_date)
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    state_root = (
        issue_path.parent.parent
        if issue_path.parent.parent.exists()
        else DEFAULT_STATE_ROOT
    )
    display_cards: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_card(
        card: dict[str, Any],
        *,
        detail_issue_date: str,
        retained_from_issue_date: str | None = None,
    ) -> None:
        source_date = str(card.get("source_published_date", ""))
        if source_date not in allowed_source_dates or not public_card_is_reader_facing(card):
            return
        if retained_from_issue_date and any(
            str(existing.get("category", "")) == str(card.get("category", ""))
            and (
                same_material_event(
                    str(existing.get("title", "")),
                    str(card.get("title", "")),
                )
                or same_material_event(card_event_text(existing), card_event_text(card))
            )
            for existing in display_cards
        ):
            return
        key = display_cluster_key(card)
        if display_cluster_seen(seen, key):
            return
        seen.add(key)
        display_cards.append(
            {
                **card,
                "issue_date": issue_date,
                "detail_issue_date": detail_issue_date,
                "freshness_label": relative_day_label(issue_date, source_date),
                **(
                    {"retained_from_issue_date": retained_from_issue_date}
                    if retained_from_issue_date
                    else {}
                ),
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
        retained_raw_cards = [
            card
            for card in previous_issue.get("cards", [])
            if isinstance(card, dict)
            and str(card.get("source_published_date", "")) in allowed_source_dates
            and public_card_is_reader_facing(card)
        ]
        if not retained_raw_cards:
            continue
        for card in normalized_cards(
            {**previous_issue, "cards": retained_raw_cards}
        ):
            add_card(
                card,
                detail_issue_date=candidate_dt.isoformat(),
                retained_from_issue_date=candidate_dt.isoformat(),
            )

    return display_cards


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
    h2 {{ margin:0; font-size:23px; }} .priority, .cards {{ display:grid; gap:16px; align-items:stretch; }} .priority {{ grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); }} .cards {{ grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); }}
    .priority-card, .card {{ min-width:0; background:var(--panel); border:1px solid var(--line); border-top:4px solid var(--blue); border-radius:10px; padding:18px; display:flex; flex-direction:column; overflow:hidden; }}
    .priority-card.hot, .card.hot {{ border-top-color:var(--red); }} .priority-card.signal, .card.signal {{ border-top-color:var(--teal); }} .priority-card.macro, .card.macro {{ border-top-color:var(--amber); }}
    .rank {{ display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; margin-bottom:10px; border-radius:6px; background:var(--night); color:white; font-size:12px; font-weight:900; }}
    h3 {{ margin:0 0 8px; font-size:18px; line-height:1.36; overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }} p {{ margin:0 0 14px; overflow-wrap:anywhere; display:-webkit-box; -webkit-line-clamp:5; -webkit-box-orient:vertical; overflow:hidden; }} .meta {{ display:flex; flex-wrap:wrap; align-items:flex-start; gap:6px; margin-bottom:10px; color:var(--muted); }} .pill {{ display:inline-flex; align-items:center; max-width:100%; min-height:30px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }} .link, .tag {{ margin-top:auto; align-self:flex-start; }}
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


def validate_manifest_alignment(issue: dict[str, Any], cards: list[dict[str, Any]]) -> None:
    manifest = issue.get("coverage_manifest")
    if not isinstance(manifest, dict):
        fail("issue state missing coverage_manifest object")
    contract = read_json(CONFIG_PATH)
    issue_date = require_str(issue, "issue_date")
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
        evidence_hash = manifest.get("evidence_sha256")
        current_contract = expected_version == contract.get("contract_version")
        if evidence_hash is not None or current_contract:
            if not isinstance(evidence_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", evidence_hash):
                fail("coverage_manifest evidence_sha256 must be a SHA-256 hex digest")
    public_titles = [str(card.get("title")) for card in cards]
    if len(public_titles) != len(set(public_titles)):
        fail("cards must have unique public titles")


def validate_issue_evidence(
    issue: dict[str, Any],
    cards: list[dict[str, Any]],
    issue_path: Path | None,
    evidence_bundle: dict[str, Any] | None = None,
) -> None:
    if evidence_bundle is None and issue_path is None:
        return
    bundle = evidence_bundle or read_json(issue_path.parent / "evidence.json")
    issue_date = require_str(issue, "issue_date")
    if bundle.get("issue_date") != issue_date:
        fail("Evidence date does not match issue date")
    if issue_path is not None:
        evidence_path = issue_path.parent / "evidence.json"
        if evidence_path.exists():
            actual_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            expected_hash = issue.get("coverage_manifest", {}).get("evidence_sha256")
            if expected_hash is not None and expected_hash != actual_hash:
                fail("Issue was built from different Evidence content")
    checked_at = bundle.get("checked_at_jst")
    if not isinstance(checked_at, str) or not checked_at.startswith(issue_date):
        fail("research bundle checked_at_jst must be on the issue date")

    configured = {
        str(category["label"]): category
        for category in read_json(CONFIG_PATH).get("categories", [])
        if isinstance(category, dict)
    }
    bundle_categories = bundle.get("categories")
    if not isinstance(bundle_categories, dict) or set(bundle_categories) != set(configured):
        fail("research bundle must cover every configured category exactly once")
    registry = load_source_registry()
    evidence_contract_active = effective_on_or_after(
        read_json(CONFIG_PATH),
        "publication_evidence_contract_effective_date",
        issue_date,
    )
    cards_by_category: dict[str, list[dict[str, Any]]] = {}
    for card in cards:
        cards_by_category.setdefault(str(card.get("category")), []).append(card)

    for label, category in configured.items():
        entry = bundle_categories[label]
        if not isinstance(entry, dict):
            fail(f"research bundle category must be an object: {label}")
        checks = entry.get("source_checks")
        if not isinstance(checks, list) or not checks:
            fail(f"research bundle has no source checks: {label}")

        required_topics = {
            str(topic.get("id"))
            for topic in category.get("watch_topics", [])
            if isinstance(topic, dict)
        }
        checked_topics: set[str] = set()
        checked_urls: set[str] = set()
        observed_urls: set[str] = set()
        observed_by_topic: dict[str, set[str]] = {
            topic: set() for topic in required_topics
        }
        for index, check in enumerate(checks, start=1):
            if not isinstance(check, dict):
                fail(f"{label} source_checks[{index}] must be an object")
            url = check.get("url")
            state = check.get("slot_state")
            topics = check.get("watch_topic_ids")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                fail(f"{label} source_checks[{index}] has an invalid URL")
            if state not in {"observed_live", "source_unavailable"}:
                fail(f"{label} source_checks[{index}] has an invalid state")
            if not isinstance(topics, list) or any(topic not in required_topics for topic in topics):
                fail(f"{label} source_checks[{index}] has invalid watch topics")
            if not str(check.get("checked_at_jst", "")).startswith(issue_date):
                fail(f"{label} source_checks[{index}] has a stale check time")
            if not isinstance(check.get("evidence_summary"), str) or not str(
                check.get("evidence_summary")
            ).strip():
                fail(f"{label} source_checks[{index}] has no evidence summary")
            checked_topics.update(str(topic) for topic in topics)
            checked_urls.add(url)
            if state == "observed_live":
                observed_urls.add(url)
                for topic in topics:
                    observed_by_topic[str(topic)].add(url)

        seed_urls = {
            str(source.get("url"))
            for source in registry.get(label, [])
            if isinstance(source, dict)
        }
        if not seed_urls <= checked_urls:
            fail(f"{label} has seed sources without explicit result states")
        if not required_topics <= checked_topics:
            fail(f"{label} has unchecked watch topics")
        if not observed_urls:
            fail(f"{label} has no observed evidence URL")

        records = entry.get("records")
        record_by_url = {
            str(record.get("url")): record
            for record in records
            if isinstance(record, dict)
            and str(record.get("url", "")).startswith(("http://", "https://"))
        } if isinstance(records, list) else {}

        for card in cards_by_category.get(label, []):
            topic_id = str(card.get("watch_topic_id"))
            if topic_id not in required_topics:
                fail(f"{label} public update uses an unknown watch topic")
            detail = card.get("detail")
            if not isinstance(detail, dict):
                fail(f"{label} public update has no detail object")
            detail_urls = {
                str(source.get("url"))
                for source in detail.get("sources", [])
                if isinstance(source, dict)
            }
            if not detail_urls or not detail_urls <= observed_by_topic[topic_id]:
                fail(f"{label} public update cites unobserved evidence")
            if evidence_contract_active:
                source_date = str(card.get("source_published_date", ""))
                evidence_dates = {
                    str(record_by_url.get(url, {}).get("published_date") or "")
                    for url in detail_urls
                }
                if "" in evidence_dates or source_date not in evidence_dates:
                    fail(
                        f"{label} public update source date is not present in its Evidence"
                    )
            basis = detail.get("summary_basis")
            if not isinstance(basis, dict):
                fail(f"{label} public update has no summary basis")
            facts = basis.get("confirmed_facts")
            mappings = basis.get("fact_sources")
            if not isinstance(facts, list) or not isinstance(mappings, list):
                fail(f"{label} public update has invalid fact mappings")
            mapped = {
                str(mapping.get("fact")): {
                    str(url) for url in mapping.get("source_urls", [])
                }
                for mapping in mappings
                if isinstance(mapping, dict)
                and isinstance(mapping.get("source_urls"), list)
            }
            if set(str(fact) for fact in facts) != set(mapped):
                fail(f"{label} public update must map every fact exactly once")
            if any(not urls or not urls <= detail_urls for urls in mapped.values()):
                fail(f"{label} public update has a fact mapped outside its sources")


def validate_issue_state(
    issue: dict[str, Any],
    issue_path: Path | None = None,
    evidence_bundle: dict[str, Any] | None = None,
) -> None:
    issue_date = require_str(issue, "issue_date")
    if issue_path and issue_path.parent.name.startswith("20") and issue_path.parent.name != issue_date:
        fail(f"issue_date does not match state directory: {issue_date} != {issue_path.parent.name}")
    cards = normalized_cards(issue)
    validate_manifest_alignment(issue, cards)
    validate_issue_evidence(issue, cards, issue_path, evidence_bundle)


def build_coverage_manifest(
    issue_date: str,
    *,
    collection_mode: str,
    collection_completed_at_jst: str,
    evidence_sha256: str,
) -> dict[str, Any]:
    """Build the minimal publication metadata kept with an Issue."""
    contract = read_json(CONFIG_PATH)
    return {
        "contract_version": contract.get("contract_version"),
        "date": issue_date,
        "collection_completed_at_jst": collection_completed_at_jst,
        "collection_mode": collection_mode,
        "evidence_sha256": evidence_sha256,
        "editor_contract_sha256": editor_contract_sha256(),
    }


def editor_contract_sha256() -> str:
    digest = hashlib.sha256()
    for path in EDITOR_CONTRACT_PATHS:
        digest.update(str(path.relative_to(ROOT)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


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
    if write_marker:
        (output_root / ".night-signal-issue-date").write_text(issue_date + "\n", encoding="utf-8")
    return {
        "issue_date": issue_date,
        "cards": len(cards),
        "display_cards": len(display_cards),
        "sample_html": str(output_root / f"night-brief-web-sample-{issue_date}.html"),
        "marker_written": write_marker,
    }


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


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def self_test() -> None:
    issue_date = "2099-01-01"
    source_url = "https://openai.com/example"
    facts = [
        "OpenAIはCodex Securityの更新版を公開した。",
        "更新版には脆弱性検出後の修正支援が追加された。",
    ]
    card = {
        "watch_topic_id": "product_release",
        "title": "OpenAI、Codex Securityの更新版を公開",
        "summary": (
            "OpenAIはCodex Securityの更新版を公開し、脆弱性検出後の修正支援を追加した。"
            "企業のコード監査で、検出から修正までを一つの流れで扱える。"
        ),
        "section_id": "openai",
        "category": "OpenAI",
        "source_published_date": issue_date,
        "topic_value_class": "technical_or_product_shift",
        "priority_class": "priority",
        "detail": {
            "slug": f"openai-codex-security-{issue_date}.html",
            "sources": [{"label": "OpenAI", "url": source_url}],
            "summary": (
                "OpenAIはCodex Securityの更新版を公開し、脆弱性検出後の修正支援を追加した。"
                "企業のコード監査では、検出結果を修正作業へつなげられる。"
            ),
            "summary_basis": {
                "what_changed": "OpenAIがCodex Securityの更新版と修正支援機能を公開した。",
                "why_it_matters": "企業のコード監査で検出から修正までを一つの流れで扱える。",
                "confirmed_facts": facts,
                "fact_sources": [
                    {"fact": fact, "source_urls": [source_url]} for fact in facts
                ],
                "limits_or_unknowns": "提供地域と利用条件の詳細は公表資料の範囲に限られる。",
                "source_dates": [issue_date],
            },
        },
    }
    issue = {
        "issue_date": issue_date,
        "cards": [card],
        "coverage_manifest": build_coverage_manifest(
            issue_date,
            collection_mode="reviewed_live_web",
            collection_completed_at_jst=f"{issue_date}T19:30:00+09:00",
            evidence_sha256="0" * 64,
        ),
    }
    validate_issue_state(issue)
    rendered = render_issue_html(issue, normalized_cards(issue))
    if "候補" in rendered or "確認情報" in rendered:
        fail("renderer exposed a removed candidate or confirmation layer")
    detail_without_limits = dict(card["detail"])
    basis_without_limits = dict(detail_without_limits["summary_basis"])
    basis_without_limits.pop("limits_or_unknowns")
    detail_without_limits["summary_basis"] = basis_without_limits
    detail_without_limits.update(
        {
            "issue_date": issue_date,
            "section_id": card["section_id"],
            "kicker": card["category"],
            "title": card["title"],
            "h1": card["title"],
        }
    )
    rendered_detail = render_detail_html(detail_without_limits)
    if "未確定点" in rendered_detail:
        fail("detail renderer created an uncertainty absent from the source")
    detail_without_why = json.loads(json.dumps(detail_without_limits))
    detail_without_why["summary_basis"].pop("why_it_matters")
    render_detail_html(detail_without_why)
    headline_only = json.loads(json.dumps(card))
    headline_only["detail"]["summary_basis"]["confirmed_facts"] = [
        headline_only["title"]
    ]
    if public_card_is_reader_facing(headline_only):
        fail("headline-only card passed the reader-facing contract")
    if fact_adds_information(
        "Honda 2026年5月の生産・販売・輸出実績を発表",
        "Hondaは2026年6月29日に2026年5月の生産・販売・輸出実績を公式サイトで発表した。",
    ):
        fail("source channel and publication date were mistaken for substantive information")
    if not public_render_copy_violations(
        "はホンダのEV事業再編が強気材料になる可能性を分析した。",
        kind="summary",
    ):
        fail("public-copy validation accepted a sentence with a missing subject")
    if not public_render_copy_violations(
        "生成AIの全社展開を推進したが、具体的な導入や成果は本文からは確認できない。",
        kind="summary",
    ):
        fail("public-copy validation accepted a no-update summary")
    if not public_render_copy_violations("ホンダEV事業再編の分析（）", kind="title"):
        fail("public-copy validation accepted empty source brackets")
    if not navigation_shell_text(
        "B1ニュース一覧 B2ニュース一覧 日程結果 順位表 個人成績 選手名鑑"
    ):
        fail("public-copy validation accepted navigation shell text")
    leaked_source = dict(card)
    leaked_source["summary"] = f"{card['summary']} Example News"
    leaked_detail = dict(card["detail"])
    leaked_detail["sources"] = [
        {"label": "Example News", "url": "https://example.com/story"}
    ]
    leaked_source["detail"] = leaked_detail
    if not source_label_leaked(leaked_source):
        fail("retained-card validation accepted a leaked source label")
    if not re.fullmatch(r"[0-9a-f]{64}", editor_contract_sha256()):
        fail("editor contract fingerprint is invalid")
    if reader_summary_violations(card["title"], f"{card['title']}。{card['title']}。") == []:
        fail("summary validation accepted title repetition")
    print("NIGHT SIGNAL STATE PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema", choices=sorted(SCHEMAS))
    parser.add_argument("--readiness", action="store_true")
    parser.add_argument("--date", default=jst_today())
    parser.add_argument("--allow-blocked", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--generate-issue", type=Path)
    parser.add_argument("--validate-issue", type=Path)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    parser.add_argument("--no-marker", action="store_true")
    args = parser.parse_args()

    if args.schema:
        print_json(SCHEMAS[args.schema])
        return 0
    if args.self_test:
        self_test()
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
    if args.validate_issue:
        validate_issue_state(read_json(args.validate_issue), args.validate_issue)
        print_json({"issue_state": str(args.validate_issue), "valid": True})
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
