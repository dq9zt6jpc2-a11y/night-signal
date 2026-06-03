#!/usr/bin/env python3
"""Topic-value decision engine for NIGHT SIGNAL.

This module is the single place where a fresh candidate becomes a publishable
topic. It is intentionally schema-first: the same shape can be produced by
OpenAI Structured Outputs, or by the deterministic fallback below when an API
call is not available.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any


TOPIC_VALUE_CLASSES = [
    "decision_or_policy",
    "market_or_financial_impact",
    "technical_or_product_shift",
    "operational_status_change",
    "event_result_or_outcome",
    "material_schedule_change",
    "risk_or_safety_signal",
    "cultural_or_audience_signal",
]

WEAK_STANDALONE_CLASSES = {"material_schedule_change"}

TOPIC_VALUE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "adoption_decision",
        "topic_value_class",
        "reader_delta",
        "materiality_basis",
        "reject_reason_class",
        "reject_reason",
    ],
    "properties": {
        "adoption_decision": {"type": "string", "enum": ["adopt", "reject"]},
        "topic_value_class": {"type": "string", "enum": TOPIC_VALUE_CLASSES},
        "reader_delta": {"type": "string"},
        "materiality_basis": {"type": "string"},
        "reject_reason_class": {
            "type": ["string", "null"],
            "enum": [
                "duplicate_covered",
                "lower_importance",
                "no_material_change",
                "insufficient_evidence",
                "insufficient_relevance",
                None,
            ],
        },
        "reject_reason": {"type": ["string", "null"]},
    },
}

CLASS_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("operational_status_change", ("打ち上げ", "ミッション", "成功", "失敗", "延期", "中止", "scrub", "launch", "Starlink")),
    ("cultural_or_audience_signal", ("リバリー", "スポンサー", "公演", "ツアー", "観客", "ファン", "ブランド", "Maaden")),
    ("decision_or_policy", ("政策", "金融政策", "利上げ", "中央銀行", "規制", "承認", "日銀", "Fed")),
    ("market_or_financial_impact", ("PMI", "GDP", "輸出", "輸入", "金利", "物価", "賃金", "資金", "株", "売上", "利益", "ISM")),
    ("technical_or_product_shift", ("API", "モデル", "Codex", "製品", "リリース", "技術", "アップデート", "開発", "PU")),
    ("event_result_or_outcome", ("結果", "優勝", "受賞", "MVP", "勝利", "決勝結果", "完走")),
    ("risk_or_safety_signal", ("リスク", "安全", "事故", "供給不安", "燃料コスト", "規制対応", "不確実性")),
]

SCHEDULE_WORDS = ("予定", "日程", "開催", "開幕", "タイムテーブル", "カレンダー", "周")
MATERIAL_SCHEDULE_WORDS = ("変更", "延期", "前倒し", "中止", "新設", "追加", "正式発表", "新たに")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def has_any(text: str, words: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def classify_topic(text: str) -> str:
    for value_class, words in CLASS_PATTERNS:
        if has_any(text, words):
            return value_class
    if has_any(text, SCHEDULE_WORDS):
        return "material_schedule_change"
    return "risk_or_safety_signal"


def is_schedule_only(text: str, value_class: str) -> bool:
    if not has_any(text, SCHEDULE_WORDS):
        return False
    if value_class != "material_schedule_change":
        return False
    return not has_any(text, MATERIAL_SCHEDULE_WORDS)


def evaluate_topic_value(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized topic-value decision.

    The input is a compact candidate record with title, summary, claims, and
    source evidence. The output mirrors TOPIC_VALUE_SCHEMA, so a future OpenAI
    Structured Outputs call can replace this function without changing renderers.
    """

    title = str(candidate.get("title", ""))
    summary = str(candidate.get("summary", ""))
    claims = " ".join(str(claim.get("claim", "")) for claim in candidate.get("claim_verification", []) if isinstance(claim, dict))
    text = f"{title} {summary} {claims}"
    value_class = classify_topic(text)

    if is_schedule_only(text, value_class):
        return {
            "adoption_decision": "reject",
            "topic_value_class": value_class,
            "reader_delta": "予定表や開催前の状態だけでは、読者の見方を変える新しい決定、結果、資金、技術、安全リスクを示せない。",
            "materiality_basis": "日程確認は抽出ログの背景証跡に残せるが、単独カードとして扱う実質変化ではない。",
            "reject_reason_class": "no_material_change",
            "reject_reason": "予定表だけで、採用できる実質変化がない。",
        }

    reader_delta = str(candidate.get("reader_delta") or "")
    materiality_basis = str(candidate.get("materiality_basis") or "")
    if len(compact(reader_delta)) < 35:
        reader_delta = build_reader_delta(value_class, title, summary)
    if len(compact(materiality_basis)) < 35:
        materiality_basis = build_materiality_basis(value_class, summary)

    return {
        "adoption_decision": "adopt",
        "topic_value_class": value_class,
        "reader_delta": reader_delta,
        "materiality_basis": materiality_basis,
        "reject_reason_class": None,
        "reject_reason": None,
    }


def build_reader_delta(value_class: str, title: str, summary: str) -> str:
    if value_class == "market_or_financial_impact":
        return f"{title}により、単なる速報ではなく市場、金利、供給網、企業収益のどこに圧力が残るかを読み分けられる。"
    if value_class == "decision_or_policy":
        return f"{title}により、政策判断や企業決定の根拠が更新され、次に見るべき数値や発言の重みが変わる。"
    if value_class == "cultural_or_audience_signal":
        return f"{title}により、競技結果や製品発表だけでは見えないスポンサー露出、ブランド反応、観客接点の変化を確認できる。"
    if value_class == "operational_status_change":
        return f"{title}により、開発中の計画と実運用の進み方を分けて見られ、継続運用の安定性を判断しやすくなる。"
    return f"{title}は、読者が次に見るべきリスク、結果、数値、公式発表の重みを変える新しい材料を含む。"


def build_materiality_basis(value_class: str, summary: str) -> str:
    basis = first_sentence(summary)
    if value_class == "operational_status_change":
        suffix = "公式の運用状況として確認でき、開発計画と定常運用を分けて読む材料になるため採用対象になる。"
    elif value_class == "cultural_or_audience_signal":
        suffix = "競技結果ではなく、スポンサー露出やブランド文脈の変化として読者判断を更新できるため採用対象になる。"
    elif value_class == "market_or_financial_impact":
        suffix = "数値で確認でき、市場、金利、供給網、企業収益の見方を更新するため採用対象になる。"
    elif value_class == "decision_or_policy":
        suffix = "公式発言や政策判断の根拠として確認でき、次の市場反応を見る軸になるため採用対象になる。"
    else:
        suffix = "前号後に追加された事実と根拠URLで読者判断を更新できるため採用対象になる。"
    return f"{basis} {suffix}"


def first_sentence(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return "根拠付きの新規情報として確認できる。"
    match = re.search(r"(?<=[。！？!?])", normalized)
    if match:
        return normalized[: match.end()].strip()
    return normalized[:120].rstrip()


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--schema":
        print(json.dumps(TOPIC_VALUE_SCHEMA, ensure_ascii=False, indent=2))
        return 0
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        schedule = evaluate_topic_value({"title": "F1モナコGP、6月5日開幕", "summary": "決勝は6月7日に78周で行われる予定。"})
        if schedule["adoption_decision"] != "reject":
            raise SystemExit("schedule-only candidate should be rejected")
        material = evaluate_topic_value({"title": "米5月ISM製造業PMIは54.0", "summary": "価格と供給不安が残り、金利見通しの判断材料になる。"})
        if material["adoption_decision"] != "adopt":
            raise SystemExit("material market candidate should be adopted")
        livery = evaluate_topic_value({"title": "Aston Martin、モナコGP向けMaaden特別リバリーを公開", "summary": "スポンサー露出とブランド文脈が加わった。"})
        if livery["topic_value_class"] != "cultural_or_audience_signal":
            raise SystemExit("livery announcement should be treated as audience/brand signal")
        launch = evaluate_topic_value({"title": "SpaceX、6月3日にSLC-40発Starlinkミッションを設定", "summary": "公式LaunchesがFalcon 9 / Starlinkミッションを示す。"})
        if launch["topic_value_class"] != "operational_status_change":
            raise SystemExit("Starlink mission should be treated as operational status")
        print("TOPIC VALUE ENGINE PASSED")
        return 0
    data = json.load(sys.stdin)
    print(json.dumps(evaluate_topic_value(data), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
